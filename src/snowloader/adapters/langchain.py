"""LangChain adapter for snowloader.

Thin wrappers that expose snowloader's core loaders through the standard
langchain_core BaseLoader interface. Each adapter delegates all the real
work to the underlying loader and just handles the conversion from
SnowDocument to langchain_core Document.

No business logic here. If you need to change how documents are built,
modify the core loaders instead.

Author: Roni Das
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from typing import Any

try:
    from langchain_core.document_loaders import BaseLoader
    from langchain_core.documents import Document
except ImportError as exc:
    raise ImportError(
        "langchain-core is required for the LangChain adapter. "
        "Install it with: pip install snowloader[langchain]"
    ) from exc

from snowloader.connection import SnowConnection
from snowloader.loaders.attachments import AttachmentLoader
from snowloader.loaders.catalog import CatalogLoader
from snowloader.loaders.changes import ChangeLoader
from snowloader.loaders.cmdb import CMDBLoader
from snowloader.loaders.incidents import IncidentLoader
from snowloader.loaders.knowledge_base import KnowledgeBaseLoader
from snowloader.loaders.problems import ProblemLoader
from snowloader.models import BaseSnowLoader

logger = logging.getLogger(__name__)


class _LangChainAdapter(BaseLoader):
    """Base adapter that wraps any snowloader loader for LangChain.

    Converts SnowDocument instances to LangChain Document objects.
    Subclasses just set the _loader_class attribute.
    """

    _loader_class: type[BaseSnowLoader]

    def __init__(self, connection: SnowConnection, **kwargs: Any) -> None:
        self._loader = self._loader_class(connection=connection, **kwargs)

    def lazy_load(self) -> Iterator[Document]:
        """Yield LangChain Documents one at a time from the core loader."""
        for snow_doc in self._loader.lazy_load():
            yield Document(
                page_content=snow_doc.page_content,
                metadata=snow_doc.metadata,
            )

    def load_since(self, since: datetime) -> list[Document]:
        """Fetch only records updated after the given datetime.

        Args:
            since: Cutoff datetime for delta sync.

        Returns:
            List of LangChain Document instances.
        """
        return [
            Document(page_content=d.page_content, metadata=d.metadata)
            for d in self._loader.load_since(since)
        ]


class ServiceNowIncidentLoader(_LangChainAdapter):
    """LangChain loader for ServiceNow incidents."""

    _loader_class = IncidentLoader


class ServiceNowKBLoader(_LangChainAdapter):
    """LangChain loader for ServiceNow Knowledge Base articles."""

    _loader_class = KnowledgeBaseLoader


class ServiceNowCMDBLoader(_LangChainAdapter):
    """LangChain loader for ServiceNow CMDB configuration items."""

    _loader_class = CMDBLoader


class ServiceNowChangeLoader(_LangChainAdapter):
    """LangChain loader for ServiceNow change requests."""

    _loader_class = ChangeLoader


class ServiceNowProblemLoader(_LangChainAdapter):
    """LangChain loader for ServiceNow problem records."""

    _loader_class = ProblemLoader


class ServiceNowCatalogLoader(_LangChainAdapter):
    """LangChain loader for ServiceNow service catalog items."""

    _loader_class = CatalogLoader


class ServiceNowAttachmentLoader(_LangChainAdapter):
    """LangChain loader for ServiceNow file attachments.

    Yields one Document per ``sys_attachment`` record. Set ``download=True``
    on the constructor to eagerly fetch each file's bytes into the metadata
    under ``content_bytes``.
    """

    _loader_class = AttachmentLoader


# Async adapters are exposed only when aiohttp is installed. They mirror the
# sync adapters with `aload`/`alazy_load`/`aload_since` coroutines.

try:
    from snowloader.async_connection import AsyncSnowConnection
    from snowloader.async_models import (
        AsyncAttachmentLoader,
        AsyncBaseSnowLoader,
        AsyncCatalogLoader,
        AsyncChangeLoader,
        AsyncCMDBLoader,
        AsyncIncidentLoader,
        AsyncKnowledgeBaseLoader,
        AsyncProblemLoader,
    )
except ImportError:
    pass
else:

    class _AsyncLangChainAdapter:
        """Async base adapter wrapping an Async*Loader for LangChain.

        Provides the standard async loader surface that LangChain expects:
        ``aload()`` returns ``list[Document]`` and ``alazy_load()`` is an async
        iterator of Documents.
        """

        _loader_class: type[AsyncBaseSnowLoader]

        def __init__(self, connection: AsyncSnowConnection, **kwargs: Any) -> None:
            self._loader = self._loader_class(connection=connection, **kwargs)

        async def aload(self) -> list[Document]:
            """Fetch all matching records as LangChain Documents."""
            return [
                Document(page_content=d.page_content, metadata=d.metadata)
                async for d in self._loader.alazy_load()
            ]

        async def alazy_load(self) -> AsyncIterator[Document]:
            """Yield LangChain Documents one at a time."""
            async for snow_doc in self._loader.alazy_load():
                yield Document(page_content=snow_doc.page_content, metadata=snow_doc.metadata)

        async def aload_since(self, since: datetime) -> list[Document]:
            """Fetch records updated after the given timestamp."""
            return [
                Document(page_content=d.page_content, metadata=d.metadata)
                async for d in self._loader.alazy_load(since=since)
            ]

    class AsyncServiceNowIncidentLoader(_AsyncLangChainAdapter):
        """Async LangChain loader for ServiceNow incidents."""

        _loader_class = AsyncIncidentLoader

    class AsyncServiceNowKBLoader(_AsyncLangChainAdapter):
        """Async LangChain loader for ServiceNow Knowledge Base articles."""

        _loader_class = AsyncKnowledgeBaseLoader

    class AsyncServiceNowCMDBLoader(_AsyncLangChainAdapter):
        """Async LangChain loader for ServiceNow CMDB CIs (no relationships)."""

        _loader_class = AsyncCMDBLoader

    class AsyncServiceNowChangeLoader(_AsyncLangChainAdapter):
        """Async LangChain loader for ServiceNow change requests."""

        _loader_class = AsyncChangeLoader

    class AsyncServiceNowProblemLoader(_AsyncLangChainAdapter):
        """Async LangChain loader for ServiceNow problem records."""

        _loader_class = AsyncProblemLoader

    class AsyncServiceNowCatalogLoader(_AsyncLangChainAdapter):
        """Async LangChain loader for ServiceNow service catalog items."""

        _loader_class = AsyncCatalogLoader

    class AsyncServiceNowAttachmentLoader(_AsyncLangChainAdapter):
        """Async LangChain loader for ServiceNow attachments."""

        _loader_class = AsyncAttachmentLoader
