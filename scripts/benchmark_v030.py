"""Measure the numbers the 0.3.0 documentation quotes.

Nothing in the docs should claim a figure that did not come out of a run.
This produces all of them against a live instance: worker scaling, the
page size surprise, sequential against threaded against async, and what
keep_alive is worth on the async path.

Author: Roni Das
Created: 2026-08-27
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

for _line in Path(".env").read_text().splitlines():
    if "=" in _line and not _line.strip().startswith("#"):
        _k, _v = _line.split("=", 1)
        os.environ[_k.strip()] = _v.strip()

from snowloader import AsyncSnowConnection, SnowConnection  # noqa: E402

TABLE = "cmdb_ci"
INSTANCE = os.environ["SNOW_INSTANCE"]
USER = os.environ["SNOW_USER"]
PASSWORD = os.environ["SNOW_PASS"]

out: dict[str, Any] = {}


def sync_conn(**kw: Any) -> SnowConnection:
    return SnowConnection(instance_url=INSTANCE, username=USER, password=PASSWORD, **kw)


def timed_sweep(conn: SnowConnection, *, workers: int | None = None) -> dict[str, Any]:
    start = time.time()
    if workers is None:
        rows = list(conn.get_records(TABLE, fields=["sys_id"]))
    else:
        rows = list(conn.concurrent_get_records(TABLE, fields=["sys_id"], max_workers=workers))
    seconds = round(time.time() - start, 1)
    ids = [r["sys_id"] for r in rows]
    return {"seconds": seconds, "returned": len(ids), "distinct": len(set(ids))}


conn = sync_conn(page_size=100)
total = conn.get_count(TABLE)
out["table"] = TABLE
out["records"] = total
print(f"{TABLE}: {total} records\n", flush=True)

# --- 1. sequential baseline ------------------------------------------------
out["sequential"] = timed_sweep(conn)
print("sequential:", out["sequential"], flush=True)

# --- 2. worker scaling on the threaded path --------------------------------
out["threaded_by_workers"] = {}
for workers in (4, 8, 16, 32):
    result = timed_sweep(conn, workers=workers)
    out["threaded_by_workers"][workers] = result
    speedup = round(out["sequential"]["seconds"] / result["seconds"], 1)
    print(f"threaded w={workers:<3} {result} speedup={speedup}x", flush=True)

# --- 3. page size, which goes the wrong way --------------------------------
out["threaded_by_page_size"] = {}
for page_size in (100, 250, 500, 1000):
    sized = sync_conn(page_size=page_size)
    result = timed_sweep(sized, workers=16)
    sized.close()
    out["threaded_by_page_size"][page_size] = result
    print(f"threaded w=16 page_size={page_size:<5} {result}", flush=True)

conn.close()


# --- 4. the async path -----------------------------------------------------
async def async_sweep(**kw: Any) -> dict[str, Any]:
    async with AsyncSnowConnection(
        instance_url=INSTANCE,
        username=USER,
        password=PASSWORD,
        **kw,
    ) as connection:
        start = time.time()
        ids = [rec["sys_id"] async for rec in connection.aget_records(TABLE, fields=["sys_id"])]
        seconds = round(time.time() - start, 1)
    return {"seconds": seconds, "returned": len(ids), "distinct": len(set(ids))}


async def async_suite() -> dict[str, Any]:
    results: dict[str, Any] = {}
    results["page_500_no_keepalive"] = await async_sweep(page_size=500, concurrency=16)
    print("async page_size=500 (the default):    ", results["page_500_no_keepalive"], flush=True)

    results["page_100_no_keepalive"] = await async_sweep(page_size=100, concurrency=16)
    print("async page_size=100:                  ", results["page_100_no_keepalive"], flush=True)

    results["page_100_keepalive"] = await async_sweep(
        page_size=100, concurrency=16, keep_alive=True
    )
    print("async page_size=100 keep_alive=True:  ", results["page_100_keepalive"], flush=True)
    return results


out["async"] = asyncio.run(async_suite())

Path("benchmark_v030.json").write_text(json.dumps(out, indent=2))
print("\nwritten to benchmark_v030.json", flush=True)
