Roadmap
=======

snowloader is under active development. Here is what has shipped and what
is planned.

v0.3 - Correctness (Shipped 2026-08-27)
----------------------------------------

Driven by a field report from a real graph build rather than by guesswork.
See :doc:`verification` and :doc:`references` for usage details.

**The data loss fix**

Every paginated request now ends its ORDERBY chain with ``sys_id``.
ServiceNow offset pagination is only safe over a unique sort key, and
``sys_created_on`` is not one. Measured on a developer instance, three
consecutive sweeps of ``cmdb_ci`` each returned 2,919 rows matching the
count the instance reported, but only 2,915 distinct: four records replaced
by four duplicates, the same four every run.

**Sweeps you can trust**

- ``verify=True`` on every read path, sync and async, connection and loader
- ``SweepReport`` and ``SweepIncompleteError`` carrying every count that
  went into the decision
- ``on_error="skip"`` so an unattended run finishes past a dead page and
  then says what it lost

**Reference fields**

- Both halves of every field in metadata: the label under its own name, the
  identifier under a ``_sys_id`` companion
- ``sys_id`` is a plain string in every display value mode
- Public field helpers: ``reference``, ``display_value``, ``raw_value``,
  ``is_sys_id``, ``expand_reference_keys``

**New surface**

- ``TableLoader`` for any table with no dedicated loader
- ``RelationshipLoader`` sweeping ``cmdb_rel_ci`` for the whole CI graph in
  one read
- ``aconcurrent_get_records``, ``order_by``, ``since_field``,
  ``expand_references``, ``include_raw``, ``keep_alive``
- measured concurrency and page size guidance for both paths, replacing
  the guesses that were there before

v0.2 - Async, Attachments, Threaded Sync (Shipped 2026-04-28)
--------------------------------------------------------------

The v0.2 series shipped three large features and a series of reliability
fixes driven by real extractions. See :doc:`async`,
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

**Reliability fixes (across 0.2.1 through 0.2.5):**

- HTTP 500 added to the default retryable status set on both sync and
  async paths (ServiceNow 500s are typically transient overload)
- ``AsyncSnowConnection`` now uses ``force_close=True`` on its
  ``aiohttp.TCPConnector``, so each request gets a fresh TCP connection
- Non-object JSON bodies (a stray ``null`` returned with HTTP 200) and
  truncated JSON responses are now treated as transient failures: the
  SDK retries up to ``max_retries`` and raises ``SnowConnectionError``
  if the issue persists, instead of silently dropping pages

v0.4 - Very Large Extractions
-----------------------------

**Keyset pagination**

Offset pagination gets slower the deeper it goes, because the instance
still has to walk past every skipped row. Paging on ``sys_id >
last_seen`` instead keeps the cost per page flat. The ordering fix in
0.3.0 is the prerequisite for it.

**Checkpoint and resume**

For large loads (100k+ records), save progress to disk so that a crash
at record 50k does not require starting from the beginning.

**Direct vector store streaming**

Write documents directly to Pinecone, Weaviate, Chroma, or Qdrant
without holding everything in memory.

Not planned: write support
--------------------------

A read-only guarantee is the reason somebody points this at production
without raising a change. A read library that starts writing has to grow
opinions about Data Policies, choice lists and business rules, or it becomes
a polite way to corrupt a CMDB. If it ever happens it will be a sibling
package sharing connection, auth and retry, so that "snowloader does not
write" stays true of the thing people install by default.

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
