Attachments
===========

The :class:`~snowloader.AttachmentLoader` (and its async sibling
:class:`AsyncAttachmentLoader`) pulls records from the ServiceNow
``sys_attachment`` table. Each attachment row carries metadata about a
file: its name, content type, size, and the parent record it belongs to
(via ``table_name`` + ``table_sys_id``).

Two access modes
----------------

The loader supports two ways of working with files:

1. **Metadata only (default)**. Each :class:`SnowDocument` describes one
   attachment without fetching its bytes. Pull binary content explicitly
   for the attachments you actually need via :meth:`download` or
   :meth:`download_to`.
2. **Eager download**. Pass ``download=True`` and the loader fetches every
   file's bytes during iteration, storing them under
   ``metadata["content_bytes"]``. Use ``max_size_bytes`` to skip files
   above a given threshold.

Quick start
-----------

.. code-block:: python

   from snowloader import SnowConnection, AttachmentLoader

   conn = SnowConnection(
       instance_url="https://mycompany.service-now.com",
       username="admin",
       password="password",
   )

   # Pull metadata for every KB attachment
   loader = AttachmentLoader(
       connection=conn,
       query="table_name=kb_knowledge",
   )
   for doc in loader.lazy_load():
       print(doc.metadata["file_name"], doc.metadata["size_bytes"])

Download a specific file
------------------------

.. code-block:: python

   from pathlib import Path

   loader = AttachmentLoader(connection=conn, query="table_name=kb_knowledge")
   first = next(iter(loader.lazy_load()))
   loader.download_to(first.metadata["sys_id"], Path("./out") / first.metadata["file_name"])

Eager download with size cap
----------------------------

.. code-block:: python

   loader = AttachmentLoader(
       connection=conn,
       query="table_name=incident",
       download=True,
       max_size_bytes=10 * 1024 * 1024,  # skip files over 10 MB
   )
   for doc in loader.lazy_load():
       blob = doc.metadata.get("content_bytes")
       if blob is not None:
           process(doc.metadata["file_name"], blob)

Async usage
-----------

.. code-block:: python

   import asyncio
   from snowloader import AsyncSnowConnection, AsyncAttachmentLoader

   async def main() -> None:
       async with AsyncSnowConnection(
           instance_url="https://mycompany.service-now.com",
           username="admin",
           password="password",
       ) as conn:
           loader = AsyncAttachmentLoader(
               connection=conn,
               query="table_name=kb_knowledge",
               download=True,
           )
           docs = await loader.aload()

   asyncio.run(main())

Document layout
---------------

Each ``SnowDocument`` produced by the attachment loader has:

* ``page_content``: a short summary line including the file name, content
  type, size, and parent record
* ``metadata`` keys:

  - ``sys_id``: the attachment's own sys_id
  - ``file_name``, ``content_type``, ``size_bytes``
  - ``table_name``, ``table_sys_id``: pointer to the parent record
  - ``download_url``: full URL to the binary endpoint
  - ``content_bytes``: present only when ``download=True`` and the file
    was within ``max_size_bytes``

LangChain and LlamaIndex adapters
---------------------------------

Both framework adapters include attachment variants:

.. code-block:: python

   from snowloader.adapters.langchain import ServiceNowAttachmentLoader
   from snowloader.adapters.llamaindex import ServiceNowAttachmentReader

The async forms are ``AsyncServiceNowAttachmentLoader`` and
``AsyncServiceNowAttachmentReader``.
