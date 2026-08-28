"""End to end tests for everything shipped up to 0.5.1, against a live instance.

These are not unit tests and they do not mock anything. Every assertion here
goes to a real ServiceNow instance, because the failures this package exists to
prevent are ones that only appear against a real one. The pagination bug passed
389 unit tests and a live sweep is what caught it. The CLI resume bug did the
same.

The table that matters most is cmdb_ci. On the development instance it holds
about 2,900 rows across only about 800 distinct sys_created_on values, so a
page boundary landing inside a tied group is not a theoretical risk here, it is
the normal case. Any path that returns the right count but the wrong distinct
count is broken, and that is what most of these check.

Run with:
    set -a; . ./.env; set +a
    pytest tests/integration/test_e2e_shipped.py -v

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from snowloader import (
    AttachmentLoader,
    CatalogLoader,
    ChangeLoader,
    CMDBLoader,
    FileCheckpoint,
    IncidentLoader,
    KnowledgeBaseLoader,
    ProblemLoader,
    RelationshipLoader,
    SnowConnection,
    TableLoader,
)

INSTANCE = os.environ.get("SNOW_INSTANCE", "")
USER = os.environ.get("SNOW_USER", "")
PASSWORD = os.environ.get("SNOW_PASS", "")

pytestmark = pytest.mark.skipif(
    not (INSTANCE and USER and PASSWORD),
    reason="needs SNOW_INSTANCE, SNOW_USER and SNOW_PASS for a live instance",
)

# The tied-timestamp table. Everything about pagination correctness uses it.
TIED_TABLE = "cmdb_ci"


def _sys_id(record: dict[str, Any]) -> str:
    """Pull the sys_id out whatever display_value mode produced the record."""
    raw = record["sys_id"]
    return str(raw["value"] if isinstance(raw, dict) else raw)


@pytest.fixture(scope="module")
def conn() -> Iterator[SnowConnection]:
    with SnowConnection(
        instance_url=INSTANCE, username=USER, password=PASSWORD, page_size=100
    ) as c:
        yield c


@pytest.fixture(scope="module")
def tied_count(conn: SnowConnection) -> int:
    return conn.get_count(TIED_TABLE)


# ---------------------------------------------------------------------------
# The bug this package exists for, checked on every path that can hit it
# ---------------------------------------------------------------------------


def test_sequential_sweep_returns_every_row_exactly_once(
    conn: SnowConnection, tied_count: int
) -> None:
    ids = [_sys_id(r) for r in conn.get_records(TIED_TABLE, fields=["sys_id"])]
    assert len(ids) == tied_count
    assert len(set(ids)) == tied_count, (
        f"{tied_count - len(set(ids))} rows lost to a tied sort column"
    )


def test_threaded_sweep_returns_every_row_exactly_once(
    conn: SnowConnection, tied_count: int
) -> None:
    """The threaded path fetches page offsets in parallel, so an unstable sort
    hurts it at least as much as the sequential one."""
    ids = [
        _sys_id(r)
        for r in conn.concurrent_get_records(TIED_TABLE, fields=["sys_id"], max_workers=16)
    ]
    assert len(ids) == tied_count
    assert len(set(ids)) == tied_count


def test_keyset_sweep_returns_every_row_exactly_once(conn: SnowConnection, tied_count: int) -> None:
    ids = [_sys_id(r) for r in conn.get_records(TIED_TABLE, fields=["sys_id"], keyset=True)]
    assert len(ids) == tied_count
    assert len(set(ids)) == tied_count


def test_every_path_agrees_on_the_same_row_set(conn: SnowConnection) -> None:
    """Not just the same count. The same rows. A count check would pass even if
    two paths lost different records."""
    seq = {_sys_id(r) for r in conn.get_records(TIED_TABLE, fields=["sys_id"])}
    thr = {
        _sys_id(r)
        for r in conn.concurrent_get_records(TIED_TABLE, fields=["sys_id"], max_workers=8)
    }
    key = {_sys_id(r) for r in conn.get_records(TIED_TABLE, fields=["sys_id"], keyset=True)}
    assert seq == thr, f"threaded differs from sequential by {len(seq ^ thr)} rows"
    assert seq == key, f"keyset differs from sequential by {len(seq ^ key)} rows"


def test_ordering_always_ends_on_the_unique_key(conn: SnowConnection) -> None:
    """Whatever the caller asks to sort by, the tiebreak has to survive."""
    params = conn._build_query_params(query="active=true^ORDERBYsys_created_on", fields=None)
    assert params["sysparm_query"].endswith("ORDERBYsys_id")


def test_a_sweep_repeated_is_stable(conn: SnowConnection) -> None:
    """The old bug was deterministic, so two runs matching proved nothing on its
    own. It is still worth knowing the fix is not flaky."""
    a = {_sys_id(r) for r in conn.get_records(TIED_TABLE, fields=["sys_id"])}
    b = {_sys_id(r) for r in conn.get_records(TIED_TABLE, fields=["sys_id"])}
    assert a == b


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def test_verify_passes_on_a_complete_sweep(conn: SnowConnection, tied_count: int) -> None:
    records = list(conn.get_records(TIED_TABLE, fields=["sys_id"], verify=True))
    assert len(records) == tied_count


def test_abandoning_a_verified_sweep_does_not_raise(conn: SnowConnection) -> None:
    """Closing the generator early is the caller deciding to stop, not the
    instance coming up short. Verification runs after the loop, so a closed
    stream skips it, and raising from close() would be the wrong contract.

    The case where the sweep really does come back short cannot be forced
    against a live instance on demand, so it is covered by the unit tests with
    a mocked short response instead.
    """
    stream = conn.get_records(TIED_TABLE, fields=["sys_id"], verify=True)
    for i, _ in enumerate(stream):
        if i > 150:
            stream.close()
            break


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def test_keyset_resume_loses_nothing(conn: SnowConnection, tied_count: int, tmp_path: Path) -> None:
    """Interrupt a sweep, resume it, and check the union covers the table. It
    is allowed to repeat the interrupted page. It is not allowed to skip one."""
    state = tmp_path / "resume.json"
    seen: list[str] = []

    first = conn.get_records(
        TIED_TABLE, fields=["sys_id"], keyset=True, checkpoint=FileCheckpoint(state)
    )
    for i, rec in enumerate(first):
        seen.append(_sys_id(rec))
        if i >= 500:
            first.close()
            break
    assert state.exists(), "an interrupted run must leave state behind"
    partial = len(seen)

    for rec in conn.get_records(
        TIED_TABLE, fields=["sys_id"], keyset=True, checkpoint=FileCheckpoint(state)
    ):
        seen.append(_sys_id(rec))

    assert len(set(seen)) == tied_count, "resume lost rows"
    assert len(seen) >= tied_count
    assert partial < tied_count, "the first leg should not have finished the table"
    assert not state.exists(), "a completed run must clear its own state"


def test_threaded_resume_loses_nothing(
    conn: SnowConnection, tied_count: int, tmp_path: Path
) -> None:
    state = tmp_path / "threaded.json"
    seen: list[str] = []

    first = conn.concurrent_get_records(
        TIED_TABLE, fields=["sys_id"], max_workers=8, checkpoint=FileCheckpoint(state)
    )
    for i, rec in enumerate(first):
        seen.append(_sys_id(rec))
        if i >= 400:
            first.close()
            break

    for rec in conn.concurrent_get_records(
        TIED_TABLE, fields=["sys_id"], max_workers=8, checkpoint=FileCheckpoint(state)
    ):
        seen.append(_sys_id(rec))

    assert len(set(seen)) == tied_count, "threaded resume lost rows"


def test_a_checkpoint_refuses_a_different_extraction(conn: SnowConnection, tmp_path: Path) -> None:
    """Resuming one table's state into another table's sweep would stitch two
    result sets into one output."""
    state = tmp_path / "mixed.json"
    stream = conn.get_records(
        TIED_TABLE, fields=["sys_id"], keyset=True, checkpoint=FileCheckpoint(state)
    )
    for i, _ in enumerate(stream):
        if i >= 150:
            stream.close()
            break

    with pytest.raises(Exception) as exc:
        list(
            conn.get_records(
                "incident", fields=["sys_id"], keyset=True, checkpoint=FileCheckpoint(state)
            )
        )
    assert "different extraction" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("loader_cls", "table"),
    [
        (IncidentLoader, "incident"),
        (KnowledgeBaseLoader, "kb_knowledge"),
        (CMDBLoader, "cmdb_ci"),
        (ChangeLoader, "change_request"),
        (ProblemLoader, "problem"),
        (CatalogLoader, "sc_cat_item"),
        (AttachmentLoader, "sys_attachment"),
        (RelationshipLoader, "cmdb_rel_ci"),
    ],
)
def test_each_loader_returns_usable_documents(
    conn: SnowConnection, loader_cls: Any, table: str
) -> None:
    docs = loader_cls(connection=conn).load(limit=5)
    assert docs, f"{loader_cls.__name__} returned nothing"
    for doc in docs:
        assert isinstance(doc.page_content, str)
        assert doc.page_content.strip(), f"{loader_cls.__name__} produced empty content"
        assert doc.metadata.get("sys_id"), f"{loader_cls.__name__} dropped the sys_id"
        assert doc.metadata.get("table") == table


def test_generic_table_loader_reads_a_table_with_no_dedicated_loader(
    conn: SnowConnection,
) -> None:
    docs = TableLoader(connection=conn, table="sys_user_group").load(limit=3)
    assert docs
    assert all(d.metadata["table"] == "sys_user_group" for d in docs)


def test_kb_articles_come_back_as_plain_text(conn: SnowConnection) -> None:
    docs = KnowledgeBaseLoader(connection=conn).load(limit=5)
    joined = " ".join(d.page_content for d in docs)
    for tag in ("<p>", "<div", "<span", "&nbsp;"):
        assert tag not in joined, f"HTML {tag} survived the cleaner"


def test_loader_verify_reaches_the_connection(conn: SnowConnection) -> None:
    docs = CMDBLoader(connection=conn).load(verify=True)
    ids = {d.metadata["sys_id"] for d in docs}
    assert len(ids) == len(docs), "loader returned duplicate documents"


# ---------------------------------------------------------------------------
# Reference fields
# ---------------------------------------------------------------------------


def test_metadata_carries_both_halves_of_a_reference(conn: SnowConnection) -> None:
    """The complaint that drove 0.3.0: a document could not be joined to
    anything because the loaders kept the label and threw the id away."""
    docs = IncidentLoader(connection=conn).load(limit=25)
    joinable = [d for d in docs if any(k.endswith("_sys_id") and d.metadata[k] for k in d.metadata)]
    assert joinable, "no document carried an identifier beside a reference label"

    doc = joinable[0]
    for key in [k for k in doc.metadata if k.endswith("_sys_id")]:
        assert len(str(doc.metadata[key])) == 32, f"{key} is not a sys_id"
        assert key[: -len("_sys_id")] in doc.metadata, f"{key} has no label beside it"


def test_reference_expansion_can_be_turned_off(conn: SnowConnection) -> None:
    """The escape hatch for vector stores with a per-vector size limit."""
    wide = IncidentLoader(connection=conn).load(limit=5)
    narrow = IncidentLoader(connection=conn, expand_references=False).load(limit=5)
    assert not [k for k in narrow[0].metadata if k.endswith("_sys_id")]
    assert len(wide[0].metadata) > len(narrow[0].metadata)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "snowloader.cli", *args],
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "SNOW_INSTANCE": INSTANCE, "SNOW_USER": USER, "SNOW_PASS": PASSWORD},
    )


def test_cli_count_prints_a_number_matching_the_api(conn: SnowConnection) -> None:
    result = _cli("count", TIED_TABLE)
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) == conn.get_count(TIED_TABLE)


def test_cli_extract_writes_every_row_exactly_once(tied_count: int, tmp_path: Path) -> None:
    out = tmp_path / "cmdb.jsonl"
    result = _cli("extract", TIED_TABLE, "--out", str(out), "--fields", "sys_id")
    assert result.returncode == 0, result.stderr

    ids = [_sys_id(json.loads(line)) for line in out.read_text().splitlines()]
    assert len(ids) == tied_count
    assert len(set(ids)) == tied_count


def test_cli_resume_continues_and_loses_nothing(tied_count: int, tmp_path: Path) -> None:
    """The bug a live run found and 389 unit tests did not: resuming onto a
    finished output appended the whole table a second time."""
    out = tmp_path / "resume.jsonl"
    first = _cli("extract", TIED_TABLE, "--out", str(out), "--fields", "sys_id", "--resume")
    assert first.returncode == 0, first.stderr

    ids = [_sys_id(json.loads(line)) for line in out.read_text().splitlines()]
    assert len(set(ids)) == tied_count

    again = _cli("extract", TIED_TABLE, "--out", str(out), "--fields", "sys_id", "--resume")
    assert again.returncode == 2, "resuming a finished output must be refused"
    after = out.read_text().splitlines()
    assert len(after) == len(ids), "the refused run still touched the file"


def test_cli_refuses_to_overwrite_silently(tmp_path: Path) -> None:
    out = tmp_path / "existing.jsonl"
    out.write_text('{"keep": "me"}\n')
    result = _cli("extract", TIED_TABLE, "--out", str(out))
    assert result.returncode == 2
    assert out.read_text() == '{"keep": "me"}\n'


def test_cli_sorts_on_a_unique_key_whatever_the_query_says(tied_count: int, tmp_path: Path) -> None:
    """A caller passing their own non-unique ordering must not be able to
    reintroduce the bug."""
    out = tmp_path / "forced.jsonl"
    result = _cli(
        "extract",
        TIED_TABLE,
        "--out",
        str(out),
        "--fields",
        "sys_id",
        "--query",
        "ORDERBYsys_created_on",
    )
    assert result.returncode == 0, result.stderr
    ids = [_sys_id(json.loads(line)) for line in out.read_text().splitlines()]
    assert len(set(ids)) == tied_count, "a caller supplied ordering lost rows"


def test_cli_threaded_extract_matches_sequential(tied_count: int, tmp_path: Path) -> None:
    out = tmp_path / "threaded.jsonl"
    result = _cli("extract", TIED_TABLE, "--out", str(out), "--fields", "sys_id", "--workers", "16")
    assert result.returncode == 0, result.stderr
    ids = [_sys_id(json.loads(line)) for line in out.read_text().splitlines()]
    assert len(set(ids)) == tied_count


def test_cli_display_value_all_keeps_both_halves(tmp_path: Path) -> None:
    out = tmp_path / "raw.jsonl"
    result = _cli(
        "extract",
        "incident",
        "--out",
        str(out),
        "--display-value",
        "all",
        "--fields",
        "sys_id,priority",
    )
    assert result.returncode == 0, result.stderr
    first = json.loads(out.read_text().splitlines()[0])
    assert isinstance(first["priority"], dict)
    assert {"value", "display_value"} <= set(first["priority"])
