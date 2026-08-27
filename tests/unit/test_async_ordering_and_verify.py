"""Tests that the async path shares the sync path's safety guarantees.

The ordering bug and the missing completeness check were in both connections,
so both fixes have to be in both. These tests pin the async half.

Author: Roni Das
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from aioresponses import aioresponses

from snowloader.async_connection import AsyncSnowConnection
from snowloader.exceptions import SnowConnectionError, SweepIncompleteError

INSTANCE = "https://test.service-now.com"


def _stats_url(table: str = "incident") -> re.Pattern[str]:
    return re.compile(rf"^{INSTANCE}/api/now/stats/{table}(\?.*)?$")


def _table_url(table: str = "incident") -> re.Pattern[str]:
    return re.compile(rf"^{INSTANCE}/api/now/table/{table}(/[^?]+)?(\?.*)?$")


def _conn(**overrides: Any) -> AsyncSnowConnection:
    kwargs: dict[str, Any] = {"instance_url": INSTANCE, "username": "u", "password": "p"}
    kwargs.update(overrides)
    return AsyncSnowConnection(**kwargs)


def _rows(start: int, count: int) -> list[dict[str, str]]:
    return [{"sys_id": f"{i:032x}"} for i in range(start, start + count)]


def _sent_query(mocked: aioresponses, table: str = "incident") -> str:
    """Return the sysparm_query of the first table request recorded.

    aioresponses keys its record by a yarl URL, which percent-encodes the
    query string a second time on the way in. parse_qs undoes one layer,
    so unquote undoes the other.
    """
    for _method, url in mocked.requests:
        if f"/api/now/table/{table}" not in str(url):
            continue
        params = parse_qs(urlparse(str(url)).query)
        if "sysparm_query" not in params:
            return ""
        return unquote(params["sysparm_query"][0])
    raise AssertionError("No table request was recorded")


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_default_order_ends_in_sys_id() -> None:
    conn = _conn(page_size=10)
    with aioresponses() as mocked:
        mocked.get(_stats_url(), payload={"result": {"stats": {"count": "2"}}}, repeat=True)
        mocked.get(_table_url(), payload={"result": _rows(0, 2)}, repeat=True)
        async for _ in conn.aget_records("incident"):
            pass
        assert _sent_query(mocked) == "ORDERBYsys_created_on^ORDERBYsys_id"
    await conn.aclose()


@pytest.mark.asyncio
async def test_async_order_by_is_configurable() -> None:
    conn = _conn(page_size=10, order_by="priority")
    with aioresponses() as mocked:
        mocked.get(_stats_url(), payload={"result": {"stats": {"count": "1"}}}, repeat=True)
        mocked.get(_table_url(), payload={"result": _rows(0, 1)}, repeat=True)
        async for _ in conn.aget_records("incident"):
            pass
        assert _sent_query(mocked) == "ORDERBYpriority^ORDERBYsys_id"
    await conn.aclose()


@pytest.mark.asyncio
async def test_async_order_by_none_sends_no_order_clause() -> None:
    conn = _conn(page_size=10, order_by=None)
    with aioresponses() as mocked:
        mocked.get(_stats_url(), payload={"result": {"stats": {"count": "1"}}}, repeat=True)
        mocked.get(_table_url(), payload={"result": _rows(0, 1)}, repeat=True)
        async for _ in conn.aget_records("incident", query="active=true"):
            pass
        assert _sent_query(mocked) == "active=true"
    await conn.aclose()


@pytest.mark.asyncio
async def test_async_order_by_rejects_an_empty_string() -> None:
    with pytest.raises(SnowConnectionError):
        _conn(order_by="  ")


# ---------------------------------------------------------------------------
# Defaults that were measured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_page_size_default_is_larger_than_the_sync_one() -> None:
    """Keep-alive is off here, so every request pays a handshake and fewer,
    larger requests win. Measured on a 2,919 row table, page_size 500 came
    back in roughly half the time page_size 100 did, and halving concurrency
    barely moved it, which says the limit is per-request cost rather than
    requests in flight."""
    conn = _conn()
    assert conn.page_size == 500
    await conn.aclose()


@pytest.mark.asyncio
async def test_keep_alive_is_off_by_default_and_can_be_turned_on() -> None:
    """force_close exists to stop null-body responses on reused connections.
    Turning it off is a decision the caller has to make deliberately."""
    default = _conn()
    assert default.keep_alive is False
    await default.aclose()

    fast = _conn(keep_alive=True)
    assert fast.keep_alive is True
    await fast.aclose()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_verify_passes_on_a_complete_sweep() -> None:
    conn = _conn(page_size=10)
    with aioresponses() as mocked:
        mocked.get(_stats_url(), payload={"result": {"stats": {"count": "4"}}}, repeat=True)
        mocked.get(_table_url(), payload={"result": _rows(0, 4)}, repeat=True)
        received = [rec async for rec in conn.aget_records("incident", verify=True)]
    assert len(received) == 4
    await conn.aclose()


@pytest.mark.asyncio
async def test_async_verify_raises_when_rows_are_missing() -> None:
    conn = _conn(page_size=10)
    with aioresponses() as mocked:
        mocked.get(_stats_url(), payload={"result": {"stats": {"count": "9"}}}, repeat=True)
        mocked.get(_table_url(), payload={"result": _rows(0, 4)}, repeat=True)
        with pytest.raises(SweepIncompleteError) as excinfo:
            async for _ in conn.aget_records("incident", verify=True):
                pass
    assert excinfo.value.report.expected == 9
    assert excinfo.value.report.distinct == 4
    await conn.aclose()


@pytest.mark.asyncio
async def test_async_verify_rejects_a_field_list_without_sys_id() -> None:
    conn = _conn()
    with pytest.raises(SnowConnectionError) as excinfo:
        async for _ in conn.aget_records("incident", fields=["number"], verify=True):
            pass
    assert "sys_id" in str(excinfo.value)
    await conn.aclose()


@pytest.mark.asyncio
async def test_async_on_error_rejects_an_unknown_policy() -> None:
    conn = _conn()
    with pytest.raises(SnowConnectionError):
        async for _ in conn.aget_records("incident", on_error="carry-on-regardless"):
            pass
    await conn.aclose()


# ---------------------------------------------------------------------------
# aconcurrent_get_records
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aconcurrent_get_records_exists_and_returns_records() -> None:
    """Someone moving over from the sync API reaches for this name. It used
    to raise AttributeError."""
    conn = _conn(page_size=10)
    with aioresponses() as mocked:
        mocked.get(_stats_url(), payload={"result": {"stats": {"count": "3"}}}, repeat=True)
        mocked.get(_table_url(), payload={"result": _rows(0, 3)}, repeat=True)
        received = [rec async for rec in conn.aconcurrent_get_records("incident")]
    assert len(received) == 3
    await conn.aclose()


@pytest.mark.asyncio
async def test_aconcurrent_get_records_accepts_max_workers() -> None:
    conn = _conn(page_size=10, concurrency=4)
    with aioresponses() as mocked:
        mocked.get(_stats_url(), payload={"result": {"stats": {"count": "3"}}}, repeat=True)
        mocked.get(_table_url(), payload={"result": _rows(0, 3)}, repeat=True)
        received = [rec async for rec in conn.aconcurrent_get_records("incident", max_workers=2)]
    assert len(received) == 3
    await conn.aclose()


@pytest.mark.asyncio
async def test_aconcurrent_get_records_verifies_like_the_sync_one() -> None:
    conn = _conn(page_size=10)
    with aioresponses() as mocked:
        mocked.get(_stats_url(), payload={"result": {"stats": {"count": "8"}}}, repeat=True)
        mocked.get(_table_url(), payload={"result": _rows(0, 3)}, repeat=True)
        with pytest.raises(SweepIncompleteError):
            async for _ in conn.aconcurrent_get_records("incident", verify=True):
                pass
    await conn.aclose()


# ---------------------------------------------------------------------------
# Delta sync column
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_since_field_is_configurable() -> None:
    from datetime import datetime

    conn = _conn(page_size=10, since_field="sys_created_on")
    with aioresponses() as mocked:
        mocked.get(_stats_url(), payload={"result": {"stats": {"count": "1"}}}, repeat=True)
        mocked.get(_table_url(), payload={"result": _rows(0, 1)}, repeat=True)
        async for _ in conn.aget_records("incident", since=datetime(2026, 1, 1)):
            pass
        assert _sent_query(mocked).startswith("sys_created_on>2026-01-01 00:00:00")
    await conn.aclose()
