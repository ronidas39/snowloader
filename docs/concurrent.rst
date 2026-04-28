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


Real-world numbers
------------------

A production extraction of 457,247 closed incidents from a customer
ServiceNow instance, with 23 fields per record and ``display_value=all``:

============================  ===============  ===========
Path                          Wall time        Rate
============================  ===============  ===========
Sequential ``get_records``    ~9 hours         ~14 rec/s
Async ``aget_records``         ~95 minutes      ~80 rec/s
Threaded ``concurrent_*``      **20 minutes**   **376 rec/s**
============================  ===============  ===========


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
