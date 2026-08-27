"""Prove that ServiceNow honours a two column ORDERBY chain.

The v0.3.0 fix defaults every sweep to ORDERBYsys_created_on^ORDERBYsys_id so
that the chronological intent survives and the tiebreak is unique. That only
works if the instance treats the second ORDERBY as a genuine secondary sort
rather than ignoring it. This checks three things against a live table:

  1. the returned sequence is sorted by sys_created_on, then by sys_id
  2. a full sweep under the chain loses and duplicates nothing
  3. the same holds on the threaded path

Author: Roni Das
Created: 2026-08-27
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

for _line in Path(".env").read_text().splitlines():
    if "=" in _line and not _line.strip().startswith("#"):
        _k, _v = _line.split("=", 1)
        os.environ[_k.strip()] = _v.strip()

from snowloader import SnowConnection  # noqa: E402

TABLE = "cmdb_ci"
CHAIN = "ORDERBYsys_created_on^ORDERBYsys_id"
out: dict[str, Any] = {}

conn = SnowConnection(
    instance_url=os.environ["SNOW_INSTANCE"],
    username=os.environ["SNOW_USER"],
    password=os.environ["SNOW_PASS"],
    page_size=100,
)

api_count = conn.get_count(TABLE)
out["api_count"] = api_count
print(f"X-Total-Count for {TABLE}: {api_count}", flush=True)


def stats(rows: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    ids = [r["sys_id"] for r in rows]
    distinct = len(set(ids))
    return {
        "returned": len(ids),
        "distinct": distinct,
        "lost": api_count - distinct,
        "duplicated": len(ids) - distinct,
        "seconds": round(seconds, 1),
    }


# --- 1. is the chain a real two column sort? -------------------------------
t0 = time.time()
rows = list(conn.get_records(TABLE, query=CHAIN, fields=["sys_id", "sys_created_on"]))
elapsed = time.time() - t0

primary_breaks = 0
secondary_breaks = 0
ties_seen = 0
for prev, cur in zip(rows, rows[1:], strict=False):
    if cur["sys_created_on"] < prev["sys_created_on"]:
        primary_breaks += 1
    elif cur["sys_created_on"] == prev["sys_created_on"]:
        ties_seen += 1
        if cur["sys_id"] <= prev["sys_id"]:
            secondary_breaks += 1

out["chain_sort"] = {
    "rows": len(rows),
    "tied_adjacent_pairs": ties_seen,
    "primary_order_breaks": primary_breaks,
    "secondary_order_breaks": secondary_breaks,
    "is_two_column_sort": primary_breaks == 0 and secondary_breaks == 0 and ties_seen > 0,
}
print("chain sort:", out["chain_sort"], flush=True)

# --- 2. does the chain sweep clean, sequentially? --------------------------
out["sequential_chain"] = stats(rows, elapsed)
print("sequential chain:", out["sequential_chain"], flush=True)

# --- 3. does it sweep clean on the threaded path? --------------------------
t0 = time.time()
threaded = list(conn.concurrent_get_records(TABLE, query=CHAIN, fields=["sys_id"], max_workers=16))
out["concurrent_chain"] = stats(threaded, time.time() - t0)
print("concurrent chain:", out["concurrent_chain"], flush=True)

# --- 4. same page boundary twice, to catch an unstable tie ------------------
# An offset landing mid table must come back byte identical every time it is
# requested, otherwise the sort key is not unique enough to page over.
url = f"{conn.instance_url}/api/now/table/{TABLE}"


def one_page(order: str, offset: int) -> list[str]:
    data = conn._request(  # noqa: SLF001
        "GET",
        url,
        params={
            "sysparm_query": order,
            "sysparm_fields": "sys_id",
            "sysparm_limit": "100",
            "sysparm_offset": str(offset),
        },
    )
    return [r["sys_id"] for r in data.get("result", [])]


mid = (api_count // 200) * 100
out["page_repeat"] = {
    "offset": mid,
    "chain_is_stable": one_page(CHAIN, mid) == one_page(CHAIN, mid),
    "shipped_order_is_stable": (
        one_page("ORDERBYsys_created_on", mid) == one_page("ORDERBYsys_created_on", mid)
    ),
}
print("repeat of the same page:", out["page_repeat"], flush=True)

# --- 5. does a caller supplied filter survive the chain? -------------------
classes: dict[str, int] = {}
for r in conn.get_records(TABLE, query=CHAIN, fields=["sys_class_name"]):
    key = str(r.get("sys_class_name"))
    classes[key] = classes.get(key, 0) + 1
busiest = max(classes, key=lambda k: classes[k])
filter_query = f"sys_class_name={busiest}"

filtered = list(conn.get_records(TABLE, query=f"{filter_query}^{CHAIN}", fields=["sys_id"]))
out["filtered_chain"] = {
    "filter": filter_query,
    "api_count": conn.get_count(TABLE, query=filter_query),
    "returned": len(filtered),
    "distinct": len({r["sys_id"] for r in filtered}),
}
print("filter plus chain:", out["filtered_chain"], flush=True)

conn.close()
Path("order_chain_evidence.json").write_text(json.dumps(out, indent=2))
print("\nwritten to order_chain_evidence.json", flush=True)
