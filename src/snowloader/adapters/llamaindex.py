"""LlamaIndex adapter for snowloader.

Thin wrappers that expose snowloader's core loaders through the standard
llama_index BaseReader interface. Each adapter delegates all the real
work to the underlying loader and just handles the conversion from
SnowDocument to llama_index Document.

No business logic here. If you need to change how documents are built,
modify the core loaders instead.

Author: Roni Das
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

try:
    from llama_index.core.readers.base import BaseReader
    from llama_index.core.schema import Document
except ImportError as exc:
    raise ImportError(
        "llama-index-core is required for the LlamaIndex adapter. "
        "Install it with: pip install snowloader[llamaindex]"
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


class _LlamaIndexAdapter(BaseReader):
    """Base adapter that wraps any snowloader loader for LlamaIndex.

    Converts SnowDocument instances to LlamaIndex Document objects.
    Subclasses just set the _loader_class attribute.
    """

    _loader_class: type[BaseSnowLoader]

    def __init__(self, connection: SnowConnection, **kwargs: Any) -> None:
        super().__init__()
        self._loader = self._loader_class(connection=connection, **kwargs)

    def load_data(self) -> list[Document]:
        """Return a list of LlamaIndex Documents from the core loader.

        Returns:
            List of LlamaIndex Document instances.
        """
        return [self._to_document(d) for d in self._loader.lazy_load()]

    def load_data_since(self, since: datetime) -> list[Document]:
        """Fetch only records updated after the given datetime.

        Args:
            since: Cutoff datetime for delta sync.

        Returns:
            List of LlamaIndex Document instances.
        """
        return [self._to_document(d) for d in self._loader.load_since(since)]

    @staticmethod
    def _to_document(snow_doc: Any) -> Document:
        """Convert a SnowDocument to a LlamaIndex Document."""
        return Document(
            text=snow_doc.page_content,
            metadata=snow_doc.metadata,
            excluded_llm_metadata_keys=["sys_id"],
        )


class ServiceNowIncidentReader(_LlamaIndexAdapter):
    """LlamaIndex reader for ServiceNow incidents."""

    _loader_class = IncidentLoader


class ServiceNowKBReader(_LlamaIndexAdapter):
    """LlamaIndex reader for ServiceNow Knowledge Base articles."""

    _loader_class = KnowledgeBaseLoader


class ServiceNowCMDBReader(_LlamaIndexAdapter):
    """LlamaIndex reader for ServiceNow CMDB configuration items."""

    _loader_class = CMDBLoader


class ServiceNowChangeReader(_LlamaIndexAdapter):
    """LlamaIndex reader for ServiceNow change requests."""

    _loader_class = ChangeLoader


class ServiceNowProblemReader(_LlamaIndexAdapter):
    """LlamaIndex reader for ServiceNow problem records."""

    _loader_class = ProblemLoader


class ServiceNowCatalogReader(_LlamaIndexAdapter):
    """LlamaIndex reader for ServiceNow service catalog items."""

    _loader_class = CatalogLoader
