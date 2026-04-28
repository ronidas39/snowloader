Roadmap
=======

snowloader is under active development. Here is what is planned for
upcoming releases.

v0.2 - Async, Attachments, Threaded Sync (Shipped 2026-04-28)
--------------------------------------------------------------

The v0.2 series shipped three big features and a series of robustness
patches driven by real-world extractions. See :doc:`async`,
:doc:`attachments`, and :doc:`concurrent` for usage details.

**Headline features:**

- ``AsyncSnowConnection`` with concurrent paginated fetches over ``aiohttp``
- Async variants of every loader and adapter
- ``AttachmentLoader`` and ``AsyncAttachmentLoader`` for the
  ``sys_attachment`` table with optional eager downloads and a size cap
- ``parse_labelled_int`` helper for ServiceNow labelled integer fields
  like ``priority``, ``urgency``, and ``impact``
- ``SnowConnection.get_count`` and ``concurrent_get_records`` plus
  ``BaseSnowLoader.concurrent_load`` and ``concurrent_lazy_load`` for
  threaded sync extractions with per-thread ``requests.Session`` instances
  (matches the throughput of the async path, no ``aiohttp`` dependency)

**Robustness improvements (across 0.2.1 through 0.2.5):**

- HTTP 500 added to the default retryable status set on both sync and
  async paths (ServiceNow 500s are typically transient overload)
- ``AsyncSnowConnection`` now uses ``force_close=True`` on its
  ``aiohttp.TCPConnector``, so each request gets a fresh TCP connection
- Non-object JSON bodies (a stray ``null`` returned with HTTP 200) and
  truncated JSON responses are now treated as transient failures: the
  SDK retries up to ``max_retries`` and raises ``SnowConnectionError``
  if the issue persists, instead of silently dropping pages

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
