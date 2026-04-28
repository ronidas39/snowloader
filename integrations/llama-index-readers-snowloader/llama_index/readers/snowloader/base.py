"""ServiceNow readers for LlamaIndex.

Thin wrappers around snowloader's core loaders, exposed through the standard
LlamaIndex BaseReader interface. Each reader delegates to the corresponding
snowloader loader and converts SnowDocument objects into LlamaIndex Documents.

I built these as part of snowloader because I needed a reliable way to pull
ServiceNow data into LlamaIndex pipelines at work. The core library handles
all the ServiceNow API complexity (auth, pagination, display values, retries),
and these readers just bridge the gap to LlamaIndex's document format.

Author: Roni Das
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from llama_index.core.readers.base import BaseReader
from llama_index.core.schema import Document

from snowloader import (
    AttachmentLoader,
    CatalogLoader,
    ChangeLoader,
    CMDBLoader,
    IncidentLoader,
    KnowledgeBaseLoader,
    ProblemLoader,
    SnowConnection,
)
from snowloader.models import BaseSnowLoader, SnowDocument


class _SnowloaderReader(BaseReader):
    """Base reader that wraps a snowloader loader for LlamaIndex.

    Subclasses set ``_loader_class`` to point at the right loader.
    Everything else is handled here.
    """

    _loader_class: type[BaseSnowLoader]
    _default_excluded_llm_keys: list[str] = ["sys_id"]

    def __init__(
        self,
        connection: SnowConnection,
        excluded_llm_metadata_keys: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._excluded_keys = (
            excluded_llm_metadata_keys
            if excluded_llm_metadata_keys is not None
            else self._default_excluded_llm_keys
        )
        self._loader = self._loader_class(connection=connection, **kwargs)

    def load_data(self) -> list[Document]:
        """Load all matching records as LlamaIndex Documents."""
        return [self._convert(d) for d in self._loader.lazy_load()]

    def load_data_since(self, since: datetime) -> list[Document]:
        """Load only records updated after the given datetime."""
        return [self._convert(d) for d in self._loader.load_since(since)]

    def _convert(self, snow_doc: SnowDocument) -> Document:
        return Document(
            text=snow_doc.page_content,
            metadata=snow_doc.metadata,
            excluded_llm_metadata_keys=self._excluded_keys,
        )


class ServiceNowIncidentReader(_SnowloaderReader):
    """Read IT incidents from ServiceNow.

    Pulls incident records with structured text including the number, summary,
    description, state, priority, assignment, and timestamps. Optionally
    includes work notes and comments via ``include_journals=True``.
    """

    _loader_class = IncidentLoader


class ServiceNowKBReader(_SnowloaderReader):
    """Read Knowledge Base articles from ServiceNow.

    HTML content is automatically cleaned to plain text. Falls back to the
    wiki field when the text field is empty.
    """

    _loader_class = KnowledgeBaseLoader


class ServiceNowCMDBReader(_SnowloaderReader):
    """Read CMDB Configuration Items from ServiceNow.

    Supports any CMDB class table via ``ci_class`` parameter (defaults to
    ``cmdb_ci``). When ``include_relationships=True``, fetches the dependency
    graph from ``cmdb_rel_ci`` with concurrent outbound/inbound queries.
    """

    _loader_class = CMDBLoader


class ServiceNowChangeReader(_SnowloaderReader):
    """Read change requests from ServiceNow.

    Documents include the change type, risk level, implementation window
    (start/end dates), and assignment details.
    """

    _loader_class = ChangeLoader


class ServiceNowProblemReader(_SnowloaderReader):
    """Read problem records from ServiceNow.

    Documents include root cause analysis, known error status, and fix notes.
    The ``known_error`` metadata field is a Python boolean.
    """

    _loader_class = ProblemLoader


class ServiceNowCatalogReader(_SnowloaderReader):
    """Read service catalog items from ServiceNow.

    Useful for building LLM-powered service desk chatbots that help users
    find and request the right services.
    """

    _loader_class = CatalogLoader


class ServiceNowAttachmentReader(_SnowloaderReader):
    """Read attachment metadata (and optionally content) from ServiceNow.

    Pulls rows from ``sys_attachment`` and yields one Document per file. Pass
    ``download=True`` to fetch each file's bytes during iteration.
    """

    _loader_class = AttachmentLoader
