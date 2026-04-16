# LlamaIndex Readers Integration: snowloader

ServiceNow data readers for LlamaIndex, powered by [snowloader](https://github.com/ronidas39/snowloader).

Covers six core ServiceNow tables - Incidents, Knowledge Base, CMDB, Changes, Problems, and Service Catalog - with production-grade features like retry logic, delta sync, CMDB relationship traversal, and HTML cleaning.

## Installation

```bash
pip install llama-index-readers-snowloader
```

## Usage

```python
from snowloader import SnowConnection
from llama_index.readers.snowloader import ServiceNowIncidentReader

conn = SnowConnection(
    instance_url="https://mycompany.service-now.com",
    username="admin",
    password="password",
)

# Load active incidents
reader = ServiceNowIncidentReader(connection=conn, query="active=true")
documents = reader.load_data()

# Build an index
from llama_index.core import VectorStoreIndex

index = VectorStoreIndex.from_documents(documents)
query_engine = index.as_query_engine()
response = query_engine.query("What incidents are related to email?")
```

## Available Readers

| Reader | ServiceNow Table | Description |
|--------|-----------------|-------------|
| `ServiceNowIncidentReader` | `incident` | IT incidents with optional work notes/comments |
| `ServiceNowKBReader` | `kb_knowledge` | Knowledge Base articles (HTML auto-cleaned) |
| `ServiceNowCMDBReader` | `cmdb_ci` | Configuration Items with relationship graph traversal |
| `ServiceNowChangeReader` | `change_request` | Change requests with implementation windows |
| `ServiceNowProblemReader` | `problem` | Problems with root cause and known error tracking |
| `ServiceNowCatalogReader` | `sc_cat_item` | Service catalog items |

## CMDB with Relationships

```python
from llama_index.readers.snowloader import ServiceNowCMDBReader

reader = ServiceNowCMDBReader(
    connection=conn,
    ci_class="cmdb_ci_server",
    include_relationships=True,
)

for doc in reader.load_data():
    print(doc.text)
    # -> db-prod-01 (Depends on::Used by)
    # <- load-balancer-01 (Depends on::Used by)
```

## Delta Sync

Only fetch records updated since your last sync:

```python
from datetime import datetime, timezone

reader = ServiceNowIncidentReader(connection=conn)
docs = reader.load_data()
last_sync = datetime.now(timezone.utc)

# Next run - only get changes
updated = reader.load_data_since(last_sync)
```

## Authentication

snowloader supports four auth modes:

```python
# Basic Auth
conn = SnowConnection(instance_url="...", username="...", password="...")

# OAuth Client Credentials (recommended for production)
conn = SnowConnection(instance_url="...", client_id="...", client_secret="...")

# OAuth Password Grant
conn = SnowConnection(instance_url="...", client_id="...", client_secret="...",
                       username="...", password="...")

# Bearer Token
conn = SnowConnection(instance_url="...", token="eyJhbG...")
```

## Author

Created and maintained by **[Roni Das](https://github.com/ronidas39)** - [thetotaltechnology@gmail.com](mailto:thetotaltechnology@gmail.com)

## Links

- [snowloader on PyPI](https://pypi.org/project/snowloader/)
- [snowloader on GitHub](https://github.com/ronidas39/snowloader)
- [Full Documentation](https://snowloader.readthedocs.io)
