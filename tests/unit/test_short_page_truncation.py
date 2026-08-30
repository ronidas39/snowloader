"""A page shorter than requested does not mean the table ended.

ServiceNow applies read ACLs after it has selected a page, so a request for
100 rows can come back with 40 while thousands remain. Treating that as the
end of the table truncates the sweep silently, and the amount lost depends on
where the filtered rows happen to fall, which is why the same table returned
769 rows at page size 100 and 969 at page size 500 while the instance reported
6,456.

Measured on a developer instance against sys_db_object: the old rule returned
969 rows, walking until an empty page returned 6,419, and four short pages sat
in between. Nothing warned, because a short page was the documented end
condition.

Only an empty page ends a sweep now. That costs one extra request per run.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import responses

from snowloader import SnowConnection, SweepIncompleteError

BASE_URL = "https://test.service-now.com"
TABLE_RE = re.compile(rf"^{re.escape(BASE_URL)}/api/now/table/incident(\?.*)?$")
STATS_RE = re.compile(rf"^{re.escape(BASE_URL)}/api/now/stats/incident(\?.*)?$")


def _rows(start: int, count: int) -> list[dict[str, str]]:
    return [{"sys_id": f"{i:032x}", "number": f"INC{i:07d}"} for i in range(start, start + count)]


def _conn(**kwargs: Any) -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret", **kwargs)


def test_a_short_page_does_not_end_the_sweep() -> None:
    """The bug. A page filtered by ACLs comes back short with more to follow."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 100)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(100, 40)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(200, 100)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": []}, status=200)
        with _conn(page_size=100) as conn:
            got = list(conn.get_records("incident", fields=["sys_id"]))

    assert len(got) == 240, f"stopped early at {len(got)}, the short page ended the sweep"


def test_only_an_empty_page_ends_the_sweep() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 100)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": []}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(100, 100)}, status=200)
        with _conn(page_size=100) as conn:
            got = list(conn.get_records("incident", fields=["sys_id"]))

    assert len(got) == 100


def test_several_consecutive_short_pages_are_all_followed() -> None:
    """ACL filtering is not evenly spread. A run of short pages is normal."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        for start, n in ((0, 20), (100, 5), (200, 60), (300, 1), (400, 100)):
            rsps.add(responses.GET, TABLE_RE, json={"result": _rows(start, n)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": []}, status=200)
        with _conn(page_size=100) as conn:
            got = list(conn.get_records("incident", fields=["sys_id"]))

    assert len(got) == 186


def test_a_limit_still_stops_without_an_extra_request() -> None:
    """A capped sweep knows its own end, so it must not pay for the empty page."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 10)}, status=200)
        with _conn(page_size=100) as conn:
            got = list(conn.get_records("incident", fields=["sys_id"], limit=10))
        calls = [c for c in rsps.calls if "/api/now/table/" in c.request.url]

    assert len(got) == 10
    assert len(calls) == 1, f"a limited sweep made {len(calls)} requests"


def test_keyset_also_follows_short_pages() -> None:
    """Keyset pages on a cursor, and the same ACL filtering applies to it."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 100)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(100, 30)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(130, 100)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": []}, status=200)
        with _conn(page_size=100) as conn:
            got = list(conn.get_records("incident", fields=["sys_id"], keyset=True))

    assert len(got) == 230


def test_verify_still_reports_rows_the_instance_will_not_return() -> None:
    """Even walking to the end, ACLs can hide rows the count includes. That is
    a real gap and must be reported rather than smoothed over."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, STATS_RE, json={"result": {"stats": {"count": "500"}}}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": _rows(0, 100)}, status=200)
        rsps.add(responses.GET, TABLE_RE, json={"result": []}, status=200)
        with _conn(page_size=100) as conn, pytest.raises(SweepIncompleteError) as exc:
            list(conn.get_records("incident", fields=["sys_id"], verify=True))

    assert exc.value.report.missing == 400


def test_an_empty_first_page_returns_nothing_quietly() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, TABLE_RE, json={"result": []}, status=200)
        with _conn(page_size=100) as conn:
            assert list(conn.get_records("incident", fields=["sys_id"])) == []
