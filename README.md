<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/logo.png" alt="snowloader" width="150">
</p>

<h1 align="center">snowloader</h1>

<p align="center">
  <em>Production ServiceNow data loader for AI, RAG, and agent pipelines.</em>
</p>

<p align="center"><strong>Created by <a href="https://github.com/ronidas39">Roni Das</a></strong> · <a href="mailto:thetotaltechnology@gmail.com">thetotaltechnology@gmail.com</a></p>

<p align="center">
  <a href="https://pypi.org/project/snowloader/"><img src="https://img.shields.io/pypi/v/snowloader.svg?label=pypi&color=1a73e8" alt="PyPI version"></a>
  <a href="https://pypi.org/project/snowloader/"><img src="https://img.shields.io/pypi/pyversions/snowloader.svg?label=python&color=4fc3f7" alt="Python versions"></a>
  <a href="https://pypi.org/project/snowloader/"><img src="https://img.shields.io/pypi/dm/snowloader.svg?label=downloads&color=10b981" alt="Downloads"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
</p>
<p align="center">
  <a href="https://github.com/ronidas39/snowloader/actions/workflows/ci.yml"><img src="https://github.com/ronidas39/snowloader/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://snowloader.readthedocs.io"><img src="https://readthedocs.org/projects/snowloader/badge/?version=latest" alt="Documentation"></a>
  <a href="https://peps.python.org/pep-0561/"><img src="https://img.shields.io/badge/typing-strict-1a73e8.svg" alt="Typed"></a>
  <a href="https://github.com/ronidas39/snowloader"><img src="https://img.shields.io/badge/code%20style-ruff-1a73e8.svg" alt="Ruff"></a>
</p>
<p align="center">
  <a href="https://github.com/ronidas39/snowloader"><img src="https://img.shields.io/badge/langchain-supported-4fc3f7.svg" alt="LangChain supported"></a>
  <a href="https://github.com/ronidas39/snowloader"><img src="https://img.shields.io/badge/llamaindex-supported-4fc3f7.svg" alt="LlamaIndex supported"></a>
  <a href="https://github.com/ronidas39/snowloader"><img src="https://img.shields.io/badge/async-aiohttp-10b981.svg" alt="Async support"></a>
  <a href="https://github.com/ronidas39/snowloader"><img src="https://img.shields.io/badge/threaded-yes-10b981.svg" alt="Threaded paginator"></a>
</p>

<p align="center">
  <strong><a href="https://snowloader.readthedocs.io">Documentation</a></strong>
   ·
  <strong><a href="https://pypi.org/project/snowloader/">PyPI</a></strong>
   ·
  <strong><a href="https://github.com/ronidas39/snowloader">Source</a></strong>
   ·
  <strong><a href="#installation">Install</a></strong>
   ·
  <strong><a href="#api-cheatsheet">API cheatsheet</a></strong>
   ·
  <strong><a href="#roadmap">Roadmap</a></strong>
</p>

---

## TL;DR

```python
from snowloader import SnowConnection, IncidentLoader

with SnowConnection(instance_url="https://yourcompany.service-now.com",
                    username="api_user", password="api_pass") as conn:
    docs = IncidentLoader(connection=conn, query="active=true").load()
```

Three lines from a ServiceNow instance to a list of documents your vector store understands. Same loader objects work with LangChain, LlamaIndex, or anything else that accepts a list of dicts.

---

## Architecture

<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/architecture.png" alt="snowloader data flow" width="900">
</p>

snowloader sits between ServiceNow's Table API and whatever LLM stack you are building. The connection layer handles auth, pagination, retries, and rate limiting. The loaders normalize each table into a `SnowDocument`. The adapters translate that into LangChain `Document` or LlamaIndex `Document` types without copying business logic.

---

## Why snowloader?

Building RAG or agentic AI on top of ServiceNow data? Existing tools either cover a single table, ignore relationships, or lock you into one framework. snowloader covers the seven core tables, gives you sync + threaded + async paginators, and stays framework-agnostic at the core so you can plug it into LangChain, LlamaIndex, or your own pipeline.

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>Seven loaders</h3>
      Incidents, Knowledge Base, CMDB, Changes, Problems, Catalog, and Attachments. One consistent interface across all of them.
    </td>
    <td width="33%" valign="top">
      <h3>Three pagination paths</h3>
      Sequential <code>get_records</code>, threaded <code>concurrent_get_records</code>, async <code>aget_records</code>. Pick the one that fits your runtime.
    </td>
    <td width="33%" valign="top">
      <h3>Four auth modes</h3>
      Basic, OAuth Password, OAuth Client Credentials, Bearer Token. Switching is a constructor argument.
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>Delta sync</h3>
      <code>load_since(datetime)</code> on every loader. Only fetch what changed since your last run.
    </td>
    <td valign="top">
      <h3>CMDB graph walking</h3>
      Pull configuration items together with their parent / child / depends-on relationships from <code>cmdb_rel_ci</code>.
    </td>
    <td valign="top">
      <h3>Streaming everywhere</h3>
      Generators and async iterators throughout. The full table never lives in memory at once.
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>Built-in HTML cleaner</h3>
      KB articles arrive as plain text. No BeautifulSoup, no extra dependencies.
    </td>
    <td valign="top">
      <h3>Production-grade</h3>
      Retry with backoff, rate limiting, thread-safe sessions, proxy support, custom CA bundles.
    </td>
    <td valign="top">
      <h3>Strict typing</h3>
      PEP 561 marker, <code>mypy --strict</code> clean, full type hints on every public surface.
    </td>
  </tr>
</table>

---

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

**Requirements:** Python 3.10, 3.11, 3.12, or 3.13. A ServiceNow instance with REST Table API access.

---

## API cheatsheet

| Loader | ServiceNow table | Highlight |
|--------|-----------------|-----------|
| `IncidentLoader` | `incident` | Optional journal entries (work notes + comments) |
| `KnowledgeBaseLoader` | `kb_knowledge` | HTML auto-stripped, plain text out |
| `CMDBLoader` | `cmdb_ci_*` | Concurrent relationship graph traversal |
| `ChangeLoader` | `change_request` | Implementation window details |
| `ProblemLoader` | `problem` | Known error flag normalized to bool |
| `CatalogLoader` | `sc_cat_item` | Active / inactive normalized to bool |
| `AttachmentLoader` | `sys_attachment` | Optional eager download with size cap |

Every loader exposes the same interface:

```python
loader.load()                         # list[SnowDocument]
loader.lazy_load()                    # generator
loader.load_since(datetime_cutoff)    # list[SnowDocument]
loader.concurrent_load(max_workers)   # threaded
loader.concurrent_lazy_load(...)      # threaded generator
```

Async siblings (when installed with `[async]`) follow the same shape: `aload`, `alazy_load`, `aload_since`.

---

## Pick the right pagination path

<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/decision.png" alt="API decision tree" width="850">
</p>

Three concurrency models, three jobs:

<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/performance.png" alt="Relative throughput" width="850">
</p>

The threaded path uses a per-thread `requests.Session`, which keeps connection pools and TLS state isolated per worker and avoids the connection-reuse failures some ServiceNow front ends exhibit when many concurrent requests share one session.

---

## Code recipes

<details>
<summary><strong>Sequential extraction (the simplest path)</strong></summary>

```python
from snowloader import SnowConnection, IncidentLoader

with SnowConnection(
    instance_url="https://yourcompany.service-now.com",
    username="api_user",
    password="api_pass",
) as conn:
    loader = IncidentLoader(connection=conn, query="active=true^priority<=2")
    for doc in loader.lazy_load():
        process(doc)
```
</details>

<details>
<summary><strong>Threaded extraction (sync, fast)</strong></summary>

```python
from snowloader import SnowConnection, IncidentLoader

with SnowConnection(
    instance_url="https://yourcompany.service-now.com",
    username="api_user",
    password="api_pass",
    page_size=500,
) as conn:
    total = conn.get_count("incident", query="state=6^close_notesISNOTEMPTY")

    for record in conn.concurrent_get_records(
        table="incident",
        query="state=6^close_notesISNOTEMPTY",
        max_workers=16,
    ):
        process(record)

    loader = IncidentLoader(connection=conn, query="state=6^close_notesISNOTEMPTY")
    docs = loader.concurrent_load(max_workers=16)
```
</details>

<details>
<summary><strong>Async extraction (asyncio apps)</strong></summary>

```python
import asyncio
from snowloader import AsyncSnowConnection, AsyncIncidentLoader

async def main() -> None:
    async with AsyncSnowConnection(
        instance_url="https://yourcompany.service-now.com",
        username="api_user",
        password="api_pass",
        page_size=500,
        concurrency=16,
    ) as conn:
        loader = AsyncIncidentLoader(connection=conn, query="active=true")
        async for doc in loader.alazy_load():
            print(doc.page_content[:200])

asyncio.run(main())
```

Every sync loader has a matching `Async*` variant. The framework adapters expose async forms too (`AsyncServiceNow*Loader` for LangChain, `AsyncServiceNow*Reader` for LlamaIndex).
</details>

<details>
<summary><strong>LangChain adapter</strong></summary>

```python
from snowloader import SnowConnection
from snowloader.adapters.langchain import ServiceNowIncidentLoader

conn = SnowConnection(
    instance_url="https://yourcompany.service-now.com",
    username="api_user",
    password="api_pass",
)
loader = ServiceNowIncidentLoader(connection=conn, query="active=true")
docs = loader.load()  # list[langchain_core.documents.Document]

# Plug straight into any vector store
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

vectorstore = FAISS.from_documents(docs, OpenAIEmbeddings())
```
</details>

<details>
<summary><strong>LlamaIndex adapter</strong></summary>

```python
from snowloader.adapters.llamaindex import ServiceNowIncidentReader

reader = ServiceNowIncidentReader(connection=conn, query="active=true")
docs = reader.load_data()  # list[llama_index.core.schema.Document]

from llama_index.core import VectorStoreIndex
index = VectorStoreIndex.from_documents(docs)
```
</details>

<details>
<summary><strong>Delta sync</strong></summary>

```python
from datetime import datetime, timezone

loader = IncidentLoader(connection=conn)
docs = loader.load()                          # First run: everything
last_sync = datetime.now(timezone.utc)

updated = loader.load_since(last_sync)        # Subsequent runs: only changes
```
</details>

<details>
<summary><strong>CMDB relationship graph</strong></summary>

```python
from snowloader import CMDBLoader

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
</details>

<details>
<summary><strong>Journal entries (work notes + comments)</strong></summary>

```python
loader = IncidentLoader(connection=conn, query="active=true", include_journals=True)
for doc in loader.lazy_load():
    print(doc.page_content)
    # Incident: INC0000007
    # Summary: Need access to sales DB
    # ...
    # [work_notes] 2024-06-01 09:15:00 by alice
    # Restarted Exchange service, monitoring.
```

Also works with `ChangeLoader` and `ProblemLoader`.
</details>

<details>
<summary><strong>Attachments</strong></summary>

```python
from snowloader import AttachmentLoader

# Metadata only
loader = AttachmentLoader(connection=conn, query="table_name=kb_knowledge")
for doc in loader.lazy_load():
    print(doc.metadata["file_name"], doc.metadata["size_bytes"])

# Download a specific file by sys_id
loader.download_to("att_sys_id", "./out/diagram.png")

# Eager download with size cap (10 MB)
loader = AttachmentLoader(connection=conn, download=True, max_size_bytes=10 * 1024 * 1024)
for doc in loader.lazy_load():
    blob = doc.metadata.get("content_bytes")
```
</details>

<details>
<summary><strong>Authentication (4 modes)</strong></summary>

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
</details>

<details>
<summary><strong>Recipe: large-scale extraction with resume support</strong></summary>

A common pattern for AI knowledge bases is two parallel corpus pulls. Closed and resolved tickets become a recommendation corpus; active tickets become a duplicate-prevention corpus. Both need raw API output (with `sysparm_display_value=all`), JSONL streaming, resume on crash, and end-of-run validation against the API count.

```python
import json
from pathlib import Path
from snowloader import SnowConnection

QUERY = (
    "stateIN6,7"
    "^close_notesISNOTEMPTY"
    "^sys_updated_on>=javascript:gs.daysAgoStart(730)"
    "^ORDERBYsys_created_on"
)
FIELDS = ["sys_id", "number", "short_description", "close_notes",
          "state", "priority", "urgency", "impact", "category",
          "assignment_group", "caller_id", "assigned_to",
          "opened_at", "resolved_at", "sys_updated_on"]

output_path = Path("incidents_closed.jsonl")
state_path = Path("incidents_closed.state.json")
state = json.loads(state_path.read_text()) if state_path.exists() else {"completed": []}
completed_offsets = set(state["completed"])

with SnowConnection(
    instance_url="https://yourcompany.service-now.com",
    username="api_user",
    password="api_pass",
    page_size=1000,
    display_value="all",
    max_retries=5,
) as conn:
    mode = "a" if completed_offsets else "w"
    with output_path.open(mode, encoding="utf-8") as fh:
        for record in conn.concurrent_get_records(
            table="incident", query=QUERY, fields=FIELDS, max_workers=16
        ):
            sid = record["sys_id"].get("value") if isinstance(record["sys_id"], dict) else record["sys_id"]
            num = record["number"].get("value") if isinstance(record["number"], dict) else record["number"]
            if not sid or not num:
                continue
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    line_count = sum(1 for _ in output_path.open("r"))
    api_total = conn.get_count("incident", query=QUERY)
    print(f"file: {line_count}, api: {api_total}, drift: {line_count - api_total}")
```

For the full pattern with offset-level checkpointing (so a crash mid-run loses at most a few seconds of work), see the [concurrent documentation page](https://snowloader.readthedocs.io/en/latest/concurrent.html).
</details>

---

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `page_size` | `100` | Records per API call (1 - 10,000) |
| `timeout` | `60` | HTTP timeout in seconds |
| `max_retries` | `3` | Retry attempts for 429 / 500 / 502 / 503 / 504 |
| `retry_backoff` | `1.0` | Base delay between retries (doubles each attempt) |
| `request_delay` | `0.0` | Minimum seconds between requests (rate limiting) |
| `display_value` | `"true"` | `sysparm_display_value` setting (`true` / `false` / `all`) |
| `proxy` | `None` | HTTP / HTTPS proxy URL |
| `verify` | `True` | SSL verification (or path to a custom CA bundle) |

See the [full documentation](https://snowloader.readthedocs.io/en/latest/configuration.html) for every parameter.

---

## Roadmap

<table>
  <tr>
    <th>Version</th>
    <th>Feature</th>
    <th>Status</th>
  </tr>
  <tr>
    <td><strong>v0.1</strong></td>
    <td>Six sync loaders, LangChain + LlamaIndex adapters, 4 auth modes, delta sync, journal entries, HTML cleaning, CMDB graph traversal</td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>v0.2</strong></td>
    <td>Async support (<code>aiohttp</code>) and async variants of every loader and adapter</td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>v0.2</strong></td>
    <td>Attachment loader for <code>sys_attachment</code> with optional eager download and size cap</td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>v0.2</strong></td>
    <td>Threaded sync paginator (<code>concurrent_get_records</code>, <code>concurrent_load</code>) with per-thread sessions</td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>v0.2</strong></td>
    <td><code>parse_labelled_int</code> helper for fields like priority, urgency, impact</td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>v0.3</strong></td>
    <td>Direct vector store streaming (Pinecone, Weaviate, Chroma, Qdrant)</td>
    <td><img src="https://img.shields.io/badge/planned-f59e0b.svg" alt="Planned"></td>
  </tr>
  <tr>
    <td><strong>v0.3</strong></td>
    <td>Checkpoint and resume for very large loads</td>
    <td><img src="https://img.shields.io/badge/planned-f59e0b.svg" alt="Planned"></td>
  </tr>
  <tr>
    <td><strong>v1.0</strong></td>
    <td>Custom field mapping for heavily customized instances</td>
    <td><img src="https://img.shields.io/badge/planned-f59e0b.svg" alt="Planned"></td>
  </tr>
</table>

---

## Contributing

Contributions are welcome.

1. Fork the repository
2. Create a feature branch
3. Write tests first (the project uses `pytest` + `responses` for HTTP mocking)
4. Ensure the quality gate passes:
   ```bash
   ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/snowloader/ && pytest tests/ -x
   ```
5. Open a pull request

---

## Author

<table>
  <tr>
    <td valign="middle">
      <strong>Roni Das</strong><br>
      <a href="mailto:thetotaltechnology@gmail.com">thetotaltechnology@gmail.com</a><br>
      <a href="https://github.com/ronidas39">github.com/ronidas39</a>
    </td>
    <td valign="middle">
      Built snowloader because every ServiceNow + AI project I picked up started with the same boilerplate. The library is the version of that boilerplate I want every team to be able to start from.
    </td>
  </tr>
</table>

## License

MIT. See [LICENSE](LICENSE) for the full text.
