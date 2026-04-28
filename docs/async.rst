Async Usage
===========

Starting in v0.2, snowloader ships an async API built on `aiohttp`. Every
sync loader has a matching ``Async*`` variant that fetches pages
concurrently against a single shared session, which makes large extractions
dramatically faster than the sequential path.

Why async
---------

The default :class:`~snowloader.SnowConnection` walks pages one after
another. That works fine for small tables but becomes the bottleneck on
production instances with hundreds of thousands of records. Real-world
benchmarks show a 16-thread parallel fetch finishing a 457,000-incident
extraction in under 20 minutes, where the sequential path would take
roughly nine hours.

The async API provides the same speedup without you having to manage
threads, sessions, or page offsets manually.

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
           page_size=500,
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

Tuning concurrency
------------------

The ``concurrency`` argument caps the number of pages fetched in parallel.
A higher number is faster but increases pressure on your ServiceNow
instance and may trigger rate limiting (429 responses). Start with the
default of 16 and adjust based on observed performance and any 429s in the
logs.

When you should still use the sync API
--------------------------------------

* You are running inside a synchronous codebase that does not have an
  event loop and you do not want to use ``asyncio.run`` for every call.
* You need :meth:`CMDBLoader` relationship traversal, which has not been
  ported to the async path yet.
* You only have a few hundred records to load and the simplicity of the
  sync API matters more than raw speed.

For everything else, the async API is the recommended path going forward.

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
