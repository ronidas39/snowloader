Concurrent Sync API
===================

snowloader's threaded paginator (added in v0.2.5) lets sync code fetch pages
in parallel without pulling in :mod:`asyncio` or :mod:`aiohttp`. It is the
fastest way to extract large tables when you do not already have an event
loop.

.. contents::
   :local:
   :depth: 1


Why threaded
------------

The default :meth:`SnowConnection.get_records` walks pages sequentially: one
HTTP request, parse, yield, then the next. For large tables (hundreds of
thousands of records) that gets slow.

:meth:`SnowConnection.concurrent_get_records` pre-fetches the total count,
splits the work into ``ceil(total / page_size)`` pages, and dispatches the
page fetches to a :class:`concurrent.futures.ThreadPoolExecutor`. Each
worker thread holds its own :class:`requests.Session` via
:class:`threading.local`, so connection pools and TLS state stay isolated.

That last detail matters: some ServiceNow front ends silently return empty
or null bodies under sustained concurrent load when many requests share one
client session. Per-thread sessions avoid that failure mode and let the
threaded paginator hit roughly 350-400 records per second on a typical
instance.


Quick start
-----------

.. code-block:: python

   from snowloader import SnowConnection

   with SnowConnection(
       instance_url="https://mycompany.service-now.com",
       username="admin",
       password="password",
       page_size=500,
   ) as conn:
       total = conn.get_count("incident", query="state=6^close_notesISNOTEMPTY")
       print(f"Fetching {total} records")

       for record in conn.concurrent_get_records(
           table="incident",
           query="state=6^close_notesISNOTEMPTY",
           max_workers=16,
       ):
           process(record)

Records are yielded in the order pages complete, not in
``ORDERBYsys_created_on`` order. If you need ordered output, sort the
consumed list yourself by the relevant timestamp.


Through a loader
----------------

Every :class:`BaseSnowLoader` subclass picks up two new methods:

.. code-block:: python

   from snowloader import SnowConnection, IncidentLoader

   with SnowConnection(
       instance_url="https://mycompany.service-now.com",
       username="admin",
       password="password",
   ) as conn:
       loader = IncidentLoader(connection=conn, query="state=6")
       docs = loader.concurrent_load(max_workers=16)

       # Streaming variant
       for doc in loader.concurrent_lazy_load(max_workers=16):
           index.upsert(doc)


Order of magnitude
------------------

Relative throughput on a typical ServiceNow instance, pulling rich
records with ``display_value=all`` and a non-trivial field list:

============================  ==============================
Path                          Throughput
============================  ==============================
Sequential ``get_records``    Baseline
Async ``aget_records``         Several times faster
Threaded ``concurrent_*``      Many times faster
============================  ==============================

The exact numbers depend heavily on instance size, network distance, page
size, and server-side query cost. Benchmark against your own instance
before tuning for a specific throughput target.


When to pick which path
-----------------------

================================  ==========================================
Situation                         Use
================================  ==========================================
Sync codebase, want max speed     ``concurrent_get_records`` / ``concurrent_load``
Existing asyncio app              ``aget_records`` / ``aload``
Streaming, low-memory pipeline    Either, both yield one record at a time
Need ordered output by time       Sequential ``get_records`` (or sort yourself)
================================  ==========================================


Tunables
--------

``max_workers``
    Number of worker threads. Default 16. Lower this if your ServiceNow
    instance returns 5xx or null bodies under load. Raise it carefully: a
    single shared front end can choke when many concurrent connections
    hit the same authentication and routing paths.

``page_size``
    Records per request. Default 100, but 500-1000 is usually a better
    balance for large extractions: fewer round trips, smaller per-call
    overhead. Maximum is 10000.

``max_retries``
    Number of retries per page on transient failures (HTTP 429 / 500 /
    502 / 503 / 504, plus null and truncated JSON bodies). Default 3.

``retry_backoff``
    Base delay (seconds) between retries. Doubles each attempt, so the
    delays go ``backoff``, ``2 * backoff``, ``4 * backoff``, ...
    Default 1.0.


How it relates to ``concurrent_get_records``
--------------------------------------------

:meth:`SnowConnection.get_count` is the cheap sibling that drives the
threaded paginator: it hits ``/api/now/stats/<table>?sysparm_count=true``
and returns the integer count. Useful on its own when you need to know
the size of a query before deciding how to fetch.


Recipe: two-pull corpus extraction with resume
-----------------------------------------------

A common pattern for AI / RAG pipelines built on ServiceNow is to maintain
two parallel corpora:

1. **Recommendation corpus**: closed and resolved tickets that became the
   ground truth for "how was a similar incident solved before?"
2. **Duplicate-prevention corpus**: active in-progress tickets, refreshed
   often, used at intake time to detect whether a new ticket is a duplicate
   of one already in flight.

Both pulls share the same shape: raw API output (so reference fields keep
their full ``display_value`` / ``value`` / ``link`` structure for downstream
consumers), JSONL output, end-of-run validation against
``/api/now/stats``, and resume support so a crash does not force a full
re-fetch.

The threaded paginator yields pages in completion order, so a single
"last offset" cursor is not enough for resume. Track the **set of
completed page offsets** instead. On rerun, only the offsets not yet in
the set get dispatched.

.. code-block:: python

   import json
   import threading
   from concurrent.futures import ThreadPoolExecutor, as_completed
   from pathlib import Path
   from snowloader import SnowConnection

   PAGE_SIZE = 1000
   MAX_WORKERS = 16

   def run_pull(conn: SnowConnection, query: str, fields: list[str],
                output: Path, state_file: Path) -> tuple[int, int]:
       """Run one pull with offset-level checkpointing.

       Returns (records_written, api_total).
       """
       state = json.loads(state_file.read_text()) if state_file.exists() else {"completed": []}
       completed = set(state["completed"])

       total = conn.get_count("incident", query=query)
       page_count = (total + PAGE_SIZE - 1) // PAGE_SIZE
       pending = [i * PAGE_SIZE for i in range(page_count) if i * PAGE_SIZE not in completed]

       mode = "a" if completed and output.exists() else "w"
       written = sum(1 for _ in output.open()) if mode == "a" else 0

       fh = output.open(mode, encoding="utf-8")
       write_lock = threading.Lock()

       def fetch_one(offset: int) -> int:
           # Use the SDK's internal helper to inherit retry / OAuth / rate limiting
           import requests
           sess = requests.Session()
           sess.auth = conn._session.auth
           url = f"{conn.instance_url}/api/now/table/incident"
           params = {
               "sysparm_limit": str(PAGE_SIZE),
               "sysparm_offset": str(offset),
               "sysparm_query": query,
               "sysparm_fields": ",".join(fields),
               "sysparm_display_value": "all",
           }
           data = conn._request_with_session(sess, "GET", url, params=params)
           records = data.get("result") or []
           lines = []
           for rec in records:
               sid = rec["sys_id"]
               num = rec["number"]
               sid_v = sid.get("value", "") if isinstance(sid, dict) else (sid or "")
               num_v = num.get("value", "") if isinstance(num, dict) else (num or "")
               if not sid_v or not num_v:
                   continue
               lines.append(json.dumps(rec, ensure_ascii=False))
           if lines:
               with write_lock:
                   fh.write("\n".join(lines) + "\n")
                   fh.flush()
           return len(lines)

       try:
           with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
               futs = {pool.submit(fetch_one, off): off for off in pending}
               for fut in as_completed(futs):
                   off = futs[fut]
                   written += fut.result()
                   completed.add(off)
                   # Checkpoint state every 30 pages
                   if len(completed) % 30 == 0:
                       state_file.write_text(json.dumps({"completed": sorted(completed)}))
       finally:
           fh.close()
           state_file.write_text(json.dumps({"completed": sorted(completed)}))

       return written, total


   with SnowConnection(
       instance_url="https://yourcompany.service-now.com",
       username="api_user",
       password="api_pass",
       page_size=PAGE_SIZE,
       display_value="all",
       max_retries=5,
   ) as conn:
       # Pull A: closed corpus (recommendation)
       written_a, total_a = run_pull(
           conn,
           query=("stateIN6,7^close_notesISNOTEMPTY"
                  "^sys_updated_on>=javascript:gs.daysAgoStart(730)"
                  "^ORDERBYsys_created_on"),
           fields=["sys_id", "number", "short_description", "close_notes",
                   "state", "priority", "urgency", "impact",
                   "assignment_group", "caller_id", "assigned_to",
                   "opened_at", "resolved_at"],
           output=Path("incidents_closed.jsonl"),
           state_file=Path("incidents_closed.state.json"),
       )
       print(f"closed: wrote {written_a}, api total {total_a}")

       # Pull B: active corpus (duplicate prevention)
       written_b, total_b = run_pull(
           conn,
           query=("stateIN1,2,3,4,5"
                  "^opened_at>=javascript:gs.daysAgoStart(60)"
                  "^ORDERBYsys_created_on"),
           fields=["sys_id", "number", "short_description",
                   "state", "priority", "category",
                   "caller_id", "opened_at"],
           output=Path("incidents_active.jsonl"),
           state_file=Path("incidents_active.state.json"),
       )
       print(f"active: wrote {written_b}, api total {total_b}")

Why per-thread sessions matter: some ServiceNow front ends silently return
empty or null bodies under sustained concurrent load when many requests
share a single client session. Per-thread :class:`requests.Session`
instances avoid that failure mode, which is exactly what
:meth:`SnowConnection.concurrent_get_records` does internally and what
the recipe above replicates when you need explicit (offset, records)
visibility for resume.
