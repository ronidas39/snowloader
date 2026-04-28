Changelog
=========

All notable changes to snowloader are documented here. This project
follows `Semantic Versioning <https://semver.org/>`_.

v0.2.0 (2026-04-28)
--------------------

**Async API:**

- ``AsyncSnowConnection`` built on ``aiohttp`` with concurrent paginated fetches
- ``AsyncBaseSnowLoader`` plus async variants for every existing loader
- ``aget_records``, ``aget_record``, ``aget_count``, ``aget_attachment`` on the async connection
- New ``[async]`` install extra: ``pip install snowloader[async]``

**Attachments:**

- ``AttachmentLoader`` for the ``sys_attachment`` table with optional eager downloads, size cap, and selective fetch
- ``AsyncAttachmentLoader`` for the same flow over the async connection
- ``SnowConnection.get_attachment`` and ``AsyncSnowConnection.aget_attachment`` for direct binary fetches

**Adapters:**

- ``ServiceNowAttachmentLoader`` (LangChain) and ``ServiceNowAttachmentReader`` (LlamaIndex)
- Async variants of every adapter: ``AsyncServiceNow*Loader`` and ``AsyncServiceNow*Reader``

**Utilities:**

- ``parse_labelled_int`` public helper for ServiceNow labelled integer fields like priority, urgency, and impact

**Tests:**

- 188 unit tests, up from 124

v0.1.0 (2026-03-25)
--------------------

Initial release.

**Loaders:**

- ``IncidentLoader`` - IT incidents with structured text and journal support
- ``KnowledgeBaseLoader`` - KB articles with built-in HTML cleaning
- ``CMDBLoader`` - Configuration Items with concurrent relationship traversal
- ``ChangeLoader`` - Change requests with implementation window details
- ``ProblemLoader`` - Problems with root cause and known error handling
- ``CatalogLoader`` - Service catalog items

**Framework Adapters:**

- LangChain adapter (6 classes implementing ``BaseLoader``)
- LlamaIndex adapter (6 classes implementing ``BaseReader``)

**Connection:**

- 4 authentication modes: Basic, OAuth Password Grant, OAuth Client Credentials, Bearer Token
- Automatic pagination with stable ordering
- Retry logic with exponential backoff for 429/502/503/504
- Rate limiting (configurable ``request_delay``)
- Thread-safe HTTP via request lock
- Proxy and custom CA certificate support
- Context manager for session lifecycle
- Configurable timeout, page size, display value mode

**Core Features:**

- Delta sync via ``load_since(datetime)``
- Memory-efficient streaming via generator-based ``lazy_load()``
- Built-in HTML cleaner (zero external dependencies)
- Journal entry support (work notes and comments)
- ``SnowDocument`` as framework-agnostic intermediate format
- PEP 561 ``py.typed`` marker for type checker support

**Testing:**

- 124 unit tests with mocked HTTP
- 33 live integration tests against a real ServiceNow instance
- Full quality gate: ruff, mypy --strict, pytest
