# Changelog

All notable changes to snowloader are documented here. This project follows [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-04-28

### Added

**Async API:**
- `AsyncSnowConnection` built on `aiohttp` with concurrent paginated fetches
- `AsyncBaseSnowLoader` plus async variants for every existing loader: `AsyncIncidentLoader`, `AsyncKnowledgeBaseLoader`, `AsyncCMDBLoader`, `AsyncChangeLoader`, `AsyncProblemLoader`, `AsyncCatalogLoader`
- `aget_records`, `aget_record`, `aget_count`, `aget_attachment` on the async connection
- `aload`, `alazy_load`, `aload_since` on every async loader
- New `[async]` install extra: `pip install snowloader[async]`

**Attachments:**
- `AttachmentLoader` for the `sys_attachment` table with optional eager downloads, size cap, and selective fetch via `download` / `download_to`
- `AsyncAttachmentLoader` for the same flow over the async connection
- `SnowConnection.get_attachment` and `AsyncSnowConnection.aget_attachment` for direct binary fetches

**Adapters:**
- `ServiceNowAttachmentLoader` (LangChain) and `ServiceNowAttachmentReader` (LlamaIndex)
- Async variants of every adapter: `AsyncServiceNow*Loader` for LangChain (`aload`, `alazy_load`, `aload_since`) and `AsyncServiceNow*Reader` for LlamaIndex (`aload_data`, `aload_data_since`)

**Utilities:**
- `parse_labelled_int` public helper for ServiceNow labelled integer fields like priority, urgency, and impact (returns the raw int from values like `"3 - Moderate"` or `{"display_value": "3 - Moderate", "value": "3"}`)

### Changed

- Concurrent pagination defaults to 16 workers and 500-record pages on the async connection
- `pyproject.toml` adds `aiohttp` as an optional dependency and `aioresponses` + `pytest-asyncio` to the dev extras
- pytest configured with `asyncio_mode = "auto"` so async tests run without per-test markers
- Documentation reorganized with new `Async Usage` and `Attachments` pages

### Tests

- 188 unit tests (up from 124), including 17 for the async connection, 8 for async loaders, 8 for attachments, and 31 for the new parsing helper
- All tests pass against the in-memory `aioresponses` and `responses` mocks

## [0.1.0] - 2026-03-25

### Added

**Loaders:**
- `IncidentLoader` - IT incidents with structured text and journal support
- `KnowledgeBaseLoader` - KB articles with built-in HTML cleaning
- `CMDBLoader` - Configuration Items with concurrent relationship traversal
- `ChangeLoader` - Change requests with implementation window details
- `ProblemLoader` - Problems with root cause and known error handling
- `CatalogLoader` - Service catalog items

**Framework Adapters:**
- LangChain adapter (6 classes implementing `BaseLoader`)
- LlamaIndex adapter (6 classes implementing `BaseReader`)

**Connection:**
- 4 authentication modes: Basic, OAuth Password Grant, OAuth Client Credentials, Bearer Token
- Automatic pagination with stable ordering (`ORDERBYsys_created_on`)
- Retry logic with exponential backoff for 429/502/503/504
- Rate limiting (configurable `request_delay`)
- Thread-safe HTTP via request lock
- Proxy and custom CA certificate support
- Context manager for session lifecycle
- Configurable timeout, page size, display value mode

**Core Features:**
- Delta sync via `load_since(datetime)`
- Memory-efficient streaming via generator-based `lazy_load()`
- Built-in HTML cleaner (zero external dependencies)
- Journal entry support (work notes and comments)
- `SnowDocument` as framework-agnostic intermediate format
- PEP 561 `py.typed` marker for type checker support

**Testing:**
- 124 unit tests with mocked HTTP
- 33 live integration tests against a real ServiceNow instance
- Full quality gate: ruff, mypy --strict, pytest

[0.1.0]: https://github.com/ronidas39/snowloader/releases/tag/v0.1.0
