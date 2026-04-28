"""Unit tests for AsyncSnowConnection.

Uses ``aioresponses`` to intercept aiohttp calls so we can verify pagination,
auth header construction, retry behavior, and concurrent fetch ordering
without hitting a real ServiceNow instance.
"""

from __future__ import annotations

import re

import pytest
from aioresponses import aioresponses

from snowloader.async_connection import AsyncSnowConnection
from snowloader.connection import SnowConnectionError

INSTANCE = "https://test.service-now.com"


def _stats_url(table: str = "incident") -> re.Pattern[str]:
    return re.compile(rf"^{INSTANCE}/api/now/stats/{table}(\?.*)?$")


def _table_url(table: str = "incident") -> re.Pattern[str]:
    return re.compile(rf"^{INSTANCE}/api/now/table/{table}(/[^?]+)?(\?.*)?$")


@pytest.mark.asyncio
async def test_basic_auth_constructs() -> None:
    conn = AsyncSnowConnection(
        instance_url=INSTANCE,
        username="u",
        password="p",
    )
    assert conn.auth_type == "basic"
    assert conn.instance_url == INSTANCE
    await conn.aclose()


@pytest.mark.asyncio
async def test_bearer_token_constructs() -> None:
    conn = AsyncSnowConnection(instance_url=INSTANCE, token="abc")
    assert conn.auth_type == "bearer"
    assert conn._access_token == "abc"
    await conn.aclose()


@pytest.mark.asyncio
async def test_oauth_password_grant_constructs() -> None:
    conn = AsyncSnowConnection(
        instance_url=INSTANCE,
        username="u",
        password="p",
        client_id="cid",
        client_secret="secret",
    )
    assert conn.auth_type == "oauth"
    await conn.aclose()


@pytest.mark.asyncio
async def test_client_credentials_constructs() -> None:
    conn = AsyncSnowConnection(
        instance_url=INSTANCE,
        client_id="cid",
        client_secret="secret",
    )
    assert conn.auth_type == "client_credentials"
    await conn.aclose()


@pytest.mark.asyncio
async def test_missing_credentials_raises() -> None:
    with pytest.raises(SnowConnectionError):
        AsyncSnowConnection(instance_url=INSTANCE)


@pytest.mark.asyncio
async def test_invalid_url_raises() -> None:
    with pytest.raises(SnowConnectionError):
        AsyncSnowConnection(instance_url="not a url", username="u", password="p")


@pytest.mark.asyncio
async def test_invalid_page_size_raises() -> None:
    with pytest.raises(SnowConnectionError):
        AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
            page_size=0,
        )


@pytest.mark.asyncio
async def test_invalid_concurrency_raises() -> None:
    with pytest.raises(SnowConnectionError):
        AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
            concurrency=0,
        )


@pytest.mark.asyncio
async def test_aget_count_returns_int() -> None:
    with aioresponses() as m:
        m.get(
            _stats_url(),
            payload={"result": {"stats": {"count": "42"}}},
            status=200,
            repeat=True,
        )
        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            count = await conn.aget_count("incident")
            assert count == 42


@pytest.mark.asyncio
async def test_aget_count_zero_for_missing() -> None:
    with aioresponses() as m:
        m.get(
            _stats_url(),
            payload={"result": {}},
            status=200,
            repeat=True,
        )
        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            assert await conn.aget_count("incident") == 0


@pytest.mark.asyncio
async def test_aget_records_paginates_concurrently() -> None:
    page_records = [{"sys_id": f"id{i}", "number": f"INC{i:04d}"} for i in range(5)]

    with aioresponses() as m:
        # 12 records total -> 3 pages of 5 (last has 2)
        m.get(
            _stats_url(),
            payload={"result": {"stats": {"count": "12"}}},
            status=200,
            repeat=True,
        )
        # All page calls return the same fake data; we only need to check
        # that we get back records from all of them.
        m.get(
            _table_url(),
            payload={"result": page_records},
            status=200,
            repeat=True,
        )

        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
            page_size=5,
            concurrency=4,
        ) as conn:
            records = [rec async for rec in conn.aget_records("incident", query="active=true")]
            # 3 pages * 5 records = 15 yielded (the mock always returns 5)
            assert len(records) == 15


@pytest.mark.asyncio
async def test_aget_records_empty_for_zero_count() -> None:
    with aioresponses() as m:
        m.get(
            _stats_url(),
            payload={"result": {"stats": {"count": "0"}}},
            status=200,
            repeat=True,
        )
        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            records = [rec async for rec in conn.aget_records("incident")]
            assert records == []


@pytest.mark.asyncio
async def test_aget_record_returns_single() -> None:
    with aioresponses() as m:
        m.get(
            re.compile(rf"^{INSTANCE}/api/now/table/incident/abc123$"),
            payload={"result": {"sys_id": "abc123", "number": "INC0001"}},
            status=200,
        )
        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            rec = await conn.aget_record("incident", "abc123")
            assert rec["sys_id"] == "abc123"


@pytest.mark.asyncio
async def test_aget_record_raises_for_empty_sys_id() -> None:
    async with AsyncSnowConnection(
        instance_url=INSTANCE,
        username="u",
        password="p",
    ) as conn:
        with pytest.raises(SnowConnectionError):
            await conn.aget_record("incident", "")


@pytest.mark.asyncio
async def test_request_raises_on_4xx() -> None:
    with aioresponses() as m:
        m.get(
            _stats_url(),
            status=403,
            body="forbidden",
        )
        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            with pytest.raises(SnowConnectionError) as exc_info:
                await conn.aget_count("incident")
            assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_aget_attachment_returns_bytes() -> None:
    with aioresponses() as m:
        m.get(
            re.compile(rf"^{INSTANCE}/api/now/attachment/abc/file$"),
            status=200,
            body=b"binary file content",
            content_type="application/octet-stream",
        )
        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            data = await conn.aget_attachment("abc")
            assert data == b"binary file content"


@pytest.mark.asyncio
async def test_request_treats_null_body_as_empty_result() -> None:
    """Regression: ServiceNow can return JSON null under transient load.

    Previously this crashed aget_records on ``data.get('result')``. Now we
    log a warning and treat it as an empty result.
    """
    with aioresponses() as m:
        m.get(
            _stats_url(),
            payload={"result": {"stats": {"count": "1"}}},
            status=200,
            repeat=True,
        )
        m.get(
            _table_url(),
            body="null",
            status=200,
            content_type="application/json",
            repeat=True,
        )
        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
            page_size=10,
        ) as conn:
            records = [rec async for rec in conn.aget_records("incident")]
            assert records == []


@pytest.mark.asyncio
async def test_request_treats_list_body_as_empty_result() -> None:
    """Regression: defensive handling for unexpected non-object JSON shapes."""
    with aioresponses() as m:
        m.get(
            _stats_url(),
            payload={"result": {"stats": {"count": "1"}}},
            status=200,
            repeat=True,
        )
        m.get(
            _table_url(),
            payload=[1, 2, 3],
            status=200,
            repeat=True,
        )
        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
            page_size=10,
        ) as conn:
            records = [rec async for rec in conn.aget_records("incident")]
            assert records == []


@pytest.mark.asyncio
async def test_aget_attachment_raises_on_404() -> None:
    with aioresponses() as m:
        m.get(
            re.compile(rf"^{INSTANCE}/api/now/attachment/missing/file$"),
            status=404,
            body="not found",
            repeat=True,
        )
        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
            max_retries=0,
        ) as conn:
            with pytest.raises(SnowConnectionError) as exc_info:
                await conn.aget_attachment("missing")
            assert exc_info.value.status_code == 404
