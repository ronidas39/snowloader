"""Baseline evidence against the shipped 0.2.8 behaviour, on a live instance.

Reproduces the two failures the gaps document reports:
  1. offset pagination over a non-unique sort column loses rows silently
  2. loaders stringify the sys_id dict and drop the joinable half

Run before any source change so the numbers are comparable afterwards.
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

from snowloader import IncidentLoader, SnowConnection  # noqa: E402

TABLE = "cmdb_ci"
out: dict[str, Any] = {}


def conn(**kw: Any) -> SnowConnection:
    return SnowConnection(
        instance_url=os.environ["SNOW_INSTANCE"],
        username=os.environ["SNOW_USER"],
        password=os.environ["SNOW_PASS"],
        **kw,
    )


def sweep_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
    ids = []
    for r in rows:
        sid = r.get("sys_id")
        ids.append(sid["value"] if isinstance(sid, dict) else sid)
    return {"returned": len(ids), "distinct": len(set(ids))}


c = conn(page_size=100)
api_count = c.get_count(TABLE)
out["api_count"] = api_count
print(f"X-Total-Count for {TABLE}: {api_count}", flush=True)

# --- 1. tie analysis -------------------------------------------------------
rows = list(c.get_records(TABLE, query="ORDERBYsys_id", fields=["sys_id", "sys_created_on"]))
stamps: dict[str, int] = {}
for r in rows:
    stamps[str(r.get("sys_created_on"))] = stamps.get(str(r.get("sys_created_on")), 0) + 1
out["tie_analysis"] = {
    "rows": len(rows),
    "distinct_timestamps": len(stamps),
    "worst_tie": max(stamps.values()) if stamps else 0,
}
print("tie analysis:", out["tie_analysis"], flush=True)

# --- 2. three sequential sweeps with the shipped default order -------------
out["sequential_default_order"] = []
baseline_sets = []
for run in range(3):
    t0 = time.time()
    rows = list(c.get_records(TABLE, fields=["sys_id"]))
    st = sweep_stats(rows)
    st["lost"] = api_count - st["distinct"]
    st["duplicated"] = st["returned"] - st["distinct"]
    st["seconds"] = round(time.time() - t0, 1)
    st["count_matches_api"] = st["returned"] == api_count
    baseline_sets.append({r["sys_id"] for r in rows})
    out["sequential_default_order"].append(st)
    print(f"  run {run + 1}: {st}", flush=True)

out["loss_is_deterministic"] = baseline_sets[0] == baseline_sets[1] == baseline_sets[2]
print("loss deterministic across runs:", out["loss_is_deterministic"], flush=True)

# --- 3. same sweep with a unique sort key ----------------------------------
t0 = time.time()
rows = list(c.get_records(TABLE, query="ORDERBYsys_id", fields=["sys_id"]))
st = sweep_stats(rows)
st["lost"] = api_count - st["distinct"]
st["duplicated"] = st["returned"] - st["distinct"]
st["seconds"] = round(time.time() - t0, 1)
out["sequential_unique_order"] = st
print("sequential ORDERBYsys_id:", st, flush=True)

# --- 4. concurrent path, both orders ---------------------------------------
for label, q in (("concurrent_default_order", None), ("concurrent_unique_order", "ORDERBYsys_id")):
    t0 = time.time()
    rows = list(c.concurrent_get_records(TABLE, query=q, fields=["sys_id"], max_workers=16))
    st = sweep_stats(rows)
    st["lost"] = api_count - st["distinct"]
    st["duplicated"] = st["returned"] - st["distinct"]
    st["seconds"] = round(time.time() - t0, 1)
    out[label] = st
    print(f"{label}: {st}", flush=True)

# --- 5. which records go missing -------------------------------------------
clean = list(c.get_records(TABLE, query="ORDERBYsys_id", fields=["sys_id", "name"]))
clean_names = {r["sys_id"]: r.get("name") for r in clean}
lossy_ids = baseline_sets[0]
out["records_lost"] = sorted(str(clean_names[i]) for i in (set(clean_names) - lossy_ids))
print("records lost by the default order:", out["records_lost"], flush=True)

# --- 6. loader metadata shape ----------------------------------------------
for dv in ("true", "all"):
    lc = conn(page_size=5, display_value=dv)
    docs = IncidentLoader(lc, query="ORDERBYsys_id").load()[:1]
    lc.close()
    if docs:
        md = docs[0].metadata
        out[f"incident_metadata_display_value_{dv}"] = {
            "keys": sorted(md),
            "sys_id": md.get("sys_id"),
            "assigned_to": md.get("assigned_to"),
            "cmdb_ci": md.get("cmdb_ci"),
            "assignment_group": md.get("assignment_group"),
            "has_any_sys_id_companion": any(k.endswith("_sys_id") for k in md),
        }
        print(f"\nincident metadata (display_value={dv}):", flush=True)
        print(json.dumps(out[f"incident_metadata_display_value_{dv}"], indent=2), flush=True)

c.close()
Path("baseline_evidence.json").write_text(json.dumps(out, indent=2))
print("\nwritten to baseline_evidence.json", flush=True)
