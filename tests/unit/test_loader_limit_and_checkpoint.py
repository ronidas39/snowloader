"""Tests for capping a loader's output and for resuming one.

Two gaps found by running the end to end suite against a live instance rather
than by reading the code.

The first is ``limit``. There was no way to ask a loader for a few documents.
Every entry point swept the whole table, so the ordinary first thing anyone
does, look at five records to see what the shape is, meant pulling every row of
an incident table that may hold half a million of them.

The second is ``checkpoint`` on the loaders. Resume shipped in 0.4.0 but only
on the raw connection, so the API most people actually use could not do it.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import responses

from snowloader import IncidentLoader, SnowConnection
from snowloader.checkpoints import FileCheckpoint

BASE_URL = "https://test.service-now.com"
TABLE_RE = re.compile(rf"^{re.escape(BASE_URL)}/api/now/table/incident(\?.*)?$")
STATS_RE = re.compile(rf"^{re.escape(BASE_URL)}/api/now/stats/incident(\?.*)?$")


def _rows(start: int, count: int) -> list[dict[str, str]]:
    return [
        {
            "sys_id": f"{i:032x}",
            "number": f"INC{i:07d}",
            "short_description": f"thing {i}",
        }
        for i in range(start, start + count)
    ]


def _conn(**kwargs: Any) -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret", **kwargs)


# ---------------------------------------------------------------------------
# limit
# ---------------------------------------------------------------------------


def test_load_accepts_a_limit() -> None:
    """The gap. Before this, the call raised TypeError."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 100)}, status=200)
        with _conn(page_size=100) as conn:
            docs = IncidentLoader(connection=conn).load(limit=5)
    assert len(docs) == 5


def test_limit_stops_requesting_pages_once_it_is_reached() -> None:
    """A limit that filtered client side would still pull the whole table,
    which is the cost the argument exists to avoid."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        for offset in range(0, 500, 100):
            rsps.add(responses.GET, TABLE_RE, json={"result": _rows(offset, 100)}, status=200)
        with _conn(page_size=100) as conn:
            docs = IncidentLoader(connection=conn).load(limit=10)
        page_requests = [c for c in rsps.calls if "/api/now/table/" in c.request.url]

    assert len(docs) == 10
    assert len(page_requests) == 1, (
        f"asked for 10 records and made {len(page_requests)} page requests"
    )


def test_limit_smaller_than_a_page_asks_for_only_that_many() -> None:
    """No point requesting 100 rows to hand back 3."""
    from urllib.parse import parse_qs, urlparse

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 3)}, status=200)
        with _conn(page_size=100) as conn:
            IncidentLoader(connection=conn).load(limit=3)
        url = [c.request.url for c in rsps.calls if "/api/now/table/" in c.request.url][0]

    assert parse_qs(urlparse(url).query)["sysparm_limit"][0] == "3"


def test_limit_larger_than_the_table_returns_what_exists() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 7)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": []}, status=200)
        with _conn(page_size=100) as conn:
            docs = IncidentLoader(connection=conn).load(limit=1000)
    assert len(docs) == 7


def test_lazy_load_honours_a_limit() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 100)}, status=200)
        with _conn(page_size=100) as conn:
            docs = list(IncidentLoader(connection=conn).lazy_load(limit=4))
    assert len(docs) == 4


def test_get_records_honours_a_limit() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 100)}, status=200)
        with _conn(page_size=100) as conn:
            got = list(conn.get_records("incident", limit=6))
    assert len(got) == 6


def test_a_limit_of_zero_returns_nothing_and_asks_for_nothing() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        with _conn(page_size=100) as conn:
            docs = IncidentLoader(connection=conn).load(limit=0)
        assert not [c for c in rsps.calls if "/api/now/table/" in c.request.url]
    assert docs == []


def test_a_negative_limit_is_refused() -> None:
    """Silently treating it as unlimited would sweep the whole table when the
    caller plainly meant the opposite."""
    from snowloader.exceptions import SnowConnectionError

    with _conn() as conn, pytest.raises(SnowConnectionError, match="limit"):
        list(conn.get_records("incident", limit=-1))


def test_limit_cannot_be_combined_with_verify() -> None:
    """Verification compares what came back against the table count. A
    deliberately capped sweep would always look short, so this pairing can
    only ever produce a false alarm."""
    from snowloader.exceptions import SnowConnectionError

    with _conn() as conn, pytest.raises(SnowConnectionError, match="verify"):
        list(conn.get_records("incident", limit=5, verify=True))


# ---------------------------------------------------------------------------
# checkpoint on the loaders
# ---------------------------------------------------------------------------


def test_lazy_load_accepts_a_checkpoint(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 30)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": []}, status=200)
        with _conn(page_size=30) as conn:
            docs = list(
                IncidentLoader(connection=conn).lazy_load(
                    keyset=True, checkpoint=FileCheckpoint(state)
                )
            )
    assert len(docs) == 30


def test_a_finished_loader_run_clears_its_state(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 30)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": []}, status=200)
        with _conn(page_size=30) as conn:
            IncidentLoader(connection=conn).load(keyset=True, checkpoint=FileCheckpoint(state))
    assert not state.exists()


def test_an_interrupted_loader_run_records_where_it_reached(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 30)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(30, 30)}, status=200)
        with _conn(page_size=30) as conn:
            stream = IncidentLoader(connection=conn).lazy_load(
                keyset=True, checkpoint=FileCheckpoint(state)
            )
            for i, _ in enumerate(stream):
                if i >= 30:
                    stream.close()
                    break
    assert state.exists()


def test_concurrent_load_accepts_a_checkpoint(tmp_path: Path) -> None:
    state = tmp_path / "threaded.json"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, STATS_RE, json={"result": {"stats": {"count": "20"}}}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 20)}, status=200)
        with _conn(page_size=20) as conn:
            docs = IncidentLoader(connection=conn).concurrent_load(
                max_workers=4, checkpoint=FileCheckpoint(state)
            )
    assert len(docs) == 20
