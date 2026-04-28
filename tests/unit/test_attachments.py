"""Unit tests for AttachmentLoader (sync + async)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import responses
from aioresponses import aioresponses

from snowloader import AttachmentLoader, SnowConnection, parse_labelled_int  # noqa: F401
from snowloader.async_connection import AsyncSnowConnection
from snowloader.async_models import AsyncAttachmentLoader

INSTANCE = "https://test.service-now.com"


@responses.activate
def test_attachment_loader_yields_metadata_only() -> None:
    responses.add(
        responses.GET,
        f"{INSTANCE}/api/now/table/sys_attachment",
        json={
            "result": [
                {
                    "sys_id": "att1",
                    "file_name": "diagram.png",
                    "content_type": "image/png",
                    "size_bytes": "12345",
                    "table_name": "kb_knowledge",
                    "table_sys_id": "kb1",
                }
            ]
        },
        status=200,
    )
    conn = SnowConnection(
        instance_url=INSTANCE,
        username="u",
        password="p",
        page_size=100,
    )
    loader = AttachmentLoader(connection=conn)
    docs = loader.load()
    assert len(docs) == 1
    md = docs[0].metadata
    assert md["file_name"] == "diagram.png"
    assert md["content_type"] == "image/png"
    assert md["size_bytes"] == 12345
    assert md["table_name"] == "kb_knowledge"
    assert md["download_url"].endswith("/api/now/attachment/att1/file")
    assert "content_bytes" not in md
    conn.close()


@responses.activate
def test_attachment_loader_eager_download() -> None:
    responses.add(
        responses.GET,
        f"{INSTANCE}/api/now/table/sys_attachment",
        json={
            "result": [
                {
                    "sys_id": "att1",
                    "file_name": "file.txt",
                    "size_bytes": "11",
                    "content_type": "text/plain",
                }
            ]
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{INSTANCE}/api/now/attachment/att1/file",
        body=b"hello world",
        status=200,
    )
    conn = SnowConnection(
        instance_url=INSTANCE,
        username="u",
        password="p",
    )
    loader = AttachmentLoader(connection=conn, download=True)
    docs = loader.load()
    assert docs[0].metadata["content_bytes"] == b"hello world"
    conn.close()


@responses.activate
def test_attachment_loader_download_to_writes_file(tmp_path: Path) -> None:
    responses.add(
        responses.GET,
        f"{INSTANCE}/api/now/attachment/att1/file",
        body=b"abc",
        status=200,
    )
    conn = SnowConnection(
        instance_url=INSTANCE,
        username="u",
        password="p",
    )
    loader = AttachmentLoader(connection=conn)
    target = tmp_path / "file.bin"
    written = loader.download_to("att1", target)
    assert written == target
    assert target.read_bytes() == b"abc"
    conn.close()


@responses.activate
def test_attachment_loader_max_size_skips_download() -> None:
    responses.add(
        responses.GET,
        f"{INSTANCE}/api/now/table/sys_attachment",
        json={
            "result": [
                {
                    "sys_id": "att_big",
                    "file_name": "huge.bin",
                    "size_bytes": "5000000",
                    "content_type": "application/octet-stream",
                }
            ]
        },
        status=200,
    )
    conn = SnowConnection(
        instance_url=INSTANCE,
        username="u",
        password="p",
    )
    loader = AttachmentLoader(connection=conn, download=True, max_size_bytes=1000)
    docs = loader.load()
    # Metadata flows through; content_bytes is not present because file was too big
    assert "content_bytes" not in docs[0].metadata
    conn.close()


@responses.activate
def test_get_attachment_returns_bytes() -> None:
    responses.add(
        responses.GET,
        f"{INSTANCE}/api/now/attachment/abc/file",
        body=b"raw bytes",
        status=200,
    )
    conn = SnowConnection(
        instance_url=INSTANCE,
        username="u",
        password="p",
    )
    data = conn.get_attachment("abc")
    assert data == b"raw bytes"
    conn.close()


@pytest.mark.asyncio
async def test_async_attachment_loader_metadata_only() -> None:
    with aioresponses() as m:
        m.get(
            re.compile(rf"^{INSTANCE}/api/now/stats/sys_attachment(\?.*)?$"),
            payload={"result": {"stats": {"count": "1"}}},
            status=200,
            repeat=True,
        )
        m.get(
            re.compile(rf"^{INSTANCE}/api/now/table/sys_attachment(\?.*)?$"),
            payload={
                "result": [
                    {
                        "sys_id": "att1",
                        "file_name": "doc.pdf",
                        "content_type": "application/pdf",
                        "size_bytes": "8000",
                        "table_name": "incident",
                        "table_sys_id": "inc1",
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
            page_size=100,
        ) as conn:
            loader = AsyncAttachmentLoader(connection=conn)
            docs = await loader.aload()
            assert len(docs) == 1
            assert docs[0].metadata["file_name"] == "doc.pdf"
            assert "content_bytes" not in docs[0].metadata


@pytest.mark.asyncio
async def test_async_attachment_loader_with_download() -> None:
    with aioresponses() as m:
        m.get(
            re.compile(rf"^{INSTANCE}/api/now/stats/sys_attachment(\?.*)?$"),
            payload={"result": {"stats": {"count": "1"}}},
            status=200,
            repeat=True,
        )
        m.get(
            re.compile(rf"^{INSTANCE}/api/now/table/sys_attachment(\?.*)?$"),
            payload={
                "result": [
                    {
                        "sys_id": "att1",
                        "file_name": "small.txt",
                        "content_type": "text/plain",
                        "size_bytes": "5",
                    }
                ]
            },
            status=200,
            repeat=True,
        )
        m.get(
            re.compile(rf"^{INSTANCE}/api/now/attachment/att1/file$"),
            body=b"hello",
            status=200,
            repeat=True,
        )

        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            loader = AsyncAttachmentLoader(connection=conn, download=True)
            docs = await loader.aload()
            assert docs[0].metadata["content_bytes"] == b"hello"


@pytest.mark.asyncio
async def test_async_get_attachment_bytes_helper() -> None:
    with aioresponses() as m:
        m.get(
            re.compile(rf"^{INSTANCE}/api/now/attachment/xyz/file$"),
            body=b"file data",
            status=200,
        )

        async with AsyncSnowConnection(
            instance_url=INSTANCE,
            username="u",
            password="p",
        ) as conn:
            loader = AsyncAttachmentLoader(connection=conn)
            data = await loader.aget_bytes("xyz")
            assert data == b"file data"
