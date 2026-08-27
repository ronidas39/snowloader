"""Tests for deterministic pagination ordering.

Offset pagination is only safe when the sort key is unique. ServiceNow does
not guarantee a stable order inside a tie, so paging over a non-unique column
(such as ``sys_created_on``) can return some rows twice and skip others while
the total count still reconciles.

These tests pin the ordering contract: every paginated request must end its
ORDERBY chain with ``sys_id``, on both the sync and async paths, and the
chain must stay configurable.

Author: Roni Das
"""

from __future__ import annotations

import re
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


def _sent_query(rsps: responses.RequestsMock) -> str:
    """Return the sysparm_query of the first table call recorded."""
    for call in rsps.calls:
        if "/api/now/table/" in call.request.url:
            return str(call.request.params["sysparm_query"])
    raise AssertionError("No table request was recorded")


# ---------------------------------------------------------------------------
# Default ordering
# ---------------------------------------------------------------------------


def test_get_records_terminates_order_chain_with_sys_id() -> None:
    """The default order must keep the chronological intent but add a unique
    tiebreak, so a page boundary landing inside a tied timestamp group is
    still deterministic."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn(page_size=100)
        try:
            list(conn.get_records("incident"))
        finally:
            conn.close()

        assert _sent_query(rsps) == "ORDERBYsys_created_on^ORDERBYsys_id"


def test_concurrent_get_records_terminates_order_chain_with_sys_id() -> None:
    """The threaded paginator splits work by offset, so it needs the same
    deterministic order as the sequential path."""
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
            json={"result": [{"sys_id": "a"}, {"sys_id": "b"}, {"sys_id": "c"}]},
            status=200,
        )

        conn = _conn(page_size=100)
        try:
            list(conn.concurrent_get_records("incident", max_workers=2))
        finally:
            conn.close()

        assert _sent_query(rsps) == "ORDERBYsys_created_on^ORDERBYsys_id"


def test_user_query_keeps_precedence_over_default_order() -> None:
    """The caller's own query still comes first, so their filters and any
    ORDERBY they supply take precedence. Ours only appends a tiebreak."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn()
        try:
            list(conn.get_records("incident", query="active=true"))
        finally:
            conn.close()

        assert _sent_query(rsps) == "active=true^ORDERBYsys_created_on^ORDERBYsys_id"


def test_since_filter_precedes_order_clause() -> None:
    """A delta-sync cutoff is a filter, so it must sit before the ORDERBY
    chain, not after it."""
    from datetime import datetime

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn()
        try:
            list(conn.get_records("incident", since=datetime(2026, 1, 1, 12, 0, 0)))
        finally:
            conn.close()

        assert _sent_query(rsps) == (
            "sys_updated_on>2026-01-01 12:00:00^ORDERBYsys_created_on^ORDERBYsys_id"
        )


# ---------------------------------------------------------------------------
# Configurable ordering
# ---------------------------------------------------------------------------


def test_order_by_single_field_gets_sys_id_tiebreak() -> None:
    """A caller who picks their own sort column still gets a unique tiebreak
    appended, because the loss mode is identical for any non-unique column."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn(order_by="priority")
        try:
            list(conn.get_records("incident"))
        finally:
            conn.close()

        assert _sent_query(rsps) == "ORDERBYpriority^ORDERBYsys_id"


def test_order_by_sys_id_alone_is_not_duplicated() -> None:
    """sys_id is already unique, so no tiebreak should be appended to it."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn(order_by="sys_id")
        try:
            list(conn.get_records("incident"))
        finally:
            conn.close()

        assert _sent_query(rsps) == "ORDERBYsys_id"


def test_order_by_accepts_a_sequence_of_fields() -> None:
    """Multi-column sorts are expressed as one ORDERBY clause per column."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn(order_by=["category", "priority"])
        try:
            list(conn.get_records("incident"))
        finally:
            conn.close()

        assert _sent_query(rsps) == "ORDERBYcategory^ORDERBYpriority^ORDERBYsys_id"


def test_order_by_passes_through_explicit_desc_clauses() -> None:
    """A caller who writes the ServiceNow clause themselves (to get a
    descending sort) must have it forwarded untouched."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn(order_by="ORDERBYDESCsys_created_on")
        try:
            list(conn.get_records("incident"))
        finally:
            conn.close()

        assert _sent_query(rsps) == "ORDERBYDESCsys_created_on^ORDERBYsys_id"


def test_order_by_desc_on_sys_id_is_recognised_as_unique() -> None:
    """A descending sys_id sort is still unique, so no tiebreak is needed."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn(order_by="ORDERBYDESCsys_id")
        try:
            list(conn.get_records("incident"))
        finally:
            conn.close()

        assert _sent_query(rsps) == "ORDERBYDESCsys_id"


def test_order_by_none_disables_ordering_entirely() -> None:
    """An explicit opt-out leaves the query untouched, for callers who know
    what they are doing and want the raw table order."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn(order_by=None)
        try:
            list(conn.get_records("incident", query="active=true"))
        finally:
            conn.close()

        assert _sent_query(rsps) == "active=true"


def test_order_by_none_with_no_query_sends_no_sysparm_query() -> None:
    """With ordering off and no filter there is nothing to send at all."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn(order_by=None)
        try:
            list(conn.get_records("incident"))
        finally:
            conn.close()

        table_calls = [c for c in rsps.calls if "/api/now/table/" in c.request.url]
        assert "sysparm_query" not in table_calls[0].request.params


def test_order_by_rejects_an_empty_string() -> None:
    """An empty order_by is a mistake, not an opt-out. Use None for that."""
    with pytest.raises(SnowConnectionError):
        _conn(order_by="   ")


def test_order_by_rejects_an_empty_sequence() -> None:
    """Same reasoning as the empty string: fail loudly instead of silently
    paginating without a sort key."""
    with pytest.raises(SnowConnectionError):
        _conn(order_by=[])


# ---------------------------------------------------------------------------
# Regression: the tie-driven loss this ordering exists to prevent
# ---------------------------------------------------------------------------


def _tied_table(rows: int, distinct_timestamps: int) -> list[dict[str, str]]:
    """Build rows that share a small number of sys_created_on values."""
    return [
        {
            "sys_id": f"{i:032x}",
            "sys_created_on": f"2026-01-01 00:{i % distinct_timestamps:02d}:00",
        }
        for i in range(rows)
    ]


def test_offset_paging_over_tied_timestamps_loses_no_rows() -> None:
    """Sweep a table whose sort column has heavy ties and assert the sweep
    returns every distinct sys_id exactly once.

    The mock server sorts by whatever ORDERBY chain it is given. When the
    chain is not unique it emulates ServiceNow's freedom to reorder inside a
    tied group, which is what makes offset paging lose rows. The library must
    send a chain that removes that freedom.
    """
    rows = _tied_table(rows=120, distinct_timestamps=6)
    page_size = 25

    def paginate(request: Any) -> tuple[int, dict[str, str], str]:
        import json as _json

        params = dict(request.params)
        query = params.get("sysparm_query", "")
        offset = int(params.get("sysparm_offset", "0"))
        limit = int(params.get("sysparm_limit", "10"))

        order_fields = [
            clause.replace("ORDERBYDESC", "").replace("ORDERBY", "")
            for clause in query.split("^")
            if clause.startswith("ORDERBY")
        ]

        if "sys_id" in order_fields:
            ordered = sorted(rows, key=lambda r: tuple(r[f] for f in order_fields))
        else:
            # Non-unique sort: rows inside a tied group come back in an order
            # the server is free to change between requests. Reversing the
            # tied groups on every other page reproduces exactly that.
            ordered = sorted(rows, key=lambda r: tuple(r[f] for f in order_fields))
            if offset // limit % 2 == 1:
                ordered = sorted(
                    ordered,
                    key=lambda r: tuple(r[f] for f in order_fields),
                    reverse=False,
                )
                ordered = list(reversed(ordered))
                ordered = sorted(ordered, key=lambda r: tuple(r[f] for f in order_fields))

        page = ordered[offset : offset + limit]
        return (200, {"Content-Type": "application/json"}, _json.dumps({"result": page}))

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_callback(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/cmdb_ci(\?.*)?$"),
            callback=paginate,
            content_type="application/json",
        )

        conn = _conn(page_size=page_size)
        try:
            returned = list(conn.get_records("cmdb_ci"))
        finally:
            conn.close()

    distinct = {r["sys_id"] for r in returned}
    assert len(returned) == len(rows), "sweep returned the wrong number of rows"
    assert len(distinct) == len(rows), "sweep lost rows to a tied sort column"


# ---------------------------------------------------------------------------
# Chains supplied as one string
# ---------------------------------------------------------------------------


def test_order_by_accepts_a_whole_chain_as_one_string() -> None:
    """Somebody who already knows the encoding will write the chain out. It
    must be split, not treated as one opaque column name, otherwise the
    sys_id check cannot see what is in it."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn(order_by="ORDERBYcategory^ORDERBYpriority")
        try:
            list(conn.get_records("incident"))
        finally:
            conn.close()

        assert _sent_query(rsps) == "ORDERBYcategory^ORDERBYpriority^ORDERBYsys_id"


def test_a_chain_string_already_ending_in_sys_id_gains_nothing() -> None:
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn(order_by="ORDERBYsys_created_on^ORDERBYsys_id")
        try:
            list(conn.get_records("incident"))
        finally:
            conn.close()

        assert _sent_query(rsps) == "ORDERBYsys_created_on^ORDERBYsys_id"


def test_a_repeated_column_still_gets_the_unique_tiebreak() -> None:
    """Sorting twice on the same non-unique column is still not unique."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": []},
            status=200,
        )

        conn = _conn(order_by="ORDERBYsys_created_on^ORDERBYsys_created_on")
        try:
            list(conn.get_records("incident"))
        finally:
            conn.close()

        assert _sent_query(rsps).endswith("^ORDERBYsys_id")
