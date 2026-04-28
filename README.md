<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/logo.png" alt="snowloader" width="150">
</p>

<h1 align="center">snowloader</h1>

<p align="center"><strong>Created by <a href="https://github.com/ronidas39">Roni Das</a></strong> · <a href="mailto:thetotaltechnology@gmail.com">thetotaltechnology@gmail.com</a></p>

[![PyPI version](https://img.shields.io/pypi/v/snowloader.svg)](https://pypi.org/project/snowloader/)
[![Downloads](https://img.shields.io/pypi/dm/snowloader.svg)](https://pypistats.org/packages/snowloader)
[![Python versions](https://img.shields.io/pypi/pyversions/snowloader.svg)](https://pypi.org/project/snowloader/)
[![CI](https://github.com/ronidas39/snowloader/actions/workflows/ci.yml/badge.svg)](https://github.com/ronidas39/snowloader/actions/workflows/ci.yml)
[![Documentation](https://readthedocs.org/projects/snowloader/badge/?version=latest)](https://snowloader.readthedocs.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Typed](https://img.shields.io/badge/typing-typed-blue.svg)](https://peps.python.org/pep-0561/)

> Comprehensive ServiceNow data loader for AI/LLM pipelines - Incidents, CMDB, KB, Changes, Problems, Catalog & more.

**Works with LangChain & LlamaIndex out of the box. Python 3.10-3.13.**

**[Documentation](https://snowloader.readthedocs.io)** | **[PyPI](https://pypi.org/project/snowloader/)** | **[GitHub](https://github.com/ronidas39/snowloader)**

---

## Why snowloader?

Building RAG or agentic AI on top of ServiceNow data? You need a reliable way to pull structured ITSM records into your vector store. Existing tools either cover a single table, ignore relationships, or lock you into one framework.

snowloader gives you:

- **7 loaders** covering core ServiceNow tables (Incidents, Knowledge Base, CMDB, Changes, Problems, Service Catalog, Attachments)
- **Async support** via `aiohttp` for concurrent paginated fetches
- **CMDB relationship traversal** - concurrent graph walking with dependency mapping
- **Delta sync** - only fetch records updated since your last sync
- **4 auth modes** - Basic, OAuth Password, OAuth Client Credentials, Bearer Token
- **Production-grade** - retry with backoff, rate limiting, thread safety, proxy support
- **Framework-agnostic core** with sync + async adapters for LangChain and LlamaIndex
- **Memory-efficient streaming** - generator-based pagination, never holds the full table in memory
- **Built-in HTML cleaning** - strips KB article HTML without extra dependencies
- **Fully typed** - PEP 561 compliant, mypy --strict clean

## Installation

```bash
# pip
pip install snowloader              # Core only
pip install snowloader[async]       # + AsyncSnowConnection (aiohttp)
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

## All 7 Loaders

Every loader shares the same interface: `load()` returns a list, `lazy_load()` yields one document at a time, `load_since(datetime)` fetches only updated records.

```python
from snowloader import (
    IncidentLoader,         # IT incidents
    KnowledgeBaseLoader,    # KB articles (HTML auto-cleaned)
    CMDBLoader,             # Configuration items + relationships
    ChangeLoader,           # Change requests
    ProblemLoader,          # Problem records
    CatalogLoader,          # Service catalog items
    AttachmentLoader,       # File attachments (sys_attachment)
)
```

## Concurrent Sync API

`SnowConnection.concurrent_get_records()` fetches pages in parallel using a `ThreadPoolExecutor`. Each worker thread holds its own `requests.Session`, which keeps connection pools and TLS state isolated. This avoids the connection-reuse failures some ServiceNow front ends exhibit when many concurrent requests share a single client session, and gives sync users the same throughput as async without the `aiohttp` dependency.

```python
from snowloader import SnowConnection, IncidentLoader

with SnowConnection(
    instance_url="https://mycompany.service-now.com",
    username="admin",
    password="password",
    page_size=500,
) as conn:
    # Get the total before deciding how to fetch
    total = conn.get_count("incident", query="state=6^close_notesISNOTEMPTY")

    # Threaded paginator yields records in completion order, not sys_created_on order
    for record in conn.concurrent_get_records(
        table="incident",
        query="state=6^close_notesISNOTEMPTY",
        max_workers=16,
    ):
        process(record)

    # Same thing through a loader
    loader = IncidentLoader(connection=conn, query="state=6^close_notesISNOTEMPTY")
    docs = loader.concurrent_load(max_workers=16)
```

Real-world result: 457,247 incidents from a production instance pulled in **20 minutes** at 376 records/second.

When to pick which path:
- `concurrent_get_records` / `concurrent_load`: sync code, no asyncio integration needed, want maximum throughput out of the box.
- `aget_records` / `aload`: existing asyncio app, want native `async for` integration with the rest of your event loop.

## Async API

Pull large tables faster with `AsyncSnowConnection`. Pages are fetched concurrently against a shared `aiohttp` session, which delivers a 10-50x speedup on production-sized extractions.

```python
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
        async for doc in loader.alazy_load():
            print(doc.page_content[:200])

asyncio.run(main())
```

Every sync loader has a matching `Async*` variant: `AsyncIncidentLoader`, `AsyncKnowledgeBaseLoader`, `AsyncCMDBLoader`, `AsyncChangeLoader`, `AsyncProblemLoader`, `AsyncCatalogLoader`, and `AsyncAttachmentLoader`. The framework adapters expose async variants too (`AsyncServiceNow*Loader` for LangChain, `AsyncServiceNow*Reader` for LlamaIndex).

## Attachments

The `AttachmentLoader` pulls records from the `sys_attachment` table. By default it returns metadata only (file name, content type, size, parent record). Pass `download=True` to fetch each file's bytes during iteration.

```python
from snowloader import SnowConnection, AttachmentLoader

conn = SnowConnection(instance_url="...", username="...", password="...")

# Metadata only
loader = AttachmentLoader(connection=conn, query="table_name=kb_knowledge")
for doc in loader.lazy_load():
    print(doc.metadata["file_name"], doc.metadata["size_bytes"])

# Download a specific file
loader.download_to("att_sys_id", "./out/diagram.png")

# Eager download with size cap
loader = AttachmentLoader(
    connection=conn,
    download=True,
    max_size_bytes=10 * 1024 * 1024,
)
for doc in loader.lazy_load():
    blob = doc.metadata.get("content_bytes")
```

## Journal Entries (Work Notes & Comments)

Include the full investigation history from `sys_journal_field`:

```python
loader = IncidentLoader(connection=conn, query="active=true", include_journals=True)
for doc in loader.lazy_load():
    print(doc.page_content)
    # Incident: INC0000007
    # Summary: Need access to sales DB
    # ...
    # [work_notes] 2024-06-01 09:15:00 by alice
    # Restarted Exchange service, monitoring.
    #
    # [comments] 2024-06-01 09:20:00 by alice
    # We are working on the issue.
```

Also works with `ChangeLoader` and `ProblemLoader`.

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
| `page_size` | `100` | Records per API call (1-10,000) |
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
| **v0.2** | Async support (`aiohttp` + `async for`) - 10-50x faster | Shipped |
| **v0.2** | Attachment loader (`sys_attachment` downloads) | Shipped |
| **v0.2** | Threaded sync paginator (`concurrent_get_records`, `concurrent_load`) | Shipped |
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

## Author

Created and maintained by **[Roni Das](https://github.com/ronidas39)** - [thetotaltechnology@gmail.com](mailto:thetotaltechnology@gmail.com)

## License

MIT - see [LICENSE](LICENSE) for details.
