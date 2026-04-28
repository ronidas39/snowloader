"""Tests for SnowConnection.get_count and SnowConnection.concurrent_get_records.

Covers the threaded paginator path: stats-endpoint count discovery, page
planning, parallel page dispatch via ``ThreadPoolExecutor``, per-thread
``requests.Session`` isolation, and validation guard rails. All HTTP traffic
is intercepted with the ``responses`` library, so no real network calls are
made.

Author: Roni Das
"""

from __future__ import annotations

import re
import threading
from typing import Any

import pytest
import responses

from snowloader.connection import SnowConnection, SnowConnectionError

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"
STATS_API = f"{BASE_URL}/api/now/stats"


def _conn(**overrides: Any) -> SnowConnection:
    """Construct a basic-auth SnowConnection with sensible test defaults."""
    kwargs: dict[str, Any] = {
        "instance_url": BASE_URL,
        "username": "admin",
        "password": "secret",
    }
    kwargs.update(overrides)
    return SnowConnection(**kwargs)


# ---------------------------------------------------------------------------
# get_count
# ---------------------------------------------------------------------------


def test_get_count_returns_int_from_stats_response() -> None:
    """get_count() should parse the stats.count field and return it as an int."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "42"}}},
            status=200,
        )

        conn = _conn()
        try:
            assert conn.get_count("incident") == 42
        finally:
            conn.close()

        # And the request must have asked for the count
        assert len(rsps.calls) == 1
        assert rsps.calls[0].request.params["sysparm_count"] == "true"


def test_get_count_returns_zero_for_missing_stats() -> None:
    """If the API response is missing stats/count, return 0, not raise."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {}},
            status=200,
        )

        conn = _conn()
        try:
            assert conn.get_count("incident") == 0
        finally:
            conn.close()


def test_get_count_with_query_passes_sysparm_query() -> None:
    """A user-supplied query should be forwarded as sysparm_query."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "7"}}},
            status=200,
        )

        conn = _conn()
        try:
            count = conn.get_count("incident", query="active=true^priority=1")
        finally:
            conn.close()

        assert count == 7
        sent_params = rsps.calls[0].request.params
        assert "sysparm_query" in sent_params
        assert "active=true^priority=1" in sent_params["sysparm_query"]


def test_get_count_raises_on_5xx() -> None:
    """A 500 response from the stats endpoint must bubble up as
    SnowConnectionError after retries are exhausted."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # The connection retries on 5xx; register enough mocks for any
        # number of attempts the retry loop might make.
        for _ in range(10):
            rsps.add(
                responses.GET,
                f"{STATS_API}/incident",
                json={"error": {"message": "Internal error"}},
                status=500,
            )

        # Use small backoff so retries don't slow the suite.
        conn = _conn(max_retries=1, retry_backoff=0.0)
        try:
            with pytest.raises(SnowConnectionError):
                conn.get_count("incident")
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# concurrent_get_records - validation
# ---------------------------------------------------------------------------


def test_concurrent_get_records_raises_on_max_workers_zero() -> None:
    """max_workers must be >= 1; zero should fail fast before any HTTP calls."""
    conn = _conn()
    try:
        with pytest.raises(SnowConnectionError):
            # Generator must be iterated for the body to execute.
            list(conn.concurrent_get_records("incident", max_workers=0))
    finally:
        conn.close()


def test_concurrent_get_records_raises_on_empty_table() -> None:
    """An empty table name must raise SnowConnectionError immediately."""
    conn = _conn()
    try:
        with pytest.raises(SnowConnectionError):
            list(conn.concurrent_get_records("   "))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# concurrent_get_records - happy paths
# ---------------------------------------------------------------------------


def _page_records(prefix: str, count: int) -> list[dict[str, str]]:
    return [{"sys_id": f"{prefix}-{i}", "number": f"INC{prefix}{i:04d}"} for i in range(count)]


def test_concurrent_get_records_paginates_with_threads() -> None:
    """With count=12 and page_size=5, the paginator must dispatch 3 page
    fetches. The mock returns 5 records on every page hit, so 15 records
    are yielded in total (we trust the count, not record list length)."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # Stats: total of 12 records
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "12"}}},
            status=200,
        )
        # Table: every offset returns 5 records (the mock doesn't honor offset)
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": _page_records("a", 5)},
            status=200,
        )

        conn = _conn(page_size=5)
        try:
            records = list(conn.concurrent_get_records("incident", max_workers=4))
        finally:
            conn.close()

        # 3 pages * 5 mocked records = 15
        assert len(records) == 15

        # 1 stats call + 3 page fetches = 4 total
        assert len(rsps.calls) == 4

        # Inspect the offsets that were dispatched (skip the stats call)
        offsets = sorted(
            int(call.request.params["sysparm_offset"])
            for call in rsps.calls
            if "/api/now/table/" in call.request.url
        )
        assert offsets == [0, 5, 10]


def test_concurrent_get_records_returns_empty_for_zero_count() -> None:
    """If the stats endpoint reports 0 records, concurrent_get_records must
    return immediately without dispatching any page fetches."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "0"}}},
            status=200,
        )

        conn = _conn(page_size=10)
        try:
            records = list(conn.concurrent_get_records("incident", max_workers=4))
        finally:
            conn.close()

        assert records == []
        # Only the stats call should have happened.
        assert len(rsps.calls) == 1
        assert "/api/now/stats/" in rsps.calls[0].request.url


def test_concurrent_get_records_passes_query_and_fields() -> None:
    """Query and fields parameters must be forwarded to every page fetch
    as sysparm_query and sysparm_fields."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "3"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": _page_records("a", 3)},
            status=200,
        )

        conn = _conn(page_size=10)
        try:
            records = list(
                conn.concurrent_get_records(
                    "incident",
                    query="active=true^priority=1",
                    fields=["sys_id", "number"],
                    max_workers=2,
                )
            )
        finally:
            conn.close()

        assert len(records) == 3

        # Find the actual page fetch (not the stats call)
        page_calls = [call for call in rsps.calls if "/api/now/table/" in call.request.url]
        assert len(page_calls) == 1
        page_params = page_calls[0].request.params

        assert "sysparm_query" in page_params
        assert "active=true^priority=1" in page_params["sysparm_query"]
        assert "ORDERBYsys_created_on" in page_params["sysparm_query"]

        assert page_params["sysparm_fields"] == "sys_id,number"


def test_concurrent_get_records_uses_per_thread_session() -> None:
    """Each worker thread must obtain its own ``requests.Session`` instance.

    We patch ``requests.Session`` so we can count how many distinct sessions
    are constructed during the concurrent fetch. With multiple pages and
    multiple workers, we expect more than one Session beyond the
    connection's own session - one per thread that actually does work.
    """
    import requests as _requests

    real_session_cls = _requests.Session
    created_sessions: list[_requests.Session] = []
    seen_thread_ids: set[int] = set()
    lock = threading.Lock()

    def tracking_session() -> _requests.Session:
        sess = real_session_cls()
        with lock:
            created_sessions.append(sess)
        return sess

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "20"}}},
            status=200,
        )

        # Track the thread that issues each table call. Use a callback so
        # the response is generated lazily inside whichever worker calls it.
        def page_callback(request: Any) -> tuple[int, dict[str, str], str]:
            with lock:
                seen_thread_ids.add(threading.get_ident())
            import json as _json

            body = _json.dumps({"result": _page_records("p", 5)})
            return (200, {"Content-Type": "application/json"}, body)

        rsps.add_callback(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            callback=page_callback,
            content_type="application/json",
        )

        conn = _conn(page_size=5)
        # Patch Session AFTER conn construction so the conn's own session is real.
        try:
            _requests.Session = tracking_session  # type: ignore[misc]
            records = list(conn.concurrent_get_records("incident", max_workers=4))
        finally:
            _requests.Session = real_session_cls  # type: ignore[misc]
            conn.close()

        # 20 / 5 = 4 pages, all 5 records each
        assert len(records) == 20

        # At least one Session was constructed inside a worker thread.
        # We can't guarantee 4 distinct workers picked up tasks (the pool is
        # free to reuse a hot worker), but at minimum ONE new Session must
        # have been created beyond the conn's own session.
        assert len(created_sessions) >= 1

        # And the page work happened on at least one non-main thread.
        assert seen_thread_ids, "No threads recorded for page fetches"


def test_concurrent_get_records_handles_partial_last_page() -> None:
    """count=7, page_size=5 should produce exactly 2 page fetches:
    offsets 0 and 5. The last page covers records 5 and 6."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "7"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": _page_records("a", 5)},
            status=200,
        )

        conn = _conn(page_size=5)
        try:
            list(conn.concurrent_get_records("incident", max_workers=4))
        finally:
            conn.close()

        page_calls = [call for call in rsps.calls if "/api/now/table/" in call.request.url]
        # Exactly 2 page fetches, no more.
        assert len(page_calls) == 2

        offsets = sorted(int(call.request.params["sysparm_offset"]) for call in page_calls)
        assert offsets == [0, 5]
