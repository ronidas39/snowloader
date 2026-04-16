Roadmap
=======

snowloader is under active development. Here is what is planned for
upcoming releases.

v0.2 - Async & Attachments (Coming Soon)
-----------------------------------------

**Async support (aiohttp + async for)**

The current implementation is synchronous. For workloads like CMDB
relationship traversal (2 API calls per CI) and journal fetching (1 call
per record), async I/O will deliver 10-50x performance improvements.

Planned API:

.. code-block:: python

   import asyncio
   from snowloader import AsyncSnowConnection, AsyncIncidentLoader

   async def main():
       async with AsyncSnowConnection(
           instance_url="...",
           username="...",
           password="...",
       ) as conn:
           loader = AsyncIncidentLoader(connection=conn, query="active=true")
           async for doc in loader.lazy_load():
               print(doc.page_content[:100])

   asyncio.run(main())

**Attachment loader**

Download files attached to ServiceNow records via the ``sys_attachment``
API. Supports binary files (PDFs, images, spreadsheets) and integrates
with document parsing libraries.

Planned API:

.. code-block:: python

   from snowloader import AttachmentLoader

   loader = AttachmentLoader(
       connection=conn,
       table="incident",
       query="active=true",
   )

   for attachment in loader.lazy_load():
       print(f"{attachment.metadata['file_name']} ({attachment.metadata['size_bytes']} bytes)")
       # attachment.page_content contains the file content or extracted text

v0.3 - Vector Store Streaming & Checkpointing
----------------------------------------------

**Direct vector store streaming**

Write documents directly to Pinecone, Weaviate, Chroma, or Qdrant
without holding everything in memory. Useful for loading millions of
records.

**Checkpoint and resume**

For large loads (100k+ records), save progress to disk so that a crash
at record 50k does not require starting from the beginning.

v1.0 - Custom Field Mapping
----------------------------

**User-defined table schemas**

Not every ServiceNow instance uses default field names. v1.0 will allow
you to define custom field mappings for any table, supporting heavily
customized instances.

Contributing
------------

We welcome contributions toward these roadmap items. See the
`contributing guide <https://github.com/ronidas39/snowloader/blob/main/README.md#contributing>`_
for details on how to get started.
