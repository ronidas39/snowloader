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

## In three lines

```python
from snowloader import SnowConnection, IncidentLoader

with SnowConnection(instance_url="https://yourcompany.service-now.com",
                    username="api_user", password="api_pass") as conn:
    docs = IncidentLoader(connection=conn, query="active=true").load()
```

Three lines from a ServiceNow instance to a list of documents your vector store understands. The same loader objects work with LangChain, LlamaIndex, or anything else that accepts a list of dicts.

---

## What 0.3.0 fixes

<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/pagination.png" alt="Offset pagination over a non-unique sort column returns some rows twice and skips others" width="960">
</p>

ServiceNow does not guarantee a stable row order inside a group of rows that tie on the sort column. Every release before 0.3.0 paged over `sys_created_on`, which is not unique, so a page boundary landing inside a tied group returned some rows twice and skipped others.

The returned count still matched, so nothing reported a problem. The loss was identical on every run, so re-running never revealed it. Measured on a developer instance where `cmdb_ci` holds 2,919 rows across only 818 distinct timestamps, three consecutive sweeps each returned 2,919 rows and only 2,915 of them were distinct.

Every ORDERBY chain now ends in `sys_id`, and you can ask a sweep to prove it was complete:

```python
records = list(conn.get_records("cmdb_ci", verify=True))   # raises if anything is missing
```

Details in [the upgrade notes](#upgrading-to-030).

---

## Upgrading to 0.3.0

**0.3.0 fixes a data loss bug. If you are on 0.2.x, upgrade.**

ServiceNow offset pagination is only safe over a unique sort key. The API does not guarantee a stable order inside a group of rows that tie on the sort column, so a page boundary landing inside a tied group returns some rows twice and skips others. Every release before 0.3.0 sorted on `sys_created_on`, which is not unique.

Measured on a developer instance, `cmdb_ci` holds 2,919 rows across only 818 distinct `sys_created_on` values, worst tie 31 rows. Three consecutive sweeps:

```text
run 1: returned=2919 distinct=2915 lost=4 duplicated=4 count_matches_api=True
run 2: returned=2919 distinct=2915 lost=4 duplicated=4 count_matches_api=True
run 3: returned=2919 distinct=2915 lost=4 duplicated=4 count_matches_api=True
```

The count reconciles, so nothing reports a problem. The loss is deterministic, so re-running never surfaces it and diffing two runs shows nothing. On a 30,000 row CMDB that rate is roughly 40 missing CIs.

0.3.0 ends every ORDERBY chain with `sys_id`. Nothing in your code changes. The same table now returns all 2,919 distinct rows on both the sequential and the threaded path.

You can also ask a sweep to prove it was complete:

```python
records = list(conn.get_records("cmdb_ci", verify=True))   # raises if anything is missing
```

Two breaking changes come with it, both in loader metadata. The one to check before you upgrade a retrieval pipeline: metadata now carries every field on the record plus an identifier beside each reference, which on a wide table is roughly three times the previous size. If you write the whole metadata dict into a vector store with a per-vector size limit, pass `expand_references=False` to keep the 0.2.x shape. Full detail in [the changelog](https://github.com/ronidas39/snowloader/blob/main/CHANGELOG.md) and [the docs](https://snowloader.readthedocs.io/en/latest/verification.html).

---

## Architecture

<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/architecture.png" alt="snowloader data flow" width="900">
</p>

snowloader sits between ServiceNow's Table API and whatever LLM stack you are building. The connection layer handles auth, pagination, retries, and rate limiting. The loaders normalize each table into a `SnowDocument`. The adapters translate that into LangChain `Document` or LlamaIndex `Document` types without copying business logic.

---

## Why snowloader?

Building RAG or agentic AI on top of ServiceNow data. snowloader covers the core tables plus a generic loader for the rest, gives you sync, threaded and async paginators, and keeps the core free of any framework so you can plug it into LangChain, LlamaIndex, or your own pipeline.

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>Sweeps that do not lose rows</h3>
      Every paginated read sorts on a unique key, so an offset page boundary landing inside a tied timestamp cannot silently drop records.
    </td>
    <td width="33%" valign="top">
      <h3>Sweeps that prove it</h3>
      <code>verify=True</code> counts the table first and raises rather than handing back an incomplete extract that looks fine.
    </td>
    <td width="33%" valign="top">
      <h3>Nine loaders</h3>
      Incidents, Knowledge Base, CMDB, Changes, Problems, Catalog, Attachments, CI relationships, and a generic <code>TableLoader</code> for anything else.
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>Three pagination paths</h3>
      Sequential <code>get_records</code>, threaded <code>concurrent_get_records</code>, async <code>aget_records</code>. Pick the one that fits your runtime.
    </td>
    <td valign="top">
      <h3>Four auth modes</h3>
      Basic, OAuth Password, OAuth Client Credentials, Bearer Token. Switching is a constructor argument.
    </td>
    <td valign="top">
      <h3>Both halves of every field</h3>
      The readable label and the sys_id you join on, side by side in metadata. No helper to write yourself.
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>Delta sync</h3>
      <code>load_since(datetime)</code> on every loader. Only fetch what changed since your last run.
    </td>
    <td valign="top">
      <h3>CMDB graph walking</h3>
      Sweep <code>cmdb_rel_ci</code> once for every edge, or traverse per CI when you only need a few.
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
      <h3>Tested against a live instance</h3>
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
| `RelationshipLoader` | `cmdb_rel_ci` | One document per edge, both endpoints as sys_ids |
| `TableLoader` | anything | Generic loader for tables with no dedicated one |

Every loader exposes the same interface:

```python
loader.load()                         # list[SnowDocument]
loader.lazy_load()                    # generator
loader.load_since(datetime_cutoff)    # list[SnowDocument]
loader.concurrent_load(max_workers)   # threaded
loader.concurrent_lazy_load(...)      # threaded generator

loader.load(verify=True)              # raises if the sweep lost records
loader.load(on_error="skip")          # finish past a dead page instead of aborting
```

Async siblings (when installed with `[async]`) follow the same shape: `aload`, `alazy_load`, `aload_since`.

Document metadata carries both halves of every reference field, so a record can be joined to what it points at:

```python
doc.metadata["assignment_group"]         # 'Service Desk'
doc.metadata["assignment_group_sys_id"]  # 'd625dcce...'
doc.metadata["priority"]                 # '5 - Planning'
doc.metadata["priority_value"]           # '5'
```

---

## Pick the right pagination path

<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/decision.png" alt="API decision tree" width="850">
</p>

Three concurrency models, three jobs. The numbers below came out of a run against a developer instance, not an estimate. Reproduce them on your own instance with `scripts/benchmark_v030.py`.

<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/performance.png" alt="Threaded sweep timings by worker count" width="900">
</p>

Two things worth taking from that chart. Throughput peaks at 16 workers, which is why 16 is the default, and 32 workers came out slower than 16 rather than marginally faster. Page size in the low hundreds measured best on this path; raising it does not buy speed here, because throughput is bounded by how many pages are in flight rather than by request count.

The async path pulls the other way and wants larger pages, which is why its default is 500. Do not carry a page size from one path to the other.

The threaded path uses a per-thread `requests.Session`, which keeps connection pools and TLS state isolated per worker and avoids the connection-reuse failures some ServiceNow front ends exhibit when many concurrent requests share one session.

---

## Code recipes

<details>
<summary><strong>A sweep that proves it was complete</strong></summary>

```python
from snowloader import SnowConnection, SweepIncompleteError

with SnowConnection(
    instance_url="https://yourcompany.service-now.com",
    username="api_user",
    password="api_pass",
    page_size=100,          # smaller pages parallelise better
    order_by="sys_id",      # unique key, and the cheapest sort
) as conn:
    try:
        records = list(
            conn.concurrent_get_records(
                "cmdb_ci",
                max_workers=16,
                verify=True,        # free here: the count is already fetched
                on_error="skip",    # finish the run, then complain
            )
        )
    except SweepIncompleteError as exc:
        alert(f"CMDB extract incomplete: {exc.report}")
        # table=cmdb_ci expected=30000 returned=29900 distinct=29900
        # missing=100 duplicated=0 failed_pages=1
        raise
```

`verify=True` counts the table before reading it and raises if the sweep did not return that many distinct records. `on_error="skip"` logs a page that could not be fetched after its retries were exhausted, leaves a gap and lets the rest finish, so an unattended run completes and then tells you what it lost instead of dying on page nine hundred.
</details>

<details>
<summary><strong>CMDB as a graph, in two sweeps</strong></summary>

```python
from snowloader import SnowConnection, TableLoader, RelationshipLoader

with SnowConnection(
    instance_url="https://yourcompany.service-now.com",
    username="api_user",
    password="api_pass",
    display_value="all",
    order_by="sys_id",
) as conn:
    for doc in TableLoader(conn, table="cmdb_ci").lazy_load(verify=True):
        graph.add_node(
            doc.metadata["sys_id"],
            name=doc.metadata.get("name"),
            # the value half, so this is the table name the CI lives in,
            # not the pretty label
            ci_class=doc.metadata.get("sys_class_name_value"),
        )

    for doc in RelationshipLoader(conn).lazy_load(verify=True):
        graph.add_edge(
            doc.metadata["parent_sys_id"],
            doc.metadata["child_sys_id"],
            type=doc.metadata["type"],
        )
```

Both endpoints and the relationship type come back as identifiers, so the edges load with no resolution step. `CMDBLoader(include_relationships=True)` is still there for walking a handful of CIs, but it costs two extra requests per CI. Measured on a developer instance that came to 2.4 seconds per CI, which projects to about 34 hours for a 50,000 CI estate. Sweeping the whole relationship table on the same instance took 7 seconds.
</details>

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
    page_size=100,
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
    page_size=100,
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
| `order_by` | `"sys_created_on"` | Sort column, or list of columns. `sys_id` appended as a unique tiebreak. `None` disables ordering |
| `since_field` | `"sys_updated_on"` | Column a delta sync compares its cutoff against |
| `proxy` | `None` | HTTP / HTTPS proxy URL |
| `verify` | `True` | SSL verification (or path to a custom CA bundle) |

`AsyncSnowConnection` takes the same arguments plus `concurrency` (default 16) and `keep_alive` (default `False`, which trades a TLS handshake per request for immunity to the empty-body responses some ServiceNow front ends return on reused connections under load). Measure both against your own instance before turning it on.

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
    <td>Deterministic pagination: every ORDERBY chain ends in <code>sys_id</code>, so offset paging cannot lose rows to a tied sort column</td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>v0.3</strong></td>
    <td>Sweep verification (<code>verify=True</code>, <code>SweepReport</code>, <code>SweepIncompleteError</code>) and a partial failure policy (<code>on_error="skip"</code>)</td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>v0.3</strong></td>
    <td>Reference fields as both halves everywhere, plus public field helpers (<code>reference</code>, <code>raw_value</code>, <code>expand_reference_keys</code>)</td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>v0.3</strong></td>
    <td>Generic <code>TableLoader</code>, <code>RelationshipLoader</code>, <code>aconcurrent_get_records</code>, configurable <code>order_by</code> and <code>since_field</code></td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>v0.4</strong></td>
    <td>Keyset pagination and checkpoint / resume for very large loads</td>
    <td><img src="https://img.shields.io/badge/planned-f59e0b.svg" alt="Planned"></td>
  </tr>
  <tr>
    <td><strong>v0.4</strong></td>
    <td>Direct vector store streaming (Pinecone, Weaviate, Chroma, Qdrant)</td>
    <td><img src="https://img.shields.io/badge/planned-f59e0b.svg" alt="Planned"></td>
  </tr>
  <tr>
    <td><strong>v1.0</strong></td>
    <td>Custom field mapping for heavily customized instances</td>
    <td><img src="https://img.shields.io/badge/planned-f59e0b.svg" alt="Planned"></td>
  </tr>
</table>

Write support stays out of scope. A read-only guarantee is the reason somebody points this at production without raising a change, and a read library that starts writing has to grow opinions about Data Policies, choice lists and business rules or it becomes a polite way to corrupt a CMDB. If it ever happens it will be a sibling package sharing connection, auth and retry.

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
