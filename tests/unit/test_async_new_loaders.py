"""Tests for the async variants of the two loaders added in 0.3.0.

README and docs/async.rst both state that every sync loader has a matching
Async variant. Until these existed that was not true of TableLoader or
RelationshipLoader.

Author: Roni Das
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from aioresponses import aioresponses

from snowloader import AsyncRelationshipLoader, AsyncSnowConnection, AsyncTableLoader
from snowloader.exceptions import SnowConnectionError

INSTANCE = "https://test.service-now.com"
PARENT_ID = "0c5f3cece1b12010f877971dea0b1449"
CHILD_ID = "b297b0982f4f831020bad7ca6fa4e327"
TYPE_ID = "1a9cb166f1571100a92eb60da2bce5c5"
REL_ID = "3e5f3cece1b12010f877971dea0b14aa"
TASK_ID = "1f2e3d4c5b6a79880123456789abcdef"


def _stats(table: str) -> re.Pattern[str]:
    return re.compile(rf"^{INSTANCE}/api/now/stats/{table}(\?.*)?$")


def _table(table: str) -> re.Pattern[str]:
    return re.compile(rf"^{INSTANCE}/api/now/table/{table}(/[^?]+)?(\?.*)?$")


def _conn(**overrides: Any) -> AsyncSnowConnection:
    kwargs: dict[str, Any] = {
        "instance_url": INSTANCE,
        "username": "u",
        "password": "p",
        "page_size": 10,
    }
    kwargs.update(overrides)
    return AsyncSnowConnection(**kwargs)


EDGE = {
    "sys_id": {"display_value": REL_ID, "value": REL_ID},
    "parent": {"display_value": "PROD-DB-01", "value": PARENT_ID},
    "child": {"display_value": "billing-app", "value": CHILD_ID},
    "type": {"display_value": "Depends on::Used by", "value": TYPE_ID},
}


@pytest.mark.asyncio
async def test_async_relationship_loader_returns_loadable_edges() -> None:
    conn = _conn()
    with aioresponses() as mocked:
        mocked.get(
            _stats("cmdb_rel_ci"), payload={"result": {"stats": {"count": "1"}}}, repeat=True
        )
        mocked.get(_table("cmdb_rel_ci"), payload={"result": [EDGE]}, repeat=True)
        docs = await AsyncRelationshipLoader(connection=conn).aload()
    assert len(docs) == 1
    assert docs[0].metadata["parent_sys_id"] == PARENT_ID
    assert docs[0].metadata["child_sys_id"] == CHILD_ID
    assert docs[0].metadata["type"] == "Depends on::Used by"
    await conn.aclose()


@pytest.mark.asyncio
async def test_async_relationship_loader_targets_the_right_table() -> None:
    conn = _conn()
    loader = AsyncRelationshipLoader(connection=conn)
    assert loader.table == "cmdb_rel_ci"
    await conn.aclose()


@pytest.mark.asyncio
async def test_async_table_loader_reads_the_table_it_was_given() -> None:
    record = {"sys_id": TASK_ID, "short_description": "Order a laptop"}
    conn = _conn()
    with aioresponses() as mocked:
        mocked.get(_stats("sc_task"), payload={"result": {"stats": {"count": "1"}}}, repeat=True)
        mocked.get(_table("sc_task"), payload={"result": [record]}, repeat=True)
        loader = AsyncTableLoader(connection=conn, table="sc_task")
        docs = await loader.aload()
    assert loader.table == "sc_task"
    assert docs[0].metadata["table"] == "sc_task"
    assert docs[0].page_content == "Order a laptop"
    await conn.aclose()


@pytest.mark.asyncio
async def test_async_table_loader_honours_content_fields() -> None:
    record = {
        "sys_id": TASK_ID,
        "short_description": "Order a laptop",
        "description": "16GB, macOS",
    }
    conn = _conn()
    with aioresponses() as mocked:
        mocked.get(_stats("sc_task"), payload={"result": {"stats": {"count": "1"}}}, repeat=True)
        mocked.get(_table("sc_task"), payload={"result": [record]}, repeat=True)
        docs = await AsyncTableLoader(
            connection=conn, table="sc_task", content_fields=["description"]
        ).aload()
    assert docs[0].page_content == "16GB, macOS"
    await conn.aclose()


@pytest.mark.asyncio
async def test_async_table_loader_requires_a_table_name() -> None:
    conn = _conn()
    with pytest.raises(SnowConnectionError):
        AsyncTableLoader(connection=conn, table="")
    await conn.aclose()
