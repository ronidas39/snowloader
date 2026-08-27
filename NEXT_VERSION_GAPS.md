# snowloader: what a real graph build needed from it

Written 27 Aug 2026, against **v0.2.8**, validated against a developer instance
(2,919 CIs, 220 relationships, incidents, KB articles).

This replaces the earlier version of this document, which was written after
reading the package and probing it. Since then I have built the thing it was
written for: generate an estate, write it into ServiceNow, read it back through
snowloader, and load it into Neo4j as a joined graph. 415 records and 105
relationships, end to end, working.

Building it changed my mind about what matters. The top of the old list was
right. The middle of it was wrong, and I have moved two items I called blockers
down to nice to have, because once I was actually writing the code I never
wanted them.

Everything below is measured on a live instance. Where I give a number, it came
out of a run, not an estimate.

---

## The short version

| | Item | Old rank | Now |
|---|---|---|---|
| 1 | Pagination orders by a non-unique column and silently loses rows | 0, critical | **critical, unchanged** |
| 2 | A sweep cannot prove it was complete | not listed | **blocker, new** |
| 3 | Reference fields do not give both halves | 1, blocker | **blocker, unchanged** |
| 4 | Async is slower than threaded and looks like the fast path | 0b | important |
| 5 | Concurrency defaults are not the measured optimum | not listed | important, new |
| - | Generic TableLoader | 2, blocker | **dropped** |
| - | RelationshipLoader | 3, blocker | **dropped** |
| - | Keyset pagination, raw record, partial failure, resume, load_since | 4 to 8 | unchanged, still worth doing |

Items 1, 2 and 3 are what a graph build actually needs. If those three land I
would recommend this package to anyone doing the same job.

---

## 1. Pagination orders by a non-unique column and silently loses rows

**Severity: critical. Fix this before anything else.**

`_build_query_params` appends `ORDERBYsys_created_on` to every request, in both
`connection.py` and `async_connection.py`. That column is not unique. On this
instance 2,784 rows shared only 807 distinct `sys_created_on` values, and the
worst tie had 31 rows on one timestamp.

ServiceNow does not guarantee a stable order inside a tie, so an offset page
boundary that lands inside a tied group returns some rows twice and skips
others.

Three consecutive sweeps, sequential path, no concurrency involved:

    run 1: returned=2784 unique=2775 lost=9 duplicated=9 count_matches_api=True
    run 2: returned=2784 unique=2775 lost=9 duplicated=9 count_matches_api=True
    run 3: returned=2784 unique=2775 lost=9 duplicated=9 count_matches_api=True

Two things about that are worse than they first look.

**The count reconciles.** `X-Total-Count` is 2,784 and the sweep returns exactly
2,784 rows. Nine records were replaced by nine duplicates. Nothing anywhere
reports a problem.

**The loss is deterministic.** Across three runs, the set of records that came
back was identical every time. The same nine are always missing. Re-running
never surfaces it, and comparing two runs against each other shows nothing,
because they agree with each other and are both wrong. The CIs lost on this
instance were Visual Studio, SQL Server, Visual C++, Visual Basic, Visual J++,
Visual Modeler, StarGate, CD Burner and What's This? Help Composer.

Loss rate 0.32 percent. On a 30,000 row CMDB sweep that is about 100 missing
CIs, and for a CMDB feeding a dependency graph, missing CIs means missing
dependencies means a wrong blast radius, with nothing downstream able to detect
it.

**Fix, one line, two call sites:**

```python
query_parts.append("ORDERBYsys_id")
# or, to keep the chronological intent with a deterministic tiebreak:
query_parts.append("ORDERBYsys_created_on^ORDERBYsys_id")
```

Confirmed working. Same table, same instance, same session:

    get_records (default)                   lost=9  dup=9  LOSSY
    get_records query=ORDERBYsys_id         lost=0  dup=0  CLEAN
    concurrent_get_records (default)        lost=9  dup=9  LOSSY
    concurrent_get_records ORDERBYsys_id    lost=0  dup=0  CLEAN

Worth a regression test that sweeps a table with heavy timestamp ties and
asserts `len(rows) == len(set(sys_ids)) == X-Total-Count`.

Note for anyone who needs this before you ship it: because the caller's query is
prepended, passing `query="ORDERBYsys_id"` produces
`ORDERBYsys_id^ORDERBYsys_created_on` and the unique key wins. So it can be
worked around from outside the package. That is what I did. It does not help
anyone who has pip installed 0.2.8 and does not know to do it.

---

## 2. A sweep cannot prove it was complete

**Severity: blocker. This is the one I would build first after the fix above.**

This was not in the old list and it should have been at the top of it. It is the
general form of item 1: after any sweep, I have no way to ask the library
whether it got everything.

I wrote this by hand and it became the most valuable thing in my pipeline:

```python
api_count = conn.get_count(table, query=query)
rows = list(conn.concurrent_get_records(table, query=f"{query}^ORDERBYsys_id"))
distinct = {r["sys_id"]["value"] for r in rows}
if len(distinct) != api_count:
    raise SweepError(...)
```

What I want instead:

```python
rows = conn.get_records("cmdb_ci", verify=True)   # raises if distinct != X-Total-Count
```

Once the ordering is fixed this check finds nothing, and that is exactly the
point. I can trust a sweep instead of hoping about it. Every unattended run I
do from here has this assertion in it, and it should not be my code.

It also means nobody has to independently rediscover item 1 in order to be safe
from it.

---

## 3. Reference fields do not give both halves

**Severity: blocker.**

A graph is built out of identifiers. The loaders return labels.

`IncidentLoader` metadata on this instance carries 15 keys, and:

| Field | What came back |
|---|---|
| `sys_id` | `"{'display_value': '8d6353ea...', 'value': '8d6353ea...'}"`, a stringified dict |
| `assigned_to` | `"David Loo"`, no sys_id anywhere |
| `caller_id`, `opened_by` | absent from metadata entirely |
| `cmdb_ci`, `assignment_group` | empty string |

No `*_sys_id` companion key exists on any loader. So an incident cannot be
joined to its CI, its caller, or its assignment group. `sys_id` being a
stringified dict is a plain bug regardless of anything else here, because it is
the primary key.

The data is not lost, the loaders are discarding it. The raw connection with
`display_value="all"` has everything:

    sys_id      display=0c5f3cec...              value=0c5f3cece1b12010f877971dea0b1449
    caller_id   display=survey user              value=005d500b536073005e0addeeff7b12f4
    opened_by   display=System Administrator     value=6816f79cc0a8016401c5a33be04be441
    priority    display=5 - Planning             value=5

**What I want:** every reference field surfaced as both halves, consistently,
on every loader. Either the flat form:

```python
metadata["assignment_group"]         # 'Service Desk'
metadata["assignment_group_sys_id"]  # 'd625dcce...'
```

or an accessor:

```python
rec["cmdb_ci"].value    # sys_id, joinable
rec["cmdb_ci"].label    # readable
```

I do not much mind which. I mind that today every consumer writes this helper
themselves.

**And they will write it wrong.** I wrote mine twice today and got it wrong the
second time: I read the display half of `sys_class_name`, got `"MySQL Instance"`
where I needed `"cmdb_ci_db_mysql_instance"`, and filed 25 databases as
application services. Silently. Every count still added up to 415. If I can do
that having just written the document complaining about it, a library shipping
one helper for this would pay for itself immediately.

---

## 4. Async is slower than threaded, and looks like the fast path

**Severity: important.**

First a correction to the old version of this document, which claimed the README
documents `aconcurrent_get_records`. It does not. That name appears nowhere in
the repo except in the old document itself. I was wrong about that.

The real finding stands and is bigger. `concurrent_get_records` exists on the
sync path at `connection.py:381` and has no async counterpart. The async surface
is `aclose`, `aget_count`, `aget_records`, `aget_record`, `aget_attachment`.
`aget_records` pages sequentially, so async pays the overhead and collects none
of the parallelism.

Measured, `cmdb_ci`, 2,919 rows, page_size 100, all returning complete data:

| Path | Time | vs sequential |
|---|---:|---:|
| `get_records` sequential | 31.7s | baseline |
| `concurrent_get_records` w=4 | 9.0s | 3.5x |
| `concurrent_get_records` w=8 | 6.0s | 5.3x |
| `concurrent_get_records` w=16 | 4.8s | 6.7x |
| `concurrent_get_records` w=32 | 4.6s | 6.9x |
| `aget_records` async | 20.8s | 1.5x |

Async is 4.3 times slower than threaded on identical work. It is correct, it
returned all 2,919 distinct rows, it is just pointless. Someone reaching for the
async API to go faster gets the opposite, and there is nothing in the docs to
warn them.

**What I want:** implement `aconcurrent_get_records`, or say plainly in the docs
that the threaded path is the fast one and async exists for integration with an
async caller rather than for throughput.

---

## 5. The concurrency defaults are not the measured optimum

**Severity: important, and cheap.**

Two things I had to find by measuring that the library could just know.

**Workers.** Threading scales to 16 and then flattens. 32 buys 4 percent over
16. A default of 16 on `concurrent_get_records` would be right for most people.

**Page size, which surprised me.** Bigger pages are worse:

    concurrent w=16, page_size=100    4.8s
    concurrent w=16, page_size=500    6.7s

Forty percent slower, because 2,919 rows becomes 6 pages instead of 30 and there
is less to parallelise. The obvious tuning instinct is exactly backwards, and it
is worth a sentence in the docs.

---

## What I dropped, and why

The old document called these blockers. Having built the thing, I would not
spend your time on them next.

**Generic TableLoader (old gap 2).** I listed fifteen tables with no loader and
said this removed 80 percent of my reason to bypass the package. In practice I
bypassed the loaders entirely and never missed them. `concurrent_get_records`
reached every table I needed. What I wanted from a table was the raw records,
which is what the connection already gives me, and `SnowDocument`'s assembled
prose is the opposite of useful for graph work. Still worth having for RAG
users. Not a blocker.

**RelationshipLoader (old gap 3).** I still stand by everything I said about
`CMDBLoader(include_relationships=True)` being unusable at scale. Measured:

    CMDBLoader per-CI traversal      1.86s per CI  ->  25.8 hours for 50,000 CIs
    one direct cmdb_rel_ci sweep     2.2s for 220 rows

But the direct sweep was two lines, and `parent`, `child` and `type` all came
back as `{display_value, value}` with both halves populated, so the edges were
directly loadable with no resolution step. The workaround is so easy that a
dedicated loader is a convenience, not a blocker.

**Old items 4 to 8** (keyset pagination, raw record access, defined partial
failure behaviour, resume, `load_since` column) I did not exercise properly at
this volume. I stand by them as written. Item 6, partial failure, gets more
important the moment anyone runs this unattended.

---

## On write support

Do not put writes in snowloader.

I needed writes today, roughly 17,500 records eventually. The write leg cost
about 40 lines of `requests`. It was never the hard part.

The hard part was what ServiceNow does to a write, and I hit three of them in
one afternoon on a stock developer instance:

- a Data Policy making `close_code` and `close_notes` mandatory once an incident
  reaches resolved or closed
- a choice list for `incident.close_code` that had been replaced, so values
  copied off existing records in the same table are rejected
- a Change Model business rule refusing any insert that declares a `state` other
  than the model's own opening one

A read library that starts writing has to grow opinions about all of that or it
becomes a polite way to corrupt a CMDB. And the read-only guarantee is worth
something on its own: it is the reason somebody points this at production
without raising a change.

If you want a write story, make it a sibling package or an opt-in extra with its
own import, sharing the connection, auth and retry. Then "snowloader does not
write" stays true of the thing people install by default.

Two things I did need on the write side that are worth stealing for it:

**Retry.** The instance intermittently answers a write with an empty or
non-JSON body under load. Reads get retried inside snowloader; writes had
nothing. Note that a 4xx should not be retried, that is the instance refusing
the data rather than failing to handle it.

**Per-thread sessions.** `requests.Session` is not safe to share across threads,
and sharing one measured 1.75 times slower than one per thread at 8 workers
(7.2s against 4.1s for the same 24 records).

Write throughput, for whoever builds this:

| Workers | `cmdb_ci_linux_server` | `incident` |
|---:|---:|---:|
| 8 | 4.6 rec/s | 2.5 rec/s |
| 16 | 9.5 rec/s | 3.0 rec/s |
| 24 | 9.4 rec/s | 3.3 rec/s |
| 32 | 7.6 rec/s | 4.1 rec/s |

CI inserts peak at 16 and fall off. Task inserts are about two and a half times
slower because of the business rules that run on them, and they were still
improving at 32. The two families want different concurrency.

---

## What the build actually did

For context on where all of the above came from.

Generated 415 records and 105 relationships, wrote them to the instance, read
them back through snowloader, and loaded them into Neo4j as a joined graph.

    push   415 records + 105 edges          81s
    read   415 records, all sweeps complete 73s
    load   415 nodes, 385 edges, 0 dangling

Every record written came back. Every edge resolved to a node that exists. The
read used `SnowConnection` with `display_value="all"` and `query="ORDERBYsys_id"`,
and did not use the loaders at all.

That last sentence is the honest summary of this document. The plumbing in this
package is good, and I used it. The loader layer on top of it is built for
retrieval, and for graph work I had to go around it.
