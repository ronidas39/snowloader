"""Tests for resuming an async sweep.

Resume shipped in 0.4.0 on the sequential and threaded sync paths, and 0.5.0
put it behind the command line. The async path never got it, so anyone whose
pipeline is async had the feature documented at them and not available. These
tests define what it has to do before the implementation exists.

The async path dispatches every page concurrently and yields in completion
order, so like the threaded sync path it cannot record one furthest position.
It records the set of page offsets that finished, and only once every record of
a page has been handed to the caller.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from snowloader.checkpoints import FileCheckpoint
from snowloader.exceptions import SnowConnectionError

aiohttp = pytest.importorskip("aiohttp")
aioresponses_mod = pytest.importorskip("aioresponses")
aioresponses = aioresponses_mod.aioresponses

from snowloader.async_connection import AsyncSnowConnection  # noqa: E402

BASE_URL = "https://test.service-now.com"
TABLE_RE = re.compile(rf"^{re.escape(BASE_URL)}/api/now/table/incident(\?.*)?$")
STATS_RE = re.compile(rf"^{re.escape(BASE_URL)}/api/now/stats/incident(\?.*)?$")


def _rows(start: int, count: int) -> list[dict[str, str]]:
    return [{"sys_id": f"{i:032x}", "number": f"INC{i:07d}"} for i in range(start, start + count)]


def _conn(**kwargs: Any) -> AsyncSnowConnection:
    return AsyncSnowConnection(instance_url=BASE_URL, username="admin", password="secret", **kwargs)


def _mock_table(m: Any, total: int, page_size: int) -> None:
    m.get(STATS_RE, payload={"result": {"stats": {"count": str(total)}}}, repeat=True)
    for offset in range(0, total, page_size):
        m.get(TABLE_RE, payload={"result": _rows(offset, min(page_size, total - offset))})


# ---------------------------------------------------------------------------
# The parameter exists at all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aget_records_accepts_a_checkpoint(tmp_path: Path) -> None:
    """The gap this closes. Before it, this call raised TypeError."""
    state = tmp_path / "state.json"
    with aioresponses() as m:
        _mock_table(m, total=30, page_size=10)
        async with _conn(page_size=10) as conn:
            got = [
                r
                async for r in conn.aget_records(
                    "incident", fields=["sys_id"], checkpoint=FileCheckpoint(state)
                )
            ]
    assert len(got) == 30


@pytest.mark.asyncio
async def test_a_completed_run_clears_its_own_state(tmp_path: Path) -> None:
    """Otherwise the next run resumes a finished job and returns nothing."""
    state = tmp_path / "state.json"
    with aioresponses() as m:
        _mock_table(m, total=30, page_size=10)
        async with _conn(page_size=10) as conn:
            async for _ in conn.aget_records(
                "incident", fields=["sys_id"], checkpoint=FileCheckpoint(state)
            ):
                pass
    assert not state.exists()


# ---------------------------------------------------------------------------
# Resuming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_interrupted_run_leaves_state_behind(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    with aioresponses() as m:
        _mock_table(m, total=50, page_size=10)
        async with _conn(page_size=10) as conn:
            stream = conn.aget_records(
                "incident", fields=["sys_id"], checkpoint=FileCheckpoint(state)
            )
            seen = 0
            async for _ in stream:
                seen += 1
                if seen >= 12:
                    await stream.aclose()
                    break

    assert state.exists(), "an interrupted async run must record its progress"
    payload = json.loads(state.read_text())
    assert payload["state"]["completed_offsets"], "no page was recorded as done"


@pytest.mark.asyncio
async def test_resuming_skips_the_pages_already_done(tmp_path: Path) -> None:
    """The point of the feature. The second leg must not refetch what the first
    leg already handed over."""
    state = tmp_path / "state.json"
    FileCheckpoint(state).save(
        _fingerprint_for(page_size=10),
        {"completed_offsets": [0, 10, 20]},
    )

    with aioresponses() as m:
        m.get(STATS_RE, payload={"result": {"stats": {"count": "50"}}}, repeat=True)
        m.get(TABLE_RE, payload={"result": _rows(30, 10)})
        m.get(TABLE_RE, payload={"result": _rows(40, 10)})
        async with _conn(page_size=10) as conn:
            got = [
                r
                async for r in conn.aget_records(
                    "incident", fields=["sys_id"], checkpoint=FileCheckpoint(state)
                )
            ]

    assert len(got) == 20, "resume refetched pages that were already complete"


@pytest.mark.asyncio
async def test_a_checkpoint_from_a_different_extraction_is_refused(tmp_path: Path) -> None:
    """A state file says nothing about which sweep wrote it. Reading one back
    against a different table stitches two result sets into one output."""
    state = tmp_path / "state.json"
    FileCheckpoint(state).save("some-other-run", {"completed_offsets": [0]})

    with aioresponses() as m:
        _mock_table(m, total=20, page_size=10)
        async with _conn(page_size=10) as conn:
            with pytest.raises(SnowConnectionError, match="different extraction"):
                async for _ in conn.aget_records(
                    "incident", fields=["sys_id"], checkpoint=FileCheckpoint(state)
                ):
                    pass


@pytest.mark.asyncio
async def test_aconcurrent_get_records_takes_a_checkpoint_too(tmp_path: Path) -> None:
    """It is the same method under the name a sync user reaches for, so the
    argument has to be there as well."""
    state = tmp_path / "state.json"
    with aioresponses() as m:
        _mock_table(m, total=20, page_size=10)
        async with _conn(page_size=10) as conn:
            got = [
                r
                async for r in conn.aconcurrent_get_records(
                    "incident", fields=["sys_id"], checkpoint=FileCheckpoint(state)
                )
            ]
    assert len(got) == 20


def _fingerprint_for(page_size: int) -> str:
    """The fingerprint the implementation must produce for this run.

    Written out rather than imported blind so the test fails if the recipe
    changes, since a silently changed fingerprint would make every existing
    checkpoint unresumable.
    """
    from snowloader.checkpoints import fingerprint

    return fingerprint(
        table="incident",
        query="ORDERBYsys_created_on^ORDERBYsys_id",
        page_size=page_size,
        mode="offset",
        fields=["sys_id"],
    )
