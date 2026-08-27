Async Usage
===========

Starting in v0.2, snowloader ships an async API built on `aiohttp`. Every
sync loader has a matching ``Async*`` variant that fetches pages
concurrently, so it is much faster than walking pages one at a time.

Why async, and when not
-----------------------

The default :class:`~snowloader.SnowConnection` walks pages one after
another. That works fine for small tables but becomes the bottleneck on
production instances with hundreds of thousands of records. Concurrent
fetching turns a multi-hour sequential extraction into a matter of minutes.

**It is not, however, the fastest path.** Measured against a developer
instance sweeping ``cmdb_ci``, 2,919 rows, projecting one field:

============================================  ========
Path                                              Time
============================================  ========
``get_records`` sequential                       46.4s
``aget_records`` async, page_size 500             9.7s
``concurrent_get_records`` threaded, w=16          6.4s
============================================  ========

Async beat the sequential path by about five times and the threaded sync
paginator beat it again. Reach for async because you are already in an event
loop and want to stay in it, not because you expect it to be the quickest
way to move records. If throughput is what you are after and you are not
already async, see :doc:`concurrent`.

Installation
------------

The async path requires ``aiohttp`` as an optional dependency:

.. code-block:: bash

   pip install snowloader[async]

   # or pull everything (async + langchain + llamaindex)
   pip install snowloader[all]

Quick start
-----------

.. code-block:: python

   import asyncio
   from snowloader import AsyncSnowConnection, AsyncIncidentLoader

   async def main() -> None:
       async with AsyncSnowConnection(
           instance_url="https://mycompany.service-now.com",
           username="admin",
           password="password",
           page_size=100,
           concurrency=16,
       ) as conn:
           loader = AsyncIncidentLoader(connection=conn, query="active=true")
           docs = await loader.aload()
           print(f"Loaded {len(docs)} incidents")

   asyncio.run(main())

The connection is an async context manager. Pages are fetched in parallel
up to the ``concurrency`` limit. Records are yielded in completion order,
not insertion order, so sort the result if you need a stable ordering.

Streaming with alazy_load
-------------------------

For large tables, prefer :meth:`alazy_load` over :meth:`aload`. The first
returns an async iterator and keeps memory flat:

.. code-block:: python

   async with AsyncSnowConnection(...) as conn:
       loader = AsyncIncidentLoader(connection=conn)
       async for doc in loader.alazy_load():
           process(doc)

Delta sync
----------

Same pattern as the sync API, just async:

.. code-block:: python

   from datetime import datetime, timezone

   since = datetime.now(timezone.utc) - timedelta(days=1)
   async with AsyncSnowConnection(...) as conn:
       loader = AsyncIncidentLoader(connection=conn)
       new_docs = await loader.aload_since(since)

aconcurrent_get_records
-----------------------

:meth:`aget_records` has always fetched pages concurrently.
:meth:`aconcurrent_get_records` is the same method under the name someone
coming from :meth:`SnowConnection.concurrent_get_records` reaches for, and it
takes ``max_workers`` to match that signature:

.. code-block:: python

   async for record in conn.aconcurrent_get_records(
       "cmdb_ci",
       max_workers=16,
       verify=True,
   ):
       process(record)

Tuning concurrency
------------------

The ``concurrency`` argument caps the number of pages fetched in parallel.
A higher number is faster but increases pressure on your ServiceNow
instance and may trigger rate limiting (429 responses). Start with the
default of 16 and adjust based on observed performance and any 429s in the
logs.

Page size, and why the async default is larger
----------------------------------------------

``AsyncSnowConnection`` defaults ``page_size`` to 500 where the sync class
uses 100. Measured against a developer instance sweeping ``cmdb_ci``, 2,919
rows, projecting one field, twice:

=====================================================  =======  =======
Configuration                                            run 1    run 2
=====================================================  =======  =======
``page_size=500``, concurrency 16                         9.7s    13.8s
``page_size=100``, concurrency 16                        18.4s    25.0s
``page_size=100``, concurrency 8                         19.6s    13.2s
``page_size=100``, concurrency 16, ``keep_alive=True``   21.7s    15.4s
=====================================================  =======  =======

Read that table carefully, because only one row-pair says anything solid.
Bigger pages beat smaller ones by roughly two to one in **both** runs, which
is why the default is 500. Everything else moved by more between the two runs
than it did between configurations: concurrency 8 was worse than 16 in run 1
and better in run 2, and keep-alive went the same way. A developer instance
is small and shared, so that is noise, not a finding.

Note also that this is the opposite of the advice for the threaded sync path,
where page size in the low hundreds measured best. Do not carry a page size
from one to the other, and measure your own instance before tuning either.

keep_alive
----------

``AsyncSnowConnection`` disables HTTP keep-alive by default, so every request
pays a fresh TCP and TLS handshake. That is deliberate. Some ServiceNow front
ends, and shared WAF layers in front of them, return empty or null response
bodies on reused connections under concurrent load, which corrupts a
paginated read without failing it.

``keep_alive=True`` turns connection reuse back on. It is worth knowing that
it is not reliably faster either: in the table above it came out slightly
slower than leaving it off. Treat it as something to measure on your own
instance rather than a free win, and verify the sweep afterwards:

.. code-block:: python

   async with AsyncSnowConnection(..., keep_alive=True) as conn:
       records = [
           rec async for rec in conn.aget_records("cmdb_ci", verify=True)
       ]

One caution on lowering ``page_size`` here. More pages means more concurrent
requests, and on a busy instance that is when the null-body responses show
up. A sweep at ``page_size=100`` exhausted the default three retries during
this benchmarking and raised; the same sweep with ``max_retries`` raised
completed cleanly. If you see that, raise ``max_retries`` rather than
assuming the data is gone, and use ``verify=True`` so you would know.

Certificate verification on macOS
---------------------------------

If the sync connection works and the async one fails with
``SSLCertVerificationError: unable to get local issuer certificate``, the
problem is the CA bundle rather than snowloader. ``requests`` ships
``certifi`` and uses it; ``aiohttp`` uses the standard library's default SSL
context, and a Python installed from python.org on macOS does not populate
that until you run the ``Install Certificates.command`` in its
``/Applications/Python 3.x/`` folder.

Running that fixes it permanently. To fix it for one process instead:

.. code-block:: bash

   export SSL_CERT_FILE="$(python -c 'import certifi; print(certifi.where())')"

Ordering and verification
-------------------------

The async connection takes ``order_by``, ``since_field``, ``verify`` and
``on_error`` exactly as the sync one does, and its ORDERBY chain ends in
``sys_id`` for the same reason. See :doc:`verification`.

When you should still use the sync API
--------------------------------------

* You are running inside a synchronous codebase that does not have an
  event loop and you do not want to use ``asyncio.run`` for every call.
* You need :meth:`CMDBLoader` relationship traversal, which has not been
  ported to the async path yet. :class:`~snowloader.RelationshipLoader` is
  usually the better answer anyway, and it is sync.
* You only have a few hundred records to load and the simplicity of the
  sync API matters more than raw speed.

For throughput on a large table the threaded sync paginator is generally the
faster of the two. The async API is for integrating with an async caller, not
for going faster than threads. See :doc:`concurrent`.

LangChain and LlamaIndex async adapters
---------------------------------------

The framework adapters expose async variants too. Their names are
prefixed with ``Async``:

.. code-block:: python

   from snowloader import AsyncSnowConnection
   from snowloader.adapters.langchain import AsyncServiceNowIncidentLoader

   async def main() -> None:
       async with AsyncSnowConnection(...) as conn:
           loader = AsyncServiceNowIncidentLoader(
               connection=conn, query="active=true"
           )
           docs = await loader.aload()  # list[langchain_core.documents.Document]

   asyncio.run(main())

The LlamaIndex variant exposes ``aload_data`` and ``aload_data_since``:

.. code-block:: python

   from snowloader.adapters.llamaindex import AsyncServiceNowIncidentReader

   async with AsyncSnowConnection(...) as conn:
       reader = AsyncServiceNowIncidentReader(connection=conn)
       documents = await reader.aload_data()
