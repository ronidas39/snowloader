# snowloader

[![PyPI version](https://img.shields.io/pypi/v/snowloader.svg)](https://pypi.org/project/snowloader/)
[![Python versions](https://img.shields.io/pypi/pyversions/snowloader.svg)](https://pypi.org/project/snowloader/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

> Comprehensive ServiceNow data loader for AI/LLM pipelines — Incidents, CMDB, KB, Changes, Problems, Catalog & more.

**Works with LangChain & LlamaIndex out of the box.**

---

## Why snowloader?

Building RAG or agentic AI on top of ServiceNow data? You need a reliable way to pull structured ITSM records into your vector store. Existing tools either cover a single table, ignore relationships, or lock you into one framework.

snowloader gives you:

- **6 loaders** covering the core ServiceNow tables (Incidents, Knowledge Base, CMDB, Changes, Problems, Service Catalog)
- **CMDB relationship traversal** — automatically maps the dependency graph between configuration items
- **Delta sync** — only fetch records updated since your last sync
- **Framework-agnostic core** with thin adapters for LangChain and LlamaIndex
- **Memory-efficient streaming** — generator-based pagination, never holds the full table in memory
- **Built-in HTML cleaning** — strips KB article HTML without extra dependencies
- **Journal support** — optionally includes work notes and comments

## Installation

```bash
pip install snowloader              # Core only
pip install snowloader[langchain]   # + LangChain adapter
pip install snowloader[llamaindex]  # + LlamaIndex adapter
pip install snowloader[all]         # Everything
```

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

## Loaders

All loaders share the same interface: `load()` returns a list, `lazy_load()` yields one document at a time, and `load_since(datetime)` fetches only updated records.

### IncidentLoader

```python
from snowloader import SnowConnection, IncidentLoader

conn = SnowConnection(instance_url="https://myco.service-now.com", username="u", password="p")
loader = IncidentLoader(connection=conn, query="active=true")
docs = loader.load()
```

### KnowledgeBaseLoader

Automatically strips HTML from article bodies.

```python
from snowloader import KnowledgeBaseLoader

loader = KnowledgeBaseLoader(connection=conn, query="workflow_state=published")
for doc in loader.lazy_load():
    print(doc.page_content[:300])
```

### CMDBLoader

Optionally traverses the relationship graph to show how CIs connect.

```python
from snowloader import CMDBLoader

loader = CMDBLoader(
    connection=conn,
    ci_class="cmdb_ci_server",
    include_relationships=True,
)
for doc in loader.lazy_load():
    print(doc.page_content)
```

### ChangeLoader

```python
from snowloader import ChangeLoader

loader = ChangeLoader(connection=conn, query="state=2")  # Scheduled changes
docs = loader.load()
```

### ProblemLoader

```python
from snowloader import ProblemLoader

loader = ProblemLoader(connection=conn, query="active=true")
docs = loader.load()
```

### CatalogLoader

```python
from snowloader import CatalogLoader

loader = CatalogLoader(connection=conn, query="active=true")
docs = loader.load()
```

## LangChain Adapter

```python
from snowloader import SnowConnection
from snowloader.adapters.langchain import ServiceNowIncidentLoader

conn = SnowConnection(
    instance_url="https://myco.service-now.com",
    username="admin",
    password="password",
)

loader = ServiceNowIncidentLoader(connection=conn, query="active=true")
docs = loader.load()  # Returns list[langchain_core.documents.Document]

# Use with any LangChain vector store
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

vectorstore = FAISS.from_documents(docs, OpenAIEmbeddings())
```

Available adapters: `ServiceNowIncidentLoader`, `ServiceNowKBLoader`, `ServiceNowCMDBLoader`, `ServiceNowChangeLoader`, `ServiceNowProblemLoader`, `ServiceNowCatalogLoader`

## LlamaIndex Adapter

```python
from snowloader import SnowConnection
from snowloader.adapters.llamaindex import ServiceNowIncidentReader

conn = SnowConnection(
    instance_url="https://myco.service-now.com",
    username="admin",
    password="password",
)

reader = ServiceNowIncidentReader(connection=conn, query="active=true")
docs = reader.load_data()  # Returns list[llama_index.core.schema.Document]

# Use with any LlamaIndex index
from llama_index.core import VectorStoreIndex

index = VectorStoreIndex.from_documents(docs)
query_engine = index.as_query_engine()
```

Available readers: `ServiceNowIncidentReader`, `ServiceNowKBReader`, `ServiceNowCMDBReader`, `ServiceNowChangeReader`, `ServiceNowProblemReader`, `ServiceNowCatalogReader`

## Delta Sync

Only fetch records that changed since your last sync:

```python
from datetime import datetime, timezone

loader = IncidentLoader(connection=conn)

# First run: load everything
docs = loader.load()
last_sync = datetime.now(timezone.utc)

# Subsequent runs: only get updates
updated_docs = loader.load_since(last_sync)
last_sync = datetime.now(timezone.utc)
```

## CMDB Relationship Traversal

The CMDB loader can map out how configuration items relate to each other — dependencies, containment, hosting, and more:

```python
loader = CMDBLoader(
    connection=conn,
    ci_class="cmdb_ci_service",
    include_relationships=True,
    query="operational_status=1",
)

for doc in loader.lazy_load():
    # Document text includes relationship arrows:
    #   --> Depends on: Database Server (cmdb_ci_server)
    #   <-- Used by: Email Service (cmdb_ci_service)
    print(doc.page_content)
```

## Configuration Reference

### SnowConnection

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `instance_url` | `str` | *required* | Full URL of your ServiceNow instance |
| `username` | `str` | `None` | ServiceNow username |
| `password` | `str` | `None` | ServiceNow password |
| `client_id` | `str` | `None` | OAuth client ID (enables OAuth mode) |
| `client_secret` | `str` | `None` | OAuth client secret |
| `page_size` | `int` | `100` | Records per API call (max 10,000) |

### Loader Common Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `connection` | `SnowConnection` | *required* | Connection instance |
| `query` | `str` | `None` | ServiceNow encoded query filter |
| `fields` | `list[str]` | `None` | Specific fields to fetch |
| `include_journals` | `bool` | `False` | Include work notes and comments |

### CMDBLoader Extra Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ci_class` | `str` | `"cmdb_ci"` | CMDB class table to query |
| `include_relationships` | `bool` | `False` | Traverse relationship graph |

## Comparison

| Feature | snowloader | langchain-servicenow | Generic REST loaders |
|---------|-----------|---------------------|---------------------|
| Tables supported | 6 (Incident, KB, CMDB, Change, Problem, Catalog) | 1-2 | Manual setup |
| CMDB relationships | Built-in traversal | No | No |
| Delta sync | Built-in | No | Manual |
| HTML cleaning | Built-in (zero deps) | No | No |
| Journal entries | Built-in | No | No |
| LangChain support | Adapter | Native | Varies |
| LlamaIndex support | Adapter | No | Varies |
| Streaming/pagination | Generator-based | Varies | Varies |

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Write tests first (we use pytest + responses for HTTP mocking)
4. Ensure the quality gate passes: `ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/snowloader/ && pytest tests/ -x`
5. Open a pull request

## License

MIT - see [LICENSE](LICENSE) for details.
