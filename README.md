<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/logo.png" alt="snowloader" width="140">
</p>

<h1 align="center">snowloader</h1>

<p align="center">
  <b>Get ServiceNow data into your AI pipeline without quietly losing rows.</b>
</p>

<p align="center">
  Incidents, Knowledge Base, CMDB, Changes, Problems, Catalog and attachments,<br>
  into LangChain, LlamaIndex, or your own code. Every sweep sorts on a unique key,<br>
  so offset pagination cannot drop records, and it can prove it returned everything.
</p>

<p align="center">
  <a href="https://pypi.org/project/snowloader/"><img src="https://img.shields.io/pypi/v/snowloader.svg?label=pypi&color=1a73e8" alt="PyPI version"></a>
  <a href="https://pypi.org/project/snowloader/"><img src="https://img.shields.io/pypi/pyversions/snowloader.svg?label=python&color=4fc3f7" alt="Python versions"></a>
  <a href="https://github.com/ronidas39/snowloader/actions/workflows/ci.yml"><img src="https://github.com/ronidas39/snowloader/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://snowloader.readthedocs.io"><img src="https://img.shields.io/badge/tests-420%20passing-10b981.svg" alt="Tests"></a>
  <a href="https://peps.python.org/pep-0561/"><img src="https://img.shields.io/badge/typing-strict-1a73e8.svg" alt="Typed"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
</p>

<p align="center">
  <a href="https://snowloader.readthedocs.io"><b>Documentation</b></a>
  &nbsp;·&nbsp;
  <a href="https://pypi.org/project/snowloader/"><b>PyPI</b></a>
  &nbsp;·&nbsp;
  <a href="#installation"><b>Install</b></a>
  &nbsp;·&nbsp;
  <a href="#upgrading-to-030"><b>Upgrading</b></a>
  &nbsp;·&nbsp;
  <a href="#api-cheatsheet"><b>API</b></a>
  &nbsp;·&nbsp;
  <a href="#roadmap"><b>Roadmap</b></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/pagination.png" alt="Offset pagination over a non-unique sort column returns some rows twice and skips others" width="960">
</p>

<p align="center">
  <i>Every release before 0.3.0 paged over a column that is not unique. The count still reconciled, so nothing reported it.</i>
</p>

<div align="center">
<table>
  <tr>
    <td align="center"><b>9</b><br>loaders, each with<br>an async variant</td>
    <td align="center"><b>3</b><br>pagination paths:<br>sequential, threaded, async</td>
    <td align="center"><b>4</b><br>authentication<br>modes</td>
    <td align="center"><b>420</b><br>unit tests, plus 21<br>against a live instance</td>
  </tr>
</table>
</div>

---

## Two ways in

**From a shell, one command.** Resumable, and it checks its own work:

```bash
pip install snowloader

export SNOW_INSTANCE=https://yourcompany.service-now.com
export SNOW_USER=api_user
export SNOW_PASS=...

snowloader extract incident --out incidents.jsonl \
    --query "stateIN6,7^close_notesISNOTEMPTY" \
    --fields sys_id,number,close_notes --display-value all --resume
```

Run it, kill it, run it again and it continues. It exits non-zero if the sweep did not return every record, so an unattended job finds out.

**From Python, three lines.** The same loader objects work with LangChain, LlamaIndex, or anything else that takes a list of dicts:

```python
from snowloader import SnowConnection, IncidentLoader

with SnowConnection(instance_url="https://yourcompany.service-now.com",
                    username="api_user", password="api_pass") as conn:
    docs = IncidentLoader(connection=conn, query="active=true").load(verify=True)
```

---

## The problem it solves

ServiceNow does not guarantee a stable row order inside a group of rows that tie on the sort column. Every release before 0.3.0 paged over `sys_created_on`, which is not unique, so a page boundary landing inside a tied group returned some rows twice and skipped others.

The returned count still matched, so nothing reported a problem. The loss was identical on every run, so re-running never revealed it. Measured on a developer instance where `cmdb_ci` holds 2,919 rows across only 818 distinct timestamps, three consecutive sweeps each returned 2,919 rows and only 2,915 of them were distinct.

Every ORDERBY chain ends in `sys_id`, so that boundary cannot fall inside a tie, and you can ask a sweep to prove it was complete:

```python
records = list(conn.get_records("cmdb_ci", verify=True))   # raises if anything is missing
```

The second thing it fixes is that a document could not be joined to anything. The loaders returned labels and threw the identifiers away.

<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/references.png" alt="Incident metadata before and after 0.3.0" width="960">
</p>

A long sweep can also be interrupted and continued. Ordering, verification and resume are the three things that were being assembled by hand and getting quietly wrong, so 0.5.0 made them the defaults of a command:

```bash
snowloader extract cmdb_ci --out cmdb.jsonl --resume --workers 16
```

Details in [the upgrade notes](#upgrading-from-02x).

---

## Upgrading from 0.2.x

**0.3.0 fixed a data loss bug. If you are still on 0.2.x, upgrade.**

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
      <h3>Runs from a shell</h3>
      <code>snowloader extract</code> and <code>snowloader count</code>. The careful choices are the defaults, and an incomplete sweep exits non-zero.
    </td>
  </tr>
  <tr>
    <td width="33%" valign="top">
      <h3>Resume where it stopped</h3>
      A checkpoint records how far a run reached, so killing a half-million-row sweep costs you the current page rather than the whole job.
    </td>
    <td width="33%" valign="top">
      <h3>Four pagination paths</h3>
      Sequential <code>get_records</code>, threaded <code>concurrent_get_records</code>, async <code>aget_records</code>, and <code>keyset=True</code> for a cursor that survives a restart.
    </td>
    <td width="33%" valign="top">
      <h3>Nine loaders</h3>
      Incidents, Knowledge Base, CMDB, Changes, Problems, Catalog, Attachments, CI relationships, and a generic <code>TableLoader</code> for anything else.
    </td>
  </tr>
  <tr>
    <td width="33%" valign="top">
      <h3>Four auth modes</h3>
      Basic, OAuth Password, OAuth Client Credentials, Bearer Token. Switching is a constructor argument.
    </td>
    <td width="33%" valign="top">
      <h3>Both halves of every field</h3>
      The readable label and the sys_id you join on, side by side in metadata. No helper to write yourself.
    </td>
    <td width="33%" valign="top">
      <h3>Delta sync</h3>
      <code>load_since(datetime)</code> on every loader. Only fetch what changed since your last run.
    </td>
  </tr>
  <tr>
    <td width="33%" valign="top">
      <h3>CMDB graph walking</h3>
      Sweep <code>cmdb_rel_ci</code> once for every edge, or traverse per CI when you only need a few.
    </td>
    <td width="33%" valign="top">
      <h3>Streaming everywhere</h3>
      Generators and async iterators throughout. The full table never lives in memory at once.
    </td>
    <td width="33%" valign="top">
      <h3>Carries on past a bad page</h3>
      <code>on_error="skip"</code> finishes the sweep when one page will not fetch, and tells you at the end exactly which records are missing.
    </td>
  </tr>
  <tr>
    <td width="33%" valign="top">
      <h3>Built-in HTML cleaner</h3>
      KB articles arrive as plain text. No BeautifulSoup, no extra dependencies.
    </td>
    <td width="33%" valign="top">
      <h3>Tested against a live instance</h3>
      Retry with backoff, rate limiting, thread-safe sessions, proxy support, custom CA bundles.
    </td>
    <td width="33%" valign="top">
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
loader.load(keyset=True)              # cursor paging, no offsets
loader.load(limit=5)                  # just enough to look at, one request
loader.load(keyset=True, checkpoint=FileCheckpoint("state.json"))   # resumable
```

On the connection, a long sweep can be made resumable:

```python
conn.get_records("cmdb_ci", keyset=True, checkpoint=FileCheckpoint("sweep.json"))
conn.concurrent_get_records("incident", max_workers=16, checkpoint=FileCheckpoint("inc.json"))
```

And the same work from a shell:

| Command | Does |
|---|---|
| `snowloader count <table>` | Prints how many records match, and stops |
| `snowloader extract <table> --out f.jsonl` | Sweeps the table to JSONL, verifying as it goes |
| `... --resume` | Continues an interrupted run, and records progress so this one can be continued |
| `... --workers 16` | Fetches pages in parallel instead of sequentially |
| `... --limit N` | Stop after N records. For sampling a table, not extracting it |
| `... --display-value all` | Keeps both halves of every field in the raw output |
| `... --skip-failed-pages` | Carries on past a page that will not fetch, and reports the gap |

Credentials come from `SNOW_INSTANCE`, `SNOW_USER` and `SNOW_PASS` when the matching option is not given, so a password need not reach a shell history or a process list. Exit status is 0 when the sweep finished and verified, 1 when it did not return every record, 2 on a usage or credential problem, and 130 when interrupted.

Async siblings (when installed with `[async]`) follow the same shape: `aload`, `alazy_load`, `aload_since`. Every loader has one, and so does every LangChain and LlamaIndex adapter.

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

Three concurrency models, three jobs, plus a cursor mode that cuts across all of them. The numbers below came out of a run against a developer instance, not an estimate. Reproduce them on your own instance with `scripts/benchmark_v030.py`.

<p align="center">
  <img src="https://raw.githubusercontent.com/ronidas39/snowloader/main/docs/_static/performance.png" alt="Threaded sweep timings by worker count" width="900">
</p>

Two things worth taking from that chart. Throughput peaks at 16 workers, which is why 16 is the default, and 32 workers came out slower than 16 rather than marginally faster. Page size in the low hundreds measured best on this path; raising it does not buy speed here, because throughput is bounded by how many pages are in flight rather than by request count.

The async path pulls the other way and wants larger pages, which is why its default is 500. Do not carry a page size from one path to the other.

Separately from concurrency, `keyset=True` pages on a `sys_id` cursor rather than an offset. It is what makes a sequential run resumable, and it is immune to the tied-sort problem by construction rather than by convention. It is not a speed feature: on a 2,919 row table, an offset of 2,800 was no slower than an offset of 0, so the usual deep-offset argument did not reproduce at that scale. Measure your own table before choosing it for throughput.

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

A common pattern for AI knowledge bases is two parallel corpus pulls. Closed and resolved tickets become a recommendation corpus, active tickets become a duplicate-prevention corpus. Both need raw API output (`sysparm_display_value=all`), JSONL streaming, resume on crash, and a completeness check at the end.

Both are one command each:

```bash
snowloader extract incident --out incidents_closed.jsonl --resume \
    --query "stateIN6,7^close_notesISNOTEMPTY^sys_updated_on>=javascript:gs.daysAgoStart(730)" \
    --fields sys_id,number,short_description,close_notes,state,priority,category,opened_at,resolved_at \
    --display-value all --workers 16

snowloader extract incident --out incidents_active.jsonl --resume \
    --query "active=true" --display-value all --workers 16
```

Ordering, resume and verification are handled. Either command exits non-zero if its sweep did not return every record, so a shell script can stop on it.

From Python, when the records go somewhere other than a file:

```python
import json
from snowloader import FileCheckpoint, SnowConnection, SweepIncompleteError

QUERY = "stateIN6,7^close_notesISNOTEMPTY"
checkpoint = FileCheckpoint("incidents_closed.state.json")

with SnowConnection(
    instance_url="https://yourcompany.service-now.com",
    username="api_user",
    password="api_pass",
    page_size=100,
    display_value="all",
) as conn:
    try:
        with open("incidents_closed.jsonl", "a", encoding="utf-8") as fh:
            for record in conn.concurrent_get_records(
                "incident", query=QUERY, max_workers=16,
                checkpoint=checkpoint, verify=True,
            ):
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except SweepIncompleteError as exc:
        alert(f"incident extract incomplete: {exc.report}")
        raise
```

Kill it at any point and run it again; it continues from the last completed page. A run that reaches the end clears its own state.

Two notes worth keeping. Resume repeats rather than drops, so an interrupted run re-delivers the page it was inside; deduplicate on `sys_id` if the output must be unique. And do not validate by comparing a line count against the API count, because the failure that costs you records replaces each lost one with a duplicate and leaves the total unchanged. Count distinct `sys_id`, or pass `verify=True` and let the sweep check itself.

Full detail on the [resume documentation page](https://snowloader.readthedocs.io/en/latest/resume.html).
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
    <td>Keyset pagination (<code>keyset=True</code>) and resumable extractions (<code>Checkpoint</code>, <code>FileCheckpoint</code>)</td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>v0.5</strong></td>
    <td>Command line: <code>snowloader extract</code> and <code>snowloader count</code>, with the careful choices as defaults</td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>v0.6</strong></td>
    <td><code>limit</code> on every loader, <code>checkpoint</code> on the loaders and the async path, and async adapters for the last two loaders</td>
    <td><img src="https://img.shields.io/badge/shipped-10b981.svg" alt="Shipped"></td>
  </tr>
  <tr>
    <td><strong>-</strong></td>
    <td>Direct vector store streaming. Removed: the LangChain and LlamaIndex adapters already reach dozens of stores, maintained by those projects</td>
    <td><img src="https://img.shields.io/badge/dropped-64748b.svg" alt="Dropped"></td>
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
