"""Tests for RelationshipLoader.

CMDBLoader(include_relationships=True) issues two queries per CI, which is
fine for a few hundred CIs and impossible for fifty thousand. Sweeping
cmdb_rel_ci once gives the same edges in one read, and every edge already
carries both halves of parent, child and type, so nothing needs resolving
afterwards.

Author: Roni Das
"""

from __future__ import annotations

import re
from typing import Any

import responses

from snowloader import RelationshipLoader, SnowConnection

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"
STATS_API = f"{BASE_URL}/api/now/stats"

PARENT_ID = "0c5f3cece1b12010f877971dea0b1449"
CHILD_ID = "b297b0982f4f831020bad7ca6fa4e327"
TYPE_ID = "1a9cb166f1571100a92eb60da2bce5c5"
REL_ID = "3e5f3cece1b12010f877971dea0b14aa"


def _conn(**overrides: Any) -> SnowConnection:
    kwargs: dict[str, Any] = {
        "instance_url": BASE_URL,
        "username": "admin",
        "password": "secret",
        "page_size": 10,
        "display_value": "all",
    }
    kwargs.update(overrides)
    return SnowConnection(**kwargs)


def _edge(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "sys_id": {"display_value": REL_ID, "value": REL_ID},
        "parent": {"display_value": "PROD-DB-01", "value": PARENT_ID},
        "child": {"display_value": "billing-app", "value": CHILD_ID},
        "type": {"display_value": "Depends on::Used by", "value": TYPE_ID},
    }
    record.update(overrides)
    return record


def _load(records: list[dict[str, Any]], **loader_kwargs: Any) -> list[Any]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/cmdb_rel_ci",
            json={"result": {"stats": {"count": str(len(records))}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/cmdb_rel_ci(\?.*)?$"),
            json={"result": records},
            status=200,
        )
        conn = _conn()
        try:
            return RelationshipLoader(conn, **loader_kwargs).load()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def test_relationship_loader_sweeps_cmdb_rel_ci() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/cmdb_rel_ci(\?.*)?$"),
            json={"result": []},
            status=200,
        )
        conn = _conn()
        try:
            loader = RelationshipLoader(conn)
            loader.load()
        finally:
            conn.close()

        assert loader.table == "cmdb_rel_ci"
        assert any("/api/now/table/cmdb_rel_ci" in c.request.url for c in rsps.calls)


def test_one_document_per_edge() -> None:
    docs = _load([_edge(), _edge(sys_id={"display_value": "x" * 32, "value": "x" * 32})])
    assert len(docs) == 2


# ---------------------------------------------------------------------------
# Both halves, which is the entire point
# ---------------------------------------------------------------------------


def test_edge_metadata_carries_both_endpoints_as_sys_ids() -> None:
    metadata = _load([_edge()])[0].metadata
    assert metadata["parent_sys_id"] == PARENT_ID
    assert metadata["child_sys_id"] == CHILD_ID


def test_edge_metadata_carries_readable_endpoint_names() -> None:
    metadata = _load([_edge()])[0].metadata
    assert metadata["parent"] == "PROD-DB-01"
    assert metadata["child"] == "billing-app"


def test_edge_metadata_carries_the_relationship_type_both_ways() -> None:
    metadata = _load([_edge()])[0].metadata
    assert metadata["type"] == "Depends on::Used by"
    assert metadata["type_sys_id"] == TYPE_ID


def test_edge_sys_id_is_a_plain_string() -> None:
    assert _load([_edge()])[0].metadata["sys_id"] == REL_ID


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------


def test_page_content_reads_as_a_directed_edge() -> None:
    content = _load([_edge()])[0].page_content
    assert "PROD-DB-01" in content
    assert "billing-app" in content
    assert "Depends on::Used by" in content


def test_an_edge_with_a_missing_endpoint_still_loads() -> None:
    """A dangling relationship is data worth seeing, not a reason to crash."""
    docs = _load([_edge(child={"display_value": "", "value": ""})])
    assert len(docs) == 1
    assert docs[0].metadata["child"] == ""


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_a_caller_query_reaches_the_request() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/cmdb_rel_ci(\?.*)?$"),
            json={"result": []},
            status=200,
        )
        conn = _conn()
        try:
            RelationshipLoader(conn, query=f"parent={PARENT_ID}").load()
        finally:
            conn.close()

        sent = str(rsps.calls[0].request.params["sysparm_query"])
        assert sent.startswith(f"parent={PARENT_ID}")


def test_relationship_loader_supports_the_threaded_path() -> None:
    docs = _load([_edge()])
    assert docs
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/cmdb_rel_ci",
            json={"result": {"stats": {"count": "1"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/cmdb_rel_ci(\?.*)?$"),
            json={"result": [_edge()]},
            status=200,
        )
        conn = _conn()
        try:
            threaded = RelationshipLoader(conn).concurrent_load(max_workers=2)
        finally:
            conn.close()

    assert threaded[0].metadata["parent_sys_id"] == PARENT_ID
