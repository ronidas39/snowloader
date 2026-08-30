"""Tests for resumable extractions.

A long extraction that dies at 90 percent should not start again from zero. A
checkpoint writes down where the run had got to, so restarting the same call
continues instead of repeating.

The hazard a checkpoint introduces is resuming into the wrong dataset: a state
file left over from a different table, query or page size will happily be read
back and produce a corpus that is part one thing and part another. Every test
about fingerprints below is about refusing that.

Author: Roni Das
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import responses

from snowloader import FileCheckpoint, SnowConnection
from snowloader.exceptions import SnowConnectionError

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"
STATS_API = f"{BASE_URL}/api/now/stats"
INCIDENT = re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$")


def _conn(**overrides: Any) -> SnowConnection:
    kwargs: dict[str, Any] = {
        "instance_url": BASE_URL,
        "username": "admin",
        "password": "secret",
        "page_size": 10,
    }
    kwargs.update(overrides)
    return SnowConnection(**kwargs)


def _rows(start: int, count: int) -> list[dict[str, str]]:
    return [{"sys_id": f"{i:032x}", "number": f"INC{i:07d}"} for i in range(start, start + count)]


# ---------------------------------------------------------------------------
# FileCheckpoint on its own
# ---------------------------------------------------------------------------


def test_file_checkpoint_round_trips_state(tmp_path: Path) -> None:
    cp = FileCheckpoint(tmp_path / "run.json")
    assert cp.load("fp-1") is None
    cp.save("fp-1", {"cursor": "abc"})
    assert cp.load("fp-1") == {"cursor": "abc"}


def test_file_checkpoint_refuses_state_from_a_different_run(tmp_path: Path) -> None:
    """A file written for one query must not be read back for another."""
    cp = FileCheckpoint(tmp_path / "run.json")
    cp.save("fp-1", {"cursor": "abc"})
    with pytest.raises(SnowConnectionError, match="different"):
        cp.load("fp-2")


def test_file_checkpoint_clear_removes_the_file(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    cp = FileCheckpoint(path)
    cp.save("fp-1", {"cursor": "abc"})
    assert path.exists()
    cp.clear()
    assert not path.exists()
    assert cp.load("fp-1") is None


def test_file_checkpoint_survives_a_corrupt_file(tmp_path: Path) -> None:
    """A half-written file from a hard kill should not stop the next run."""
    path = tmp_path / "run.json"
    path.write_text('{"fingerprint": "fp-1", "state": {"cur')
    assert FileCheckpoint(path).load("fp-1") is None


def test_file_checkpoint_writes_atomically(tmp_path: Path) -> None:
    """Saving must not leave a truncated file if the process dies mid-write."""
    path = tmp_path / "run.json"
    cp = FileCheckpoint(path)
    cp.save("fp-1", {"cursor": "a" * 5000})
    payload = json.loads(path.read_text())
    assert payload["state"]["cursor"] == "a" * 5000
    assert not list(tmp_path.glob("*.tmp"))


# ---------------------------------------------------------------------------
# Resuming a keyset read
# ---------------------------------------------------------------------------


@pytest.mark.replaying_mocks
def test_an_unfinished_keyset_run_records_its_cursor(tmp_path: Path) -> None:
    """State is written once a page is complete, not once a record is handed
    over, so the position always names a page boundary."""
    path = tmp_path / "run.json"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 10)}, status=200)
        conn = _conn(page_size=10)
        try:
            stream = conn.get_records("incident", keyset=True, checkpoint=FileCheckpoint(path))
            [next(stream) for _ in range(10)]  # one whole page
            next(stream)  # forces the save, then starts page two
            stream.close()
        finally:
            conn.close()

    saved = json.loads(path.read_text())["state"]
    assert saved["cursor"] == f"{9:032x}"


def test_a_finished_keyset_run_clears_its_checkpoint(tmp_path: Path) -> None:
    """A completed run leaves nothing behind, so the next one starts clean."""
    path = tmp_path / "run.json"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 4)}, status=200)
        conn = _conn(page_size=10)
        try:
            list(conn.get_records("incident", keyset=True, checkpoint=FileCheckpoint(path)))
        finally:
            conn.close()

    assert not path.exists()


def test_an_interrupted_keyset_run_resumes_from_its_cursor(tmp_path: Path) -> None:
    """The whole point. Stop after two pages, restart, and the third request
    asks for the rows after the last one already delivered."""
    path = tmp_path / "run.json"
    pages = {0: _rows(0, 10), 1: _rows(10, 10), 2: _rows(20, 4)}
    served: list[str] = []

    def paginate(request: Any) -> tuple[int, dict[str, str], str]:
        from urllib.parse import parse_qs, urlparse

        q = parse_qs(urlparse(request.url).query).get("sysparm_query", [""])[0]
        served.append(q)
        if "sys_id>" not in q:
            body = pages[0]
        elif f"{9:032x}" in q:
            body = pages[1]
        elif f"{19:032x}" in q:
            body = pages[2]
        else:
            # Past the last row. A real instance returns an empty page here,
            # and a sweep needs that to know it has reached the end.
            body = []
        import json as _json

        return (200, {"Content-Type": "application/json"}, _json.dumps({"result": body}))

    # First run: consume two pages then walk away.
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_callback(
            responses.GET, INCIDENT, callback=paginate, content_type="application/json"
        )
        conn = _conn(page_size=10)
        try:
            stream = conn.get_records("incident", keyset=True, checkpoint=FileCheckpoint(path))
            first = [next(stream) for _ in range(20)]
            stream.close()
        finally:
            conn.close()

    assert len(first) == 20
    assert path.exists(), "an unfinished run must leave its position behind"

    # Second run: same call, and it must not start over.
    served.clear()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_callback(
            responses.GET, INCIDENT, callback=paginate, content_type="application/json"
        )
        conn = _conn(page_size=10)
        try:
            rest = list(conn.get_records("incident", keyset=True, checkpoint=FileCheckpoint(path)))
        finally:
            conn.close()

    # It resumes from the last page it finished, not from the last record it
    # handed over. The generator is suspended at that final yield when the
    # consumer walks away, so the save for the page in flight never runs.
    # That re-delivers page two and costs ten duplicates, which is the right
    # way round: repeating a page is recoverable, losing one is not.
    assert served[0].startswith(f"sys_id>{9:032x}"), served[0]
    assert len(rest) == 14
    ids = {r["sys_id"] for r in rest}
    assert {f"{i:032x}" for i in range(10, 24)} == ids


@pytest.mark.replaying_mocks
def test_resuming_with_a_different_query_is_refused(tmp_path: Path) -> None:
    """State from one extraction must not be applied to another."""
    path = tmp_path / "run.json"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 10)}, status=200)
        conn = _conn(page_size=10)
        try:
            stream = conn.get_records(
                "incident", query="active=true", keyset=True, checkpoint=FileCheckpoint(path)
            )
            [next(stream) for _ in range(11)]  # a whole page, plus one
            stream.close()
        finally:
            conn.close()

    conn = _conn(page_size=10)
    try:
        with pytest.raises(SnowConnectionError, match="different"):
            list(
                conn.get_records(
                    "incident", query="active=false", keyset=True, checkpoint=FileCheckpoint(path)
                )
            )
    finally:
        conn.close()


@pytest.mark.replaying_mocks
def test_resuming_with_a_different_page_size_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 10)}, status=200)
        conn = _conn(page_size=10)
        try:
            stream = conn.get_records("incident", keyset=True, checkpoint=FileCheckpoint(path))
            [next(stream) for _ in range(11)]  # a whole page, plus one
            stream.close()
        finally:
            conn.close()

    conn = _conn(page_size=25)
    try:
        with pytest.raises(SnowConnectionError, match="different"):
            list(conn.get_records("incident", keyset=True, checkpoint=FileCheckpoint(path)))
    finally:
        conn.close()


def test_a_checkpoint_needs_keyset_on_the_sequential_path(tmp_path: Path) -> None:
    """Plain offset paging has no position worth writing down that survives a
    reordering, so say so rather than pretending to resume."""
    conn = _conn()
    try:
        with pytest.raises(SnowConnectionError, match="keyset"):
            list(conn.get_records("incident", checkpoint=FileCheckpoint(tmp_path / "r.json")))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Resuming a threaded read
# ---------------------------------------------------------------------------


@pytest.mark.replaying_mocks
def test_threaded_run_resumes_only_the_offsets_it_did_not_finish(tmp_path: Path) -> None:
    """The threaded paginator completes pages out of order, so a single last
    offset is not enough. It records the set it actually finished."""
    path = tmp_path / "run.json"
    cp = FileCheckpoint(path)
    cp.save(
        cp.fingerprint(
            table="incident",
            query="ORDERBYsys_created_on^ORDERBYsys_id",
            page_size=10,
            mode="offset",
        ),
        {"completed_offsets": [0, 20]},
    )
    asked: list[str] = []

    def paginate(request: Any) -> tuple[int, dict[str, str], str]:
        import json as _json
        from urllib.parse import parse_qs, urlparse

        off = parse_qs(urlparse(request.url).query).get("sysparm_offset", ["0"])[0]
        asked.append(off)
        return (
            200,
            {"Content-Type": "application/json"},
            _json.dumps({"result": _rows(int(off), 10)}),
        )

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "40"}}},
            status=200,
        )
        rsps.add_callback(
            responses.GET, INCIDENT, callback=paginate, content_type="application/json"
        )
        conn = _conn(page_size=10)
        try:
            records = list(
                conn.concurrent_get_records(
                    "incident", max_workers=2, checkpoint=FileCheckpoint(path)
                )
            )
        finally:
            conn.close()

    assert sorted(asked) == ["10", "30"], asked
    assert len(records) == 20
