# Changelog

All notable changes to snowloader are documented here. This project follows [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-03-25

### Added

**Loaders:**
- `IncidentLoader` — IT incidents with structured text and journal support
- `KnowledgeBaseLoader` — KB articles with built-in HTML cleaning
- `CMDBLoader` — Configuration Items with concurrent relationship traversal
- `ChangeLoader` — Change requests with implementation window details
- `ProblemLoader` — Problems with root cause and known error handling
- `CatalogLoader` — Service catalog items

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
