"""Compare per-CI relationship traversal against one cmdb_rel_ci sweep.

RelationshipLoader exists because CMDBLoader(include_relationships=True)
costs two requests for every configuration item. This measures both against
a live instance so the documentation can quote a number that came out of a
run rather than an estimate.

Author: Roni Das
Created: 2026-08-27
"""

from __future__ import annotations

import json
import os
import time
from itertools import islice
from pathlib import Path
from typing import Any

for _line in Path(".env").read_text().splitlines():
    if "=" in _line and not _line.strip().startswith("#"):
        _k, _v = _line.split("=", 1)
        os.environ[_k.strip()] = _v.strip()

from snowloader import CMDBLoader, RelationshipLoader, SnowConnection  # noqa: E402

SAMPLE_SIZE = 10
out: dict[str, Any] = {}

conn = SnowConnection(
    instance_url=os.environ["SNOW_INSTANCE"],
    username=os.environ["SNOW_USER"],
    password=os.environ["SNOW_PASS"],
    page_size=SAMPLE_SIZE,
)

ci_total = conn.get_count("cmdb_ci")
edge_total = conn.get_count("cmdb_rel_ci")
out["cmdb_ci_records"] = ci_total
out["cmdb_rel_ci_records"] = edge_total
print(f"cmdb_ci: {ci_total} CIs, cmdb_rel_ci: {edge_total} edges\n", flush=True)

# --- per CI traversal, on a small sample ----------------------------------
# islice, not a slice on a list comprehension: get_records is a generator and
# building the whole list first would sweep the entire table to get ten rows.
sample = [r["sys_id"] for r in islice(conn.get_records("cmdb_ci", fields=["sys_id"]), SAMPLE_SIZE)]
start = time.time()
walked = 0
for sys_id in sample:
    docs = CMDBLoader(conn, query=f"sys_id={sys_id}", include_relationships=True).load()
    walked += len(docs)
per_ci = (time.time() - start) / max(1, len(sample))

out["per_ci_traversal"] = {
    "sample": len(sample),
    "seconds_per_ci": round(per_ci, 2),
    "projected_hours_for_50k": round(per_ci * 50_000 / 3600, 1),
}
print("per CI traversal:", out["per_ci_traversal"], flush=True)

# --- one sweep of the relationship table ----------------------------------
sweep_conn = SnowConnection(
    instance_url=os.environ["SNOW_INSTANCE"],
    username=os.environ["SNOW_USER"],
    password=os.environ["SNOW_PASS"],
    page_size=100,
)
start = time.time()
edges = RelationshipLoader(sweep_conn).load(verify=True)
out["relationship_sweep"] = {
    "edges": len(edges),
    "seconds": round(time.time() - start, 1),
}
print("one cmdb_rel_ci sweep:", out["relationship_sweep"], flush=True)

sweep_conn.close()
conn.close()

Path("relationship_cost.json").write_text(json.dumps(out, indent=2))
print("\nwritten to relationship_cost.json", flush=True)
