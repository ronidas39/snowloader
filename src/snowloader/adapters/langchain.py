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
from collections.abc import Iterator
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
