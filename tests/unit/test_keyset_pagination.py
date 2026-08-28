"""Tests for keyset pagination.

Offset pagination asks the instance to walk past every row it is skipping, so
the cost of a page grows with how deep the page is. Keyset pagination asks for
the rows after a remembered position instead, which keeps the cost of a page
flat however far in it is, and makes a run resumable from a single value.

It only works over a unique, ordered column. sys_id is the one ServiceNow
guarantees, so keyset mode sorts on sys_id and pages on ``sys_id>cursor``.

Author: Roni Das
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from snowloader.connection import SnowConnection
from snowloader.exceptions import SnowConnectionError, SweepIncompleteError

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


def _queries(rsps: responses.RequestsMock) -> list[str]:
    out = []
    for call in rsps.calls:
        if "/api/now/table/" not in call.request.url:
            continue
        params = parse_qs(urlparse(call.request.url).query)
        out.append(params.get("sysparm_query", [""])[0])
    return out


def _sent_params(rsps: responses.RequestsMock) -> list[dict[str, list[str]]]:
    return [
        parse_qs(urlparse(c.request.url).query)
        for c in rsps.calls
        if "/api/now/table/" in c.request.url
    ]


# ---------------------------------------------------------------------------
# The query it builds
# ---------------------------------------------------------------------------


def test_keyset_sorts_on_sys_id_alone() -> None:
    """A keyset cursor is a single value, so the order has to be the single
    unique column. Any other sort makes the cursor ambiguous."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": []}, status=200)
        conn = _conn()
        try:
            list(conn.get_records("incident", keyset=True))
        finally:
            conn.close()

        assert _queries(rsps)[0] == "ORDERBYsys_id"


def test_keyset_sends_no_offset() -> None:
    """The whole point is not to make the instance count past skipped rows."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 3)}, status=200)
        conn = _conn(page_size=10)
        try:
            list(conn.get_records("incident", keyset=True))
        finally:
            conn.close()

        assert all("sysparm_offset" not in p for p in _sent_params(rsps))


def test_keyset_advances_the_cursor_past_the_last_row_of_each_page() -> None:
    pages = [_rows(0, 10), _rows(10, 10), _rows(20, 3)]
    served: list[list[dict[str, str]]] = []

    def paginate(request: Any) -> tuple[int, dict[str, str], str]:
        import json as _json

        served.append(pages[len(served)] if len(served) < len(pages) else [])
        return (200, {"Content-Type": "application/json"}, _json.dumps({"result": served[-1]}))

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_callback(
            responses.GET, INCIDENT, callback=paginate, content_type="application/json"
        )
        conn = _conn(page_size=10)
        try:
            records = list(conn.get_records("incident", keyset=True))
        finally:
            conn.close()

        queries = _queries(rsps)
        assert queries[0] == "ORDERBYsys_id"
        assert queries[1] == f"sys_id>{9:032x}^ORDERBYsys_id"
        assert queries[2] == f"sys_id>{19:032x}^ORDERBYsys_id"
        assert len(records) == 23


def test_keyset_keeps_the_caller_filter_in_front_of_the_cursor() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 3)}, status=200)
        conn = _conn(page_size=10)
        try:
            list(conn.get_records("incident", query="active=true", keyset=True))
        finally:
            conn.close()

        assert _queries(rsps)[0] == "active=true^ORDERBYsys_id"


def test_keyset_reads_the_cursor_from_the_display_value_all_shape() -> None:
    """With sysparm_display_value=all every field is a dict, so the cursor has
    to come from the value half rather than from str(dict)."""
    rows = [{"sys_id": {"display_value": f"{i:032x}", "value": f"{i:032x}"}} for i in range(10)]
    calls = {"n": 0}

    def paginate(request: Any) -> tuple[int, dict[str, str], str]:
        import json as _json

        calls["n"] += 1
        body = rows if calls["n"] == 1 else []
        return (200, {"Content-Type": "application/json"}, _json.dumps({"result": body}))

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_callback(
            responses.GET, INCIDENT, callback=paginate, content_type="application/json"
        )
        conn = _conn(page_size=10, display_value="all")
        try:
            list(conn.get_records("incident", keyset=True))
        finally:
            conn.close()

        assert _queries(rsps)[1] == f"sys_id>{9:032x}^ORDERBYsys_id"


# ---------------------------------------------------------------------------
# Termination
# ---------------------------------------------------------------------------


def test_keyset_stops_on_a_short_page() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 4)}, status=200)
        conn = _conn(page_size=10)
        try:
            records = list(conn.get_records("incident", keyset=True))
        finally:
            conn.close()

        assert len(records) == 4
        assert len(_queries(rsps)) == 1


def test_keyset_stops_on_an_empty_table() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": []}, status=200)
        conn = _conn()
        try:
            assert list(conn.get_records("incident", keyset=True)) == []
        finally:
            conn.close()


def test_keyset_stops_rather_than_looping_when_the_cursor_cannot_advance() -> None:
    """A page with no readable sys_id would leave the cursor where it is and
    the same request would repeat for ever. Stop instead."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            INCIDENT,
            json={"result": [{"number": f"INC{i}"} for i in range(10)]},
            status=200,
        )
        conn = _conn(page_size=10)
        try:
            with pytest.raises(SnowConnectionError, match="cursor"):
                list(conn.get_records("incident", keyset=True))
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


def test_keyset_refuses_a_field_list_without_sys_id() -> None:
    """The cursor is read out of the records themselves."""
    conn = _conn()
    try:
        with pytest.raises(SnowConnectionError, match="sys_id"):
            list(conn.get_records("incident", fields=["number"], keyset=True))
    finally:
        conn.close()


def test_keyset_refuses_a_deliberate_custom_sort_order() -> None:
    """A single value cursor only makes sense over the column it sorts by.

    Somebody who asked for priority order and then asked for keyset has asked
    for two things that cannot both happen, so say so rather than quietly
    ignoring one of them.
    """
    conn = _conn(order_by="priority")
    try:
        with pytest.raises(SnowConnectionError, match="order_by"):
            list(conn.get_records("incident", keyset=True))
    finally:
        conn.close()


def test_keyset_accepts_the_default_sort_order() -> None:
    """The default is not a deliberate choice, so keyset just takes over."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 2)}, status=200)
        conn = _conn()  # order_by defaults to sys_created_on
        try:
            list(conn.get_records("incident", keyset=True))
        finally:
            conn.close()

        assert _queries(rsps)[0] == "ORDERBYsys_id"


def test_keyset_accepts_an_explicit_sys_id_sort_order() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 2)}, status=200)
        conn = _conn(order_by="sys_id")
        try:
            list(conn.get_records("incident", keyset=True))
        finally:
            conn.close()

        assert _queries(rsps)[0] == "ORDERBYsys_id"


def test_keyset_is_available_on_the_loader_surface() -> None:
    from snowloader import IncidentLoader

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 2)}, status=200)
        conn = _conn(page_size=10)
        try:
            docs = IncidentLoader(conn).load(keyset=True)
        finally:
            conn.close()

        assert len(docs) == 2
        assert _queries(rsps)[0] == "ORDERBYsys_id"


# ---------------------------------------------------------------------------
# Composes with verification
# ---------------------------------------------------------------------------


def test_keyset_composes_with_verify() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "4"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 4)}, status=200)
        conn = _conn(page_size=10)
        try:
            records = list(conn.get_records("incident", keyset=True, verify=True))
        finally:
            conn.close()

    assert len(records) == 4


def test_keyset_verify_still_raises_when_records_are_missing() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "50"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 4)}, status=200)
        conn = _conn(page_size=10)
        try:
            with pytest.raises(SweepIncompleteError):
                list(conn.get_records("incident", keyset=True, verify=True))
        finally:
            conn.close()
