"""Tests that the async adapters cover the same loaders as the sync ones.

The core has nine async loaders and each framework has nine sync adapters, but
only seven async ones. The two missing on each side are the generic
``TableLoader`` and the ``RelationshipLoader``, which are exactly the two an
async user reaching past the six named tables would want.

The parity test is written as a set comparison rather than as a list of
expected names, so adding a tenth loader later fails here until its async
adapter exists too.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import pytest

pytest.importorskip("aiohttp")


def _class_names(module: object, prefix: str) -> set[str]:
    """Names defined on a module that start with prefix, minus the prefix."""
    return {
        name[len(prefix) :]
        for name in dir(module)
        if name.startswith(prefix) and isinstance(getattr(module, name), type)
    }


def test_langchain_async_adapters_cover_every_sync_adapter() -> None:
    pytest.importorskip("langchain_core")
    from snowloader.adapters import langchain as mod

    sync = _class_names(mod, "ServiceNow")
    asyn = _class_names(mod, "AsyncServiceNow")
    assert sync - asyn == set(), f"no async adapter for {sorted(sync - asyn)}"


def test_llamaindex_async_readers_cover_every_sync_reader() -> None:
    pytest.importorskip("llama_index.core")
    from snowloader.adapters import llamaindex as mod

    sync = _class_names(mod, "ServiceNow")
    asyn = _class_names(mod, "AsyncServiceNow")
    assert sync - asyn == set(), f"no async reader for {sorted(sync - asyn)}"


def test_the_new_langchain_adapters_wrap_the_right_loaders() -> None:
    pytest.importorskip("langchain_core")
    from snowloader.adapters.langchain import (
        AsyncServiceNowRelationshipLoader,
        AsyncServiceNowTableLoader,
    )
    from snowloader.async_models import AsyncRelationshipLoader, AsyncTableLoader

    assert AsyncServiceNowTableLoader._loader_class is AsyncTableLoader
    assert AsyncServiceNowRelationshipLoader._loader_class is AsyncRelationshipLoader


def test_the_new_llamaindex_readers_wrap_the_right_loaders() -> None:
    pytest.importorskip("llama_index.core")
    from snowloader.adapters.llamaindex import (
        AsyncServiceNowRelationshipReader,
        AsyncServiceNowTableReader,
    )
    from snowloader.async_models import AsyncRelationshipLoader, AsyncTableLoader

    assert AsyncServiceNowTableReader._loader_class is AsyncTableLoader
    assert AsyncServiceNowRelationshipReader._loader_class is AsyncRelationshipLoader


def test_the_table_adapter_passes_the_table_name_through() -> None:
    """TableLoader is the one adapter with a required extra argument, so a
    thin wrapper that dropped kwargs would break only this one."""
    pytest.importorskip("langchain_core")
    from snowloader.adapters.langchain import AsyncServiceNowTableLoader
    from snowloader.async_connection import AsyncSnowConnection

    conn = AsyncSnowConnection(
        instance_url="https://test.service-now.com", username="u", password="p"
    )
    adapter = AsyncServiceNowTableLoader(conn, table="sys_user_group")
    assert adapter._loader.table == "sys_user_group"
