"""Unit tests for async loader variants.

Verifies that each Async*Loader produces SnowDocuments with the same
content and metadata as its sync sibling, and that concurrent pagination
works through the AsyncBaseSnowLoader pipeline.
"""

from __future__ import annotations

import re

import pytest
from aioresponses import aioresponses

from snowloader import (
    AsyncCatalogLoader,
    AsyncChangeLoader,
    AsyncCMDBLoader,
    AsyncIncidentLoader,
    AsyncKnowledgeBaseLoader,
    AsyncProblemLoader,
    AsyncSnowConnection,
)

INSTANCE = "https://test.service-now.com"


def _stats_url(table: str) -> re.Pattern[str]:
    return re.compile(rf"^{INSTANCE}/api/now/stats/{table}(\?.*)?$")


def _table_url(table: str) -> re.Pattern[str]:
    return re.compile(rf"^{INSTANCE}/api/now/table/{table}(\?.*)?$")


@pytest.mark.asyncio
async def test_async_incident_loader_yields_documents() -> None:
    with aioresponses() as m:
        m.get(
            _stats_url("incident"),
            payload={"result": {"stats": {"count": "1"}}},
            status=200,
            repeat=True,
        )
        m.get(
            _table_url("incident"),
            payload={
                "result": [
                    {
                        "sys_id": "abc123",
                        "number": "INC0001",
                        "short_description": "Email outage",
                        "state": "Resolved",
                        "priority": "1 - Critical",
                    }
                ]
            },
            status=200,
            repeat=True,
        )

        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
            page_size=10,
        ) as conn:
            loader = AsyncIncidentLoader(connection=conn)
            docs = await loader.aload()
            assert len(docs) == 1
            assert "INC0001" in docs[0].page_content
            assert docs[0].metadata["table"] == "incident"


@pytest.mark.asyncio
async def test_async_kb_loader_strips_html() -> None:
    with aioresponses() as m:
        m.get(
            _stats_url("kb_knowledge"),
            payload={"result": {"stats": {"count": "1"}}},
            status=200,
            repeat=True,
        )
        m.get(
            _table_url("kb_knowledge"),
            payload={
                "result": [
                    {
                        "sys_id": "kb1",
                        "number": "KB0001",
                        "short_description": "How to reset",
                        "text": "<p>Click <strong>reset</strong>.</p>",
                    }
                ]
            },
            status=200,
            repeat=True,
        )

        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            loader = AsyncKnowledgeBaseLoader(connection=conn)
            docs = await loader.aload()
            assert len(docs) == 1
            assert "<p>" not in docs[0].page_content
            assert "reset" in docs[0].page_content


@pytest.mark.asyncio
async def test_async_cmdb_loader_uses_class_table() -> None:
    with aioresponses() as m:
        m.get(
            _stats_url("cmdb_ci_server"),
            payload={"result": {"stats": {"count": "1"}}},
            status=200,
            repeat=True,
        )
        m.get(
            _table_url("cmdb_ci_server"),
            payload={
                "result": [
                    {
                        "sys_id": "ci1",
                        "name": "web-prod-01",
                        "sys_class_name": "cmdb_ci_server",
                        "operational_status": "1",
                    }
                ]
            },
            status=200,
            repeat=True,
        )

        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            loader = AsyncCMDBLoader(connection=conn, ci_class="cmdb_ci_server")
            docs = await loader.aload()
            assert len(docs) == 1
            assert "web-prod-01" in docs[0].page_content


@pytest.mark.asyncio
async def test_async_change_loader_basic() -> None:
    with aioresponses() as m:
        m.get(
            _stats_url("change_request"),
            payload={"result": {"stats": {"count": "1"}}},
            status=200,
            repeat=True,
        )
        m.get(
            _table_url("change_request"),
            payload={
                "result": [
                    {
                        "sys_id": "chg1",
                        "number": "CHG0001",
                        "short_description": "Patch servers",
                        "state": "Implement",
                    }
                ]
            },
            status=200,
            repeat=True,
        )

        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            loader = AsyncChangeLoader(connection=conn)
            docs = await loader.aload()
            assert len(docs) == 1
            assert "CHG0001" in docs[0].page_content


@pytest.mark.asyncio
async def test_async_problem_loader_basic() -> None:
    with aioresponses() as m:
        m.get(
            _stats_url("problem"),
            payload={"result": {"stats": {"count": "1"}}},
            status=200,
            repeat=True,
        )
        m.get(
            _table_url("problem"),
            payload={
                "result": [
                    {
                        "sys_id": "prb1",
                        "number": "PRB0001",
                        "short_description": "Recurring DB lockup",
                        "known_error": "true",
                    }
                ]
            },
            status=200,
            repeat=True,
        )

        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            loader = AsyncProblemLoader(connection=conn)
            docs = await loader.aload()
            assert len(docs) == 1
            assert "PRB0001" in docs[0].page_content


@pytest.mark.asyncio
async def test_async_catalog_loader_basic() -> None:
    with aioresponses() as m:
        m.get(
            _stats_url("sc_cat_item"),
            payload={"result": {"stats": {"count": "1"}}},
            status=200,
            repeat=True,
        )
        m.get(
            _table_url("sc_cat_item"),
            payload={
                "result": [
                    {
                        "sys_id": "cat1",
                        "name": "New laptop",
                        "short_description": "Standard issue laptop",
                        "active": "true",
                    }
                ]
            },
            status=200,
            repeat=True,
        )

        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            loader = AsyncCatalogLoader(connection=conn)
            docs = await loader.aload()
            assert len(docs) == 1
            assert "New laptop" in docs[0].page_content


@pytest.mark.asyncio
async def test_async_loader_paginates_concurrently() -> None:
    page_data = [
        {"sys_id": f"i{n}", "number": f"INC{n:04d}", "short_description": f"r{n}"}
        for n in range(10)
    ]
    with aioresponses() as m:
        m.get(
            _stats_url("incident"),
            payload={"result": {"stats": {"count": "30"}}},
            status=200,
            repeat=True,
        )
        # 3 pages of 10 records each
        m.get(
            _table_url("incident"),
            payload={"result": page_data},
            status=200,
            repeat=True,
        )

        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
            page_size=10,
            concurrency=3,
        ) as conn:
            loader = AsyncIncidentLoader(connection=conn)
            docs = await loader.aload()
            # 3 pages * 10 records = 30
            assert len(docs) == 30


@pytest.mark.asyncio
async def test_async_lazy_load_streams() -> None:
    with aioresponses() as m:
        m.get(
            _stats_url("incident"),
            payload={"result": {"stats": {"count": "5"}}},
            status=200,
            repeat=True,
        )
        m.get(
            _table_url("incident"),
            payload={
                "result": [
                    {"sys_id": f"id{i}", "number": f"INC{i:04d}", "short_description": "x"}
                    for i in range(5)
                ]
            },
            status=200,
            repeat=True,
        )

        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
            page_size=10,
        ) as conn:
            loader = AsyncIncidentLoader(connection=conn)
            count = 0
            async for doc in loader.alazy_load():
                assert "INC" in doc.page_content
                count += 1
            assert count == 5
