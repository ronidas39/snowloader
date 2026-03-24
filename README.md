# snowloader

> Comprehensive ServiceNow data loader for AI/LLM pipelines — Incidents, CMDB, KB, Changes, Catalog & more.

**Works with LangChain & LlamaIndex out of the box.**

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

loader = IncidentLoader(conn, query="active=true^priority<=2")
docs = loader.load()

for doc in docs:
    print(doc.text[:100])
```

## License

MIT
