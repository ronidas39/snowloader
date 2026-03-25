# snowloader

[![PyPI version](https://img.shields.io/pypi/v/snowloader.svg)](https://pypi.org/project/snowloader/)
[![Python versions](https://img.shields.io/pypi/pyversions/snowloader.svg)](https://pypi.org/project/snowloader/)
[![CI](https://github.com/ronidas39/snowloader/actions/workflows/ci.yml/badge.svg)](https://github.com/ronidas39/snowloader/actions/workflows/ci.yml)
[![Documentation](https://readthedocs.org/projects/snowloader/badge/?version=latest)](https://snowloader.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Typed](https://img.shields.io/badge/typing-typed-blue.svg)](https://peps.python.org/pep-0561/)

> Comprehensive ServiceNow data loader for AI/LLM pipelines — Incidents, CMDB, KB, Changes, Problems, Catalog & more.

**Works with LangChain & LlamaIndex out of the box. Python 3.10–3.13.**

**[Documentation](https://snowloader.readthedocs.io)** | **[PyPI](https://pypi.org/project/snowloader/)** | **[GitHub](https://github.com/ronidas39/snowloader)**

---

## Why snowloader?

Building RAG or agentic AI on top of ServiceNow data? You need a reliable way to pull structured ITSM records into your vector store. Existing tools either cover a single table, ignore relationships, or lock you into one framework.

snowloader gives you:

- **6 loaders** covering the core ServiceNow tables (Incidents, Knowledge Base, CMDB, Changes, Problems, Service Catalog)
- **CMDB relationship traversal** — concurrent graph walking with dependency mapping
- **Delta sync** — only fetch records updated since your last sync
- **4 auth modes** — Basic, OAuth Password, OAuth Client Credentials, Bearer Token
- **Production-grade** — retry with backoff, rate limiting, thread safety, proxy support
- **Framework-agnostic core** with thin adapters for LangChain and LlamaIndex
- **Memory-efficient streaming** — generator-based pagination, never holds the full table in memory
- **Built-in HTML cleaning** — strips KB article HTML without extra dependencies
- **Fully typed** — PEP 561 compliant, mypy --strict clean

## Installation

```bash
# pip
pip install snowloader              # Core only
pip install snowloader[langchain]   # + LangChain adapter
pip install snowloader[llamaindex]  # + LlamaIndex adapter
pip install snowloader[all]         # Everything

# uv
uv add snowloader
uv add snowloader[all]
```

**Requirements:** Python 3.10+ and a ServiceNow instance with REST API access.

## Quick Start

```python
from snowloader import SnowConnection, IncidentLoader

conn = SnowConnection(
    instance_url="https://mycompany.service-now.com",
    username="admin",
    password="password",
)

loader = IncidentLoader(connection=conn, query="active=true^priority<=2")
for doc in loader.lazy_load():
    print(doc.page_content[:200])
```

## All 6 Loaders

Every loader shares the same interface: `load()` returns a list, `lazy_load()` yields one document at a time, `load_since(datetime)` fetches only updated records.

```python
from snowloader import (
    IncidentLoader,         # IT incidents
    KnowledgeBaseLoader,    # KB articles (HTML auto-cleaned)
    CMDBLoader,             # Configuration items + relationships
    ChangeLoader,           # Change requests
    ProblemLoader,          # Problem records
    CatalogLoader,          # Service catalog items
)
```

## LangChain Adapter

```python
from snowloader import SnowConnection
from snowloader.adapters.langchain import ServiceNowIncidentLoader

conn = SnowConnection(instance_url="...", username="...", password="...")
loader = ServiceNowIncidentLoader(connection=conn, query="active=true")
docs = loader.load()  # list[langchain_core.documents.Document]

# Use with any vector store
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

vectorstore = FAISS.from_documents(docs, OpenAIEmbeddings())
```

## LlamaIndex Adapter

```python
from snowloader.adapters.llamaindex import ServiceNowIncidentReader

reader = ServiceNowIncidentReader(connection=conn, query="active=true")
docs = reader.load_data()  # list[llama_index.core.schema.Document]

from llama_index.core import VectorStoreIndex
index = VectorStoreIndex.from_documents(docs)
```

## Delta Sync

```python
from datetime import datetime, timezone

loader = IncidentLoader(connection=conn)
docs = loader.load()                          # First run: everything
last_sync = datetime.now(timezone.utc)

updated = loader.load_since(last_sync)        # Next runs: only changes
```

## CMDB Relationship Traversal

```python
loader = CMDBLoader(
    connection=conn,
    ci_class="cmdb_ci_server",
    include_relationships=True,
)

for doc in loader.lazy_load():
    # -> db-prod-01 (Depends on::Used by)
    # <- load-balancer-01 (Depends on::Used by)
    print(doc.page_content)
```

## Authentication

```python
# Basic Auth (development)
conn = SnowConnection(instance_url="...", username="admin", password="pass")

# OAuth Client Credentials (recommended for production)
conn = SnowConnection(instance_url="...", client_id="...", client_secret="...")

# OAuth Password Grant
conn = SnowConnection(instance_url="...", client_id="...", client_secret="...",
                       username="...", password="...")

# Bearer Token (pre-obtained)
conn = SnowConnection(instance_url="...", token="eyJhbG...")
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `page_size` | `100` | Records per API call (1–10,000) |
| `timeout` | `60` | HTTP timeout in seconds |
| `max_retries` | `3` | Retry attempts for 429/502/503/504 |
| `retry_backoff` | `1.0` | Base delay between retries (doubles each attempt) |
| `request_delay` | `0.0` | Min seconds between requests (rate limiting) |
| `display_value` | `"true"` | `sysparm_display_value` setting |
| `proxy` | `None` | HTTP/HTTPS proxy URL |
| `verify` | `True` | SSL verification (path for custom CA bundle) |

See the [full documentation](https://snowloader.readthedocs.io/en/latest/configuration.html) for all parameters.

## Roadmap

| Version | Feature | Status |
|---------|---------|--------|
| **v0.2** | Async support (`aiohttp` + `async for`) — 10-50x faster | Coming soon |
| **v0.2** | Attachment loader (`sys_attachment` downloads) | Coming soon |
| **v0.3** | Direct vector store streaming (Pinecone, Weaviate, Chroma) | Planned |
| **v0.3** | Checkpoint and resume for large loads | Planned |
| **v1.0** | Custom field mapping for customized instances | Planned |

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Write tests first (we use pytest + responses for HTTP mocking)
4. Ensure the quality gate passes:
   ```bash
   ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/snowloader/ && pytest tests/ -x
   ```
5. Open a pull request

## License

MIT — see [LICENSE](LICENSE) for details.
