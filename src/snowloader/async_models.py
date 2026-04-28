"""Async base loader and async variants of every snowloader loader.

Each ``Async*Loader`` class wraps the same ``_record_to_document`` logic from
its sync sibling, so document assembly stays in one place. The async variants
only differ in how they fetch records: via :class:`AsyncSnowConnection` with
concurrent pagination instead of sequential ``SnowConnection``.

Author: Roni Das
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, cast

from snowloader.async_connection import AsyncSnowConnection
from snowloader.connection import SnowConnectionError
from snowloader.loaders.catalog import CatalogLoader
from snowloader.loaders.changes import ChangeLoader
from snowloader.loaders.cmdb import CMDBLoader
from snowloader.loaders.incidents import IncidentLoader
from snowloader.loaders.knowledge_base import KnowledgeBaseLoader
from snowloader.loaders.problems import ProblemLoader
from snowloader.models import BaseSnowLoader, SnowDocument

logger = logging.getLogger(__name__)


class AsyncBaseSnowLoader:
    """Async counterpart to :class:`BaseSnowLoader`.

    Mirrors the public surface of the sync base class with coroutines:

        - ``aload()`` returns ``list[SnowDocument]``
        - ``alazy_load()`` is an async iterator
        - ``aload_since(since)`` returns ``list[SnowDocument]``

    Subclasses inject a sync sibling loader class via ``_sync_loader_class``
    so the document-assembly logic (which has no I/O) stays shared.

    Args:
        connection: An initialized :class:`AsyncSnowConnection`.
        query: Optional encoded query string.
        fields: Optional list of field names.
        include_journals: Whether to fetch journal entries.
    """

    table: str = ""
    _sync_loader_class: type[BaseSnowLoader] | None = None

    def __init__(
        self,
        connection: AsyncSnowConnection,
        query: str | None = None,
        fields: list[str] | None = None,
        include_journals: bool = False,
        **loader_kwargs: Any,
    ) -> None:
        self._connection = connection
        self._query = query
        self._fields = fields
        self._include_journals = include_journals
        self._loader_kwargs = loader_kwargs

        if self._sync_loader_class is None:
            raise NotImplementedError(
                "Subclasses must set _sync_loader_class to the matching sync loader."
            )

        # The sync loader is used purely for document assembly. We bypass its
        # __init__ so it never opens a sync session; we then patch the few
        # attributes its _record_to_document path actually reads.
        assembler = self._sync_loader_class.__new__(self._sync_loader_class)
        # The connection is only consulted for instance_url and journal fetches
        # (which we override to use the async path), so the type mismatch is
        # intentional here.
        assembler_any = cast(Any, assembler)
        assembler_any._connection = connection
        assembler_any._query = query
        assembler_any._fields = fields
        assembler_any._include_journals = include_journals
        for key, val in loader_kwargs.items():
            setattr(assembler_any, f"_{key}", val)
        self._assembler = assembler
        self.table = self._assembler.table

    async def aload(self) -> list[SnowDocument]:
        """Fetch all matching records as a list of SnowDocuments."""
        return [doc async for doc in self.alazy_load()]

    async def alazy_load(self, since: datetime | None = None) -> AsyncIterator[SnowDocument]:
        """Yield SnowDocuments one at a time using concurrent pagination."""
        async for record in self._connection.aget_records(
            table=self.table,
            query=self._query,
            fields=self._fields,
            since=since,
        ):
            doc = self._assembler._record_to_document(record)
            if self._include_journals:
                sys_id = str(record.get("sys_id", ""))
                if sys_id:
                    journals = await self._afetch_journals(sys_id)
                    journal_text = self._assembler._format_journals(journals)
                    if journal_text:
                        doc.page_content = doc.page_content + "\n\n" + journal_text
            yield doc

    async def aload_since(self, since: datetime) -> list[SnowDocument]:
        """Fetch records updated after ``since``."""
        return [doc async for doc in self.alazy_load(since=since)]

    async def _afetch_journals(self, sys_id: str) -> list[dict[str, Any]]:
        try:
            query = f"element_id={sys_id}^elementINwork_notes,comments"
            return [
                rec
                async for rec in self._connection.aget_records(
                    table="sys_journal_field",
                    query=query,
                    fields=["value", "element", "sys_created_on", "sys_created_by"],
                )
            ]
        except SnowConnectionError:
            logger.warning(
                "Failed to fetch journals for record %s. Continuing without entries.",
                sys_id,
                exc_info=True,
            )
            return []


class AsyncIncidentLoader(AsyncBaseSnowLoader):
    """Async incident loader."""

    _sync_loader_class = IncidentLoader


class AsyncKnowledgeBaseLoader(AsyncBaseSnowLoader):
    """Async KB article loader with HTML cleaning."""

    _sync_loader_class = KnowledgeBaseLoader


class AsyncCMDBLoader(AsyncBaseSnowLoader):
    """Async CMDB CI loader.

    Note: relationship traversal is not yet ported to the async path because
    the sync CMDBLoader uses a ThreadPoolExecutor under the hood. For now,
    use the sync :class:`CMDBLoader` when you need ``include_relationships``.
    The async variant returns CI records with full metadata but no
    relationship graph.
    """

    _sync_loader_class = CMDBLoader

    def __init__(
        self,
        connection: AsyncSnowConnection,
        query: str | None = None,
        fields: list[str] | None = None,
        ci_class: str | None = None,
    ) -> None:
        super().__init__(
            connection,
            query=query,
            fields=fields,
            include_journals=False,
        )
        # Override the table set by the assembler if a specific class was requested
        if ci_class:
            self.table = ci_class
            self._assembler.table = ci_class
        # Force relationship traversal off in the async path
        assembler_any = cast(Any, self._assembler)
        assembler_any._include_relationships = False
        assembler_any._max_relationship_workers = 2


class AsyncChangeLoader(AsyncBaseSnowLoader):
    """Async change request loader."""

    _sync_loader_class = ChangeLoader


class AsyncProblemLoader(AsyncBaseSnowLoader):
    """Async problem record loader."""

    _sync_loader_class = ProblemLoader


class AsyncCatalogLoader(AsyncBaseSnowLoader):
    """Async service catalog item loader."""

    _sync_loader_class = CatalogLoader


class AsyncAttachmentLoader(AsyncBaseSnowLoader):
    """Async sys_attachment loader.

    Yields :class:`SnowDocument` records with attachment metadata. Set
    ``download=True`` to fetch each file's bytes during iteration (slow on
    large attachments). For selective downloads, leave ``download`` off and
    call :meth:`aget_bytes` on the sys_ids you actually need.

    Args:
        connection: An :class:`AsyncSnowConnection`.
        query: Optional encoded query (e.g. ``"table_name=kb_knowledge"``).
        fields: Optional field list override.
        download: If True, fetch bytes during iteration.
        max_size_bytes: Skip downloads above this size.
    """

    from snowloader.loaders.attachments import AttachmentLoader as _AttachmentLoader  # noqa: E402

    _sync_loader_class = _AttachmentLoader

    def __init__(
        self,
        connection: AsyncSnowConnection,
        query: str | None = None,
        fields: list[str] | None = None,
        download: bool = False,
        max_size_bytes: int | None = None,
    ) -> None:
        super().__init__(
            connection,
            query=query,
            fields=fields,
            include_journals=False,
        )
        self._download = download
        self._max_size_bytes = max_size_bytes
        # Tell the assembler not to do its own download (we do it async)
        assembler_any = cast(Any, self._assembler)
        assembler_any._download = False
        assembler_any._max_size_bytes = max_size_bytes

    async def alazy_load(self, since: datetime | None = None) -> AsyncIterator[SnowDocument]:
        async for record in self._connection.aget_records(
            table=self.table,
            query=self._query,
            fields=self._fields,
            since=since,
        ):
            doc = self._assembler._record_to_document(record)
            if self._download:
                sys_id = doc.metadata.get("sys_id")
                size_bytes = doc.metadata.get("size_bytes")
                too_large = (
                    self._max_size_bytes is not None
                    and isinstance(size_bytes, int)
                    and size_bytes > self._max_size_bytes
                )
                if sys_id and not too_large:
                    try:
                        content = await self._connection.aget_attachment(sys_id)
                        doc.metadata["content_bytes"] = content
                    except SnowConnectionError as exc:
                        logger.warning("Failed to download %s: %s", sys_id, exc)
            yield doc

    async def aget_bytes(self, sys_id: str) -> bytes:
        """Fetch the binary content of a single attachment."""
        return await self._connection.aget_attachment(sys_id)
