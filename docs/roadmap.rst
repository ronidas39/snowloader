Roadmap
=======

snowloader is under active development. Here is what is planned for
upcoming releases.

v0.2 - Async & Attachments (Shipped 2026-04-28)
------------------------------------------------

Both features in v0.2 are now live. See the :doc:`async` and
:doc:`attachments` pages for details. Highlights:

- ``AsyncSnowConnection`` with concurrent paginated fetches
- Async variants of every loader and adapter
- ``AttachmentLoader`` and ``AsyncAttachmentLoader`` for the
  ``sys_attachment`` table with optional eager downloads and a size cap
- ``parse_labelled_int`` helper for fields like priority, urgency, impact

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
