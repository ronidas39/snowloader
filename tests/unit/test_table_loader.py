"""Tests for the generic TableLoader.

snowloader ships a loader for six tables. ServiceNow has thousands. TableLoader
covers the rest without asking anyone to subclass BaseSnowLoader, which is what
people were doing instead.

Author: Roni Das
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import responses

from snowloader import SnowConnection, SnowConnectionError, TableLoader

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"

TASK_ID = "1f2e3d4c5b6a79880123456789abcdef"
GROUP_ID = "d625dccec0a8016700a222a0f7900d06"


def _conn(**overrides: Any) -> SnowConnection:
    kwargs: dict[str, Any] = {
        "instance_url": BASE_URL,
        "username": "admin",
        "password": "secret",
        "page_size": 10,
    }
    kwargs.update(overrides)
    return SnowConnection(**kwargs)


def _load(table: str, records: list[dict[str, Any]], **loader_kwargs: Any) -> list[Any]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/{table}(\?.*)?$"),
            json={"result": records},
            status=200,
        )
        conn = _conn()
        try:
            return TableLoader(conn, table=table, **loader_kwargs).load()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_table_loader_requires_a_table_name() -> None:
    conn = _conn()
    try:
        with pytest.raises(SnowConnectionError):
            TableLoader(conn, table="")
    finally:
        conn.close()


def test_table_loader_reads_the_table_it_was_given() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/sc_task(\?.*)?$"),
            json={"result": []},
            status=200,
        )
        conn = _conn()
        try:
            loader = TableLoader(conn, table="sc_task")
            loader.load()
        finally:
            conn.close()

        assert loader.table == "sc_task"
        assert any("/api/now/table/sc_task" in c.request.url for c in rsps.calls)


# ---------------------------------------------------------------------------
# Content assembly
# ---------------------------------------------------------------------------


def test_explicit_content_fields_are_joined_in_order() -> None:
    docs = _load(
        "sc_task",
        [{"sys_id": TASK_ID, "short_description": "Order a laptop", "description": "16GB, macOS"}],
        content_fields=["short_description", "description"],
    )
    assert docs[0].page_content == "Order a laptop\n16GB, macOS"


def test_content_fields_default_to_whatever_text_the_table_has() -> None:
    """Nobody knows the text columns of an arbitrary table off the top of
    their head, so the loader picks from the usual candidates present on the
    record rather than returning an empty document."""
    docs = _load("sys_user_group", [{"sys_id": GROUP_ID, "name": "Service Desk"}])
    assert docs[0].page_content == "Service Desk"


def test_a_record_with_no_recognisable_text_still_produces_a_document() -> None:
    """Metadata is the point for a link table. Empty content is fine; a
    dropped record is not."""
    docs = _load("cmdb_rel_type", [{"sys_id": TASK_ID, "sys_created_by": "admin"}])
    assert len(docs) == 1
    assert docs[0].page_content == ""
    assert docs[0].metadata["sys_id"] == TASK_ID


def test_missing_content_field_is_skipped_not_rendered_as_none() -> None:
    docs = _load(
        "sc_task",
        [{"sys_id": TASK_ID, "short_description": "Order a laptop"}],
        content_fields=["short_description", "description"],
    )
    assert docs[0].page_content == "Order a laptop"


def test_content_fields_read_the_label_half_of_a_reference() -> None:
    docs = _load(
        "sc_task",
        [
            {
                "sys_id": TASK_ID,
                "short_description": {"display_value": "Order a laptop", "value": "Order a laptop"},
            }
        ],
        content_fields=["short_description"],
    )
    assert docs[0].page_content == "Order a laptop"


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_metadata_carries_the_table_and_a_usable_sys_id() -> None:
    docs = _load("sc_task", [{"sys_id": {"display_value": TASK_ID, "value": TASK_ID}}])
    assert docs[0].metadata["table"] == "sc_task"
    assert docs[0].metadata["sys_id"] == TASK_ID


def test_metadata_expands_references_like_every_other_loader() -> None:
    docs = _load(
        "sc_task",
        [
            {
                "sys_id": TASK_ID,
                "assignment_group": {"display_value": "Service Desk", "value": GROUP_ID},
            }
        ],
    )
    assert docs[0].metadata["assignment_group"] == "Service Desk"
    assert docs[0].metadata["assignment_group_sys_id"] == GROUP_ID


def test_include_raw_works_on_the_generic_loader_too() -> None:
    docs = _load("sc_task", [{"sys_id": TASK_ID, "state": "1"}], include_raw=True)
    assert docs[0].metadata["raw"] == {"sys_id": TASK_ID, "state": "1"}
