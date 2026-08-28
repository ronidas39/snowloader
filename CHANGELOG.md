# Changelog

All notable changes to snowloader are documented here. This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **A command line interface.** `snowloader extract` and `snowloader count`,
  with no new dependencies.

  It exists because the pieces were all in the library and people were still
  assembling them by hand and getting it wrong. Of the extraction scripts
  written against this package beforehand, two built their own encoded query
  with a non-unique sort, so they never picked up the ordering fix, and one
  validated itself by comparing a line count against the record count, which
  is the one check that cannot detect the loss that causes.

  So the defaults are the careful ones. The sort always ends on `sys_id` and
  there is no option to change it. Verification is on unless switched off
  deliberately. An incomplete sweep exits 1, a usage problem exits 2, and an
  interruption exits 130 with a note about `--resume`.

  It refuses to overwrite an output file without being told, and it refuses to
  resume onto a finished one. A completed run deletes its own state, so an
  output with no state beside it is finished, and appending to it would write
  the whole table in a second time. The result would look entirely plausible
  while holding every record twice.

  Credentials come from `SNOW_INSTANCE`, `SNOW_USER` and `SNOW_PASS` when the
  options are not given, so a password need not reach a shell history or a
  process list.

### Documentation

- New page, `docs/cli.rst`.

## [0.4.0] - 2026-08-28

### Added

- **Keyset pagination.** `get_records(keyset=True)` pages on a `sys_id` cursor
  instead of an offset, asking each time for the rows after the last one seen.
  It keeps your filter and any delta cutoff in front of the cursor, reads the
  cursor from the value half so `display_value="all"` works, and composes with
  `verify` and the loaders. It refuses a field list without `sys_id`, since the
  cursor comes out of the records, and a deliberate `order_by`, since a single
  value cursor can only walk the column it sorts by. A page whose last record
  carries no usable `sys_id` raises rather than repeating the same request.

  Worth being plain about what it is for. The usual argument for keyset is that
  deep offsets cost more than shallow ones. That was not reproducible here: on
  a 2,919 row table, median of five requests, a page at offset 2,800 took
  1,118 ms against 1,125 ms at offset 0. Flat. End to end keyset came out
  slightly slower than offset, because it is sequential where the threaded
  paginator is not. Its real value is that the position is one value you can
  write down, and that it cannot be caught by the tied sort problem. Measure
  your own table before choosing it for speed.

- **Resumable extractions.** `Checkpoint` and `FileCheckpoint` record how far
  a run reached, so running the same call again continues rather than starting
  over. Supported on `get_records` with `keyset=True`, and on
  `concurrent_get_records`, which records the set of finished page offsets
  because it completes pages out of order.

  State is written when a page is complete, not when a record is handed over,
  so an interrupted run repeats the page it was in the middle of rather than
  dropping it. Interrupting a live sweep of 2,919 records after 500 at page
  size 200 gave 3,019 lines, 2,919 distinct, 0 missing and 100 duplicates,
  the duplicates being that one page.

  Every checkpoint carries a fingerprint of table, query, field list, page size
  and mode, and refuses to be read by a run that does not match. Resuming into
  a different result set would produce an output that is partly one thing and
  partly another, which is worse than starting again.

  `FileCheckpoint` writes atomically and treats an unparseable file as absent,
  so a process killed mid-write cannot block the next run.

### Documentation

- New page, `docs/resume.rst`: both kinds of position, why it repeats rather
  than drops, what the fingerprint protects against, and how to keep state
  somewhere other than a file.

## [0.3.1] - 2026-08-28

Documentation only. No code changed, so there is nothing to gain by upgrading
from 0.3.0 unless you want the newer project page.

PyPI renders the README that was inside the uploaded distribution rather than
the one in the repository, and it does not accept a re-upload of a version
that already exists. The project page was therefore stuck showing the README
as it stood when 0.3.0 was tagged. This release exists to move it forward.

### Documentation

- The Read the Docs site has a stylesheet of its own for the first time,
  drawn in the same palette as the diagrams so the pages and the images look
  like one thing. It adds a hero, feature cards, a numbers strip, framed
  figures with captions, and a dark mode that does not wash the diagrams out.
- The landing page was rebuilt around it: what the library is for, the
  pagination diagram and the numbers behind it, what you get, and how the
  pieces fit together.
- New diagram showing incident metadata before and after 0.3.0, which makes
  the reference field change easier to see than to read about.
- The architecture diagram was still saying seven loaders and had no
  `cmdb_rel_ci` on it. The throughput chart was showing estimated relative
  bars; it now shows the measured seconds behind them.
- README reorganised for the project pages: one badge row rather than three, a
  plainer statement of what the library does, the pagination diagram directly
  under it, and a table of the numbers. Verified through `readme_renderer`,
  which is what PyPI runs, so the diagrams and tables are known to survive its
  sanitising.
- Swapped the downloads badge, which was often rendering as rate limited by
  the upstream service.

## [0.3.0] - 2026-08-27

This release fixes a data loss bug. If you are on 0.2.x and you sweep a table
whose `sys_created_on` has repeated values, some of your records are missing
and nothing told you. Upgrade.

### Fixed

- **Pagination no longer loses records.** Every paginated request now ends its
  ORDERBY chain with `sys_id`. ServiceNow offset pagination is only safe over a
  unique sort key: the API does not guarantee a stable order inside a group of
  rows that tie on the sort column, so a page boundary landing inside a tied
  group returns some rows twice and skips others. Every release before this one
  sorted on `sys_created_on`, which is not unique.

  Measured on a developer instance: `cmdb_ci` holds 2,919 rows across only 818
  distinct `sys_created_on` values, worst tie 31 rows. Three consecutive sweeps
  each returned exactly 2,919 rows, matching the count the instance reported,
  but only 2,915 distinct. Four records replaced by four duplicates, the same
  four every run. The count reconciles so nothing reports a problem, and the
  loss is deterministic so re-running never surfaces it and diffing two runs
  shows nothing. On a 30,000 row CMDB that rate is roughly 40 missing CIs.

  With the fix, the same table returns all 2,919 distinct rows on both the
  sequential and the threaded path. Confirmed on the same instance in the same
  session, along with the fact that ServiceNow honours
  `ORDERBYsys_created_on^ORDERBYsys_id` as a genuine two column sort: across
  2,101 adjacent pairs sharing a timestamp, `sys_id` ascended inside every one.

  Applies to `SnowConnection`, `AsyncSnowConnection`, the threaded paginator
  and every loader. No code change needed to get it.

- **A 200 response whose body is not a JSON object no longer loses data on the
  sync paths.** Some ServiceNow front ends answer with HTTP 200 and a body of
  `null` under load. The sequential reader called `.get("result")` on it and
  raised `AttributeError`, which no `except SnowConnectionError` catches. The
  threaded reader was worse: it turned the page into an empty list, so a sweep
  of 250 records returned zero and reported success. Both now retry the
  response and then raise `SnowConnectionError`, matching what the async path
  has done since 0.2.3.

- **`asyncio.TimeoutError` no longer escapes the async retry loop.** It is not
  a subclass of `aiohttp.ClientError`, so a total-timeout breach bypassed
  `max_retries` entirely and reached the caller as an exception their handler
  did not catch.

- **`SweepReport.complete` accounts for skipped pages.** A report with
  `failed_pages` greater than zero was still reported complete when the totals
  happened to line up, which they can when the table grew during the read.

- **`expand_references` and `include_raw` work on every loader.** They were
  missing from `CMDBLoader` and `AttachmentLoader` and their async variants, so
  the escape hatch this changelog and the README told upgraders to use raised
  `TypeError` on the two loaders with the widest records.

- **`AttachmentLoader` expands reference fields.** It was the one loader that
  never called the shared metadata builder, so it received none of the
  reference work described below.

- **`sys_id` is a plain string in every display value mode.** With
  `display_value="all"` the loaders put the string form of a dict in metadata,
  so the primary key read as `"{'display_value': '02a73898...', 'value':
  '02a73898...'}"`.

### Added

- **`verify=True` on every read path.** Counts the table before the sweep and
  raises `SweepIncompleteError` if the sweep did not return that many distinct
  records. Available on `get_records`, `concurrent_get_records`, `aget_records`,
  and on `load`, `lazy_load`, `concurrent_load`, `concurrent_lazy_load`,
  `aload` and `alazy_load`. Costs one extra request on the sequential path and
  nothing on the threaded and async paths, which already fetch that count to
  plan their pages. Off by default, because it holds one key per record.

- **`SweepReport` and `SweepIncompleteError`.** The report carries `expected`,
  `returned`, `distinct`, `missing`, `duplicates`, `failed_pages` and
  `complete`, and is attached to the exception. `SweepIncompleteError`
  subclasses `SnowConnectionError`, so existing handlers keep catching it.

- **Reference fields carry both halves.** Metadata now holds the readable
  label under a field's own name and the identifier beside it:
  `assignment_group` and `assignment_group_sys_id`, `caller_id` and
  `caller_id_sys_id`. The suffix names what it holds: `_sys_id` when the value
  identifies another record, `_value` when it does not, so anything under a
  `_sys_id` key can be joined on. Fields whose halves are identical get no
  companion.

- **Field helpers are public.** `display_value`, `raw_value`, `reference`,
  `ReferenceField`, `is_sys_id`, `parse_boolean` and `expand_reference_keys`
  are exported from the package root. Every consumer was writing these by hand.

- **`order_by` on both connections.** Takes a column name, a list of columns,
  or a ready-made clause such as `"ORDERBYDESCsys_created_on"`. `sys_id` is
  appended as a tiebreak unless the chain already sorts on it. `None` turns
  ordering off. An empty string or empty list is refused rather than treated as
  an opt-out.

- **`on_error="skip"`.** An unrecoverable page logs at ERROR, leaves a gap and
  lets the sweep finish, rather than aborting it. Retries still happen first, so
  a page only counts as failed once `max_retries` is exhausted. Compose it with
  `verify=True` for an unattended run: it completes, then raises with a report
  saying exactly how much was lost. Default stays `"raise"`.

- **`TableLoader`.** A generic loader for any ServiceNow table. Content fields
  can be given explicitly or picked per record from the usual text columns.
  Metadata gets the same reference expansion as every other loader.

- **`RelationshipLoader`.** Sweeps `cmdb_rel_ci` directly and returns one
  document per edge, with `parent_sys_id`, `child_sys_id` and `type_sys_id`
  populated. `CMDBLoader(include_relationships=True)` costs two extra requests
  per CI, which measured at 2.4 seconds per CI on a developer instance and
  projects to about 34 hours for a 50,000 CI estate. Sweeping the whole
  relationship table on the same instance took 7 seconds.

- **`AsyncRelationshipLoader` and `AsyncTableLoader`.** The README and the
  async guide both said every sync loader had a matching async variant. Until
  these existed that was not true of the two loaders added in this release.

- **`aconcurrent_get_records`.** `aget_records` already fetched pages
  concurrently, so this is the same method under the name someone coming from
  the sync API looks for. It used to raise `AttributeError`.

- **`since_field` on both connections.** The column a delta sync compares its
  cutoff against. Defaults to `sys_updated_on`. Set it to `sys_created_on` on an
  append-only table, or where the update column is not indexed.

- **`expand_references` and `include_raw` on every loader.**
  `expand_references=False` restores the curated-only metadata from 0.2.x.
  `include_raw=True` attaches the untouched API record under `"raw"`.

- **`keep_alive` on `AsyncSnowConnection`.** `force_close=True` has been the
  default since 0.2.3, because some ServiceNow front ends return empty response
  bodies on reused connections under concurrent load, which corrupts a
  paginated read silently. It stays the default. `keep_alive=True` hands that
  trade back to callers who have measured their own instance. Worth saying that
  it did not measure faster here: across two runs it came out slightly slower
  than leaving it off, so it is something to test rather than a free win.

### Changed

- **Breaking: `cmdb_ci` in incident metadata now holds the label.** It held a
  bare sys_id while every sibling reference held a label, so one dict mixed two
  conventions and no field had both. The identifier moved to `cmdb_ci_sys_id`.

- **Breaking: loader metadata is fuller.** Every field on the record reaches
  metadata now, not just the dozen or so each loader curated. `caller_id` and
  `opened_by` were absent from incident metadata entirely. On a wide table
  that is roughly three times the previous metadata size, which is worth
  checking if you write the whole dict into a vector store with a per-vector
  limit. Pass `expand_references=False` for the old shape.

- LlamaIndex readers now exclude every `*_sys_id` companion from
  `excluded_llm_metadata_keys` alongside `sys_id`. Reference expansion puts an
  identifier beside every reference, and a model reading a 32 character sys_id
  learns nothing while paying for all of it. They stay in `metadata`, where
  they are useful.

- `SnowConnectionError` moved to `snowloader.exceptions` so the sync and async
  connections can share it. It is still importable from `snowloader` and from
  `snowloader.connection`; nothing needs changing.

### Build

- The sdist is now an explicit allow list rather than whatever happens to be
  in the working directory. A locally built sdist was picking up local tooling
  directories and scratch files: 253 entries, of which 133 had no business
  being published. It is 92 curated entries now.

- mypy now runs with `python_version = "3.12"` instead of 3.10. numpy ships
  stubs written with PEP 695 `type` statements, which mypy refuses to parse at
  3.10, and numpy reaches us through `llama-index-core`. Our 3.10 floor is
  still enforced: ruff runs at `target-version = "py310"` and the CI matrix
  runs the full suite on a real 3.10 interpreter.
- The `dev` extra caps aiohttp below 3.14. aiohttp 3.14 changed
  `ClientResponse.__init__` to require `stream_writer` and `aioresponses`
  still builds one without it, so the async tests failed inside the mock
  rather than in library code. The `async` and `all` extras are deliberately
  left unpinned: snowloader itself runs correctly on aiohttp 3.14, verified
  against a live instance with a full verified sweep.

### Documentation

- New page, `docs/verification.rst`: what the ordering bug was, the numbers it
  was measured with, how `order_by` works, and a checklist for an unattended
  run.
- New page, `docs/references.rst`: the three shapes a field arrives in, what
  metadata holds, the public helpers, and the `sys_class_name` trap that files
  a MySQL instance under a label no table is called.
- Concurrency and page size guidance on both paths replaced with measured
  tables from `scripts/benchmark_v030.py`. Threaded throughput peaks at 16
  workers and a page size in the low hundreds; the async path wants larger
  pages instead. The two paths pull in opposite directions, so the docs now
  say not to carry a page size from one to the other.
- `docs/async.rst` states plainly that async is not the fastest path. It beat
  the sequential sweep by about five times and the threaded paginator beat it
  again. Async is for staying inside an event loop, not for throughput.
- Note in `docs/async.rst` on `SSLCertVerificationError` from aiohttp on
  macOS, which is a missing CA bundle in the Python install rather than
  anything to do with this library.
- README, index and roadmap updated for the release.

## [0.2.8] - 2026-04-28

### Documentation

- README rebuilt around three pre-rendered infographics: data-flow architecture diagram, relative-throughput chart, and an API decision tree. Images live in `docs/_static/` and render on PyPI via raw GitHub URLs.
- New `scripts/build_assets.py` regenerates the diagrams whenever the asset code changes; uses matplotlib only at build time so PyPI and ReadTheDocs stay matplotlib-free at install.
- Hero section reorganized with grouped badge rows (install / quality / framework support), tagline, and quick navigation links.
- Feature grid replaces the bullet list with a three-column table of capability cards.
- Code examples consolidated into eight collapsible `<details>` sections (sequential, threaded, async, LangChain, LlamaIndex, delta sync, CMDB graph, journals, attachments, auth, large-scale resume recipe) so the page reads short but holds depth.
- Roadmap rewritten as an HTML table with shields.io status badges (green for shipped, amber for planned).
- Author card added at the bottom in a clean two-column layout.

## [0.2.7] - 2026-04-28

### Documentation

- README gains a "Recipe: large-scale extraction with resume support" subsection showing the two-pull corpus pattern (closed corpus + active corpus) with raw `display_value=all` JSONL output, sys_id/number skip filter, and end-of-run validation against `/api/now/stats`.
- `docs/concurrent.rst` extended with the full two-pull recipe including offset-level state file checkpointing, per-thread sessions for connection isolation, and an explanation of why a single "last offset" cursor is not enough for the threaded paginator.
- All examples use generic placeholders (`yourcompany.service-now.com`, `api_user`, `api_pass`) so the documentation does not leak real instance details.

## [0.2.6] - 2026-04-28

### Documentation

- README updated with a `Concurrent Sync API` section showing `get_count`, `concurrent_get_records`, and `concurrent_load`. Roadmap table now lists the threaded paginator as Shipped.
- New Sphinx page `docs/concurrent.rst` covering when to pick threaded sync vs async, per-thread session isolation, real-world numbers from a 457k-record extraction, and tunables (`max_workers`, `page_size`, `max_retries`, `retry_backoff`).
- Roadmap consolidated: v0.2 Shipped section now covers the full 0.2.0 through 0.2.5 history including async, attachments, threaded sync, and the connection robustness patches.

## [0.2.5] - 2026-04-28

### Added

- `SnowConnection.get_count(table, query, since)` - sync sibling of `aget_count`. Hits `/api/now/stats/<table>` and returns the integer record count. Used internally by the new threaded paginator and useful for users who need the total before deciding how to fetch.
- `SnowConnection.concurrent_get_records(table, query, fields, since, max_workers=16)` - threaded paginator that fetches pages in parallel using a `ThreadPoolExecutor`. Each worker thread holds its own `requests.Session` so connection pools and TLS state stay isolated. This avoids the connection-reuse failures some ServiceNow front ends exhibit when many concurrent requests share a single client session, and gives sync users the same throughput characteristics as the async path without the aiohttp dependency.
- `BaseSnowLoader.concurrent_load(max_workers)` and `BaseSnowLoader.concurrent_lazy_load(max_workers, since)` - high-level loader methods that yield `SnowDocument` objects through the threaded paginator.

### Changed

- `SnowConnection._request` now delegates to a new internal `_request_with_session(session, method, url, params)` so caller-provided sessions can use the same retry, OAuth refresh, and rate-limiting logic. The shared-session lock is still applied when called via the default `_request` path.

## [0.2.4] - 2026-04-28

### Changed

- Truncated or malformed JSON responses are now treated as transient failures and retried up to `max_retries` instead of raising immediately. Some ServiceNow front ends occasionally return cut-off response bodies under sustained concurrent load; this change keeps long extractions alive through those blips.

## [0.2.3] - 2026-04-28

### Changed

- `AsyncSnowConnection` now uses `force_close=True` and `limit_per_host=concurrency` on its `aiohttp.TCPConnector`. Each request gets a fresh TCP connection, which avoids the connection-reuse failures some ServiceNow instances exhibit under sustained concurrent load.
- Non-object JSON bodies (e.g. `null` or a list returned with HTTP 200) are now treated as transient failures: the SDK retries up to `max_retries` and raises `SnowConnectionError` if the issue persists. Previously the v0.2.2 fallback silently treated them as empty pages, which would lose data.
- HTTP 500 added to the default retryable status code set on both `SnowConnection` and `AsyncSnowConnection`. ServiceNow 500s are typically transient overload, not deterministic bugs.

### Fixed

- `AsyncSnowConnection.aget_records` no longer crashes with `AttributeError` when a page returns a non-object JSON body. The retry-then-raise behavior surfaces the failure clearly instead of silently dropping data.

## [0.2.2] - 2026-04-28

### Fixed

- `AsyncSnowConnection.aget_records` no longer crashes with `AttributeError: 'NoneType' object has no attribute 'get'` when the API returns a non-object JSON body (e.g. `null` or a list under transient load). Such responses are now logged and treated as an empty result, letting the rest of the pages stream through.
- `AsyncSnowConnection._request` now validates that the parsed JSON body is a dict before returning, so downstream callers can rely on the `dict[str, Any]` contract.

## [0.2.1] - 2026-04-28

### Changed

- Roadmap entries for Async support and the Attachment loader marked as Shipped.

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
