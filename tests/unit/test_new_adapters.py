"""Tests for the adapters added in 0.3.0.

The adapter layer is a thin wrapper by design, so these check the two things
a wrapper can get wrong: that the framework interface is satisfied, and that
constructor arguments reach the underlying loader.

Author: Roni Das
"""

from __future__ import annotations

import re

import pytest
import responses

from snowloader.connection import SnowConnection

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"

PARENT_ID = "0c5f3cece1b12010f877971dea0b1449"
CHILD_ID = "b297b0982f4f831020bad7ca6fa4e327"
TYPE_ID = "1a9cb166f1571100a92eb60da2bce5c5"
REL_ID = "3e5f3cece1b12010f877971dea0b14aa"
TASK_ID = "1f2e3d4c5b6a79880123456789abcdef"

EDGE: dict = {
    "sys_id": {"display_value": REL_ID, "value": REL_ID},
    "parent": {"display_value": "PROD-DB-01", "value": PARENT_ID},
    "child": {"display_value": "billing-app", "value": CHILD_ID},
    "type": {"display_value": "Depends on::Used by", "value": TYPE_ID},
}

TASK: dict = {
    "sys_id": TASK_ID,
    "short_description": "Order a laptop",
    "description": "16GB, macOS",
}


def _conn() -> SnowConnection:
    return SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
        page_size=10,
    )


def _mock(rsps: responses.RequestsMock, table: str, records: list[dict]) -> None:
    rsps.add(
        responses.GET,
        re.compile(rf"^{re.escape(TABLE_API)}/{table}(\?.*)?$"),
        json={"result": records},
        status=200,
    )


# ---------------------------------------------------------------------------
# LangChain
# ---------------------------------------------------------------------------

pytest.importorskip("langchain_core")

from snowloader.adapters.langchain import (  # noqa: E402
    ServiceNowRelationshipLoader,
    ServiceNowTableLoader,
)


def test_langchain_relationship_loader_returns_documents() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _mock(rsps, "cmdb_rel_ci", [EDGE])
        conn = _conn()
        try:
            docs = ServiceNowRelationshipLoader(connection=conn).load()
        finally:
            conn.close()

    assert len(docs) == 1
    assert docs[0].metadata["parent_sys_id"] == PARENT_ID
    assert docs[0].metadata["child_sys_id"] == CHILD_ID


def test_langchain_relationship_loader_lazy_load_is_an_iterator() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _mock(rsps, "cmdb_rel_ci", [EDGE])
        conn = _conn()
        try:
            docs = list(ServiceNowRelationshipLoader(connection=conn).lazy_load())
        finally:
            conn.close()

    assert "PROD-DB-01" in docs[0].page_content


def test_langchain_table_loader_forwards_the_table_argument() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _mock(rsps, "sc_task", [TASK])
        conn = _conn()
        try:
            docs = ServiceNowTableLoader(connection=conn, table="sc_task").load()
        finally:
            conn.close()

        assert any("/api/now/table/sc_task" in c.request.url for c in rsps.calls)

    assert docs[0].metadata["table"] == "sc_task"


def test_langchain_table_loader_forwards_content_fields() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _mock(rsps, "sc_task", [TASK])
        conn = _conn()
        try:
            docs = ServiceNowTableLoader(
                connection=conn,
                table="sc_task",
                content_fields=["description"],
            ).load()
        finally:
            conn.close()

    assert docs[0].page_content == "16GB, macOS"


# ---------------------------------------------------------------------------
# LlamaIndex
# ---------------------------------------------------------------------------

pytest.importorskip("llama_index.core")

from snowloader.adapters.llamaindex import (  # noqa: E402
    ServiceNowRelationshipReader,
    ServiceNowTableReader,
)


def test_llamaindex_relationship_reader_returns_documents() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _mock(rsps, "cmdb_rel_ci", [EDGE])
        conn = _conn()
        try:
            docs = ServiceNowRelationshipReader(connection=conn).load_data()
        finally:
            conn.close()

    assert len(docs) == 1
    assert docs[0].metadata["type_sys_id"] == TYPE_ID


def test_llamaindex_table_reader_forwards_the_table_argument() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _mock(rsps, "sc_task", [TASK])
        conn = _conn()
        try:
            docs = ServiceNowTableReader(connection=conn, table="sc_task").load_data()
        finally:
            conn.close()

    assert docs[0].metadata["table"] == "sc_task"


def test_llamaindex_readers_still_exclude_sys_id_from_llm_metadata() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _mock(rsps, "sc_task", [TASK])
        conn = _conn()
        try:
            docs = ServiceNowTableReader(connection=conn, table="sc_task").load_data()
        finally:
            conn.close()

    assert "sys_id" in docs[0].excluded_llm_metadata_keys


def test_llamaindex_readers_keep_identifier_companions_out_of_the_prompt() -> None:
    """Reference expansion puts a sys_id beside every reference. Those are
    for joining, not for a model to read, and at 32 characters each they are
    not free."""
    record = {
        "sys_id": TASK_ID,
        "short_description": "Order a laptop",
        "assignment_group": {"display_value": "Service Desk", "value": PARENT_ID},
    }

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _mock(rsps, "sc_task", [record])
        conn = _conn()
        try:
            docs = ServiceNowTableReader(connection=conn, table="sc_task").load_data()
        finally:
            conn.close()

    excluded = docs[0].excluded_llm_metadata_keys
    assert "assignment_group_sys_id" in excluded
    assert "assignment_group" not in excluded
    assert docs[0].metadata["assignment_group_sys_id"] == PARENT_ID
