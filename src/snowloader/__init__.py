"""snowloader -- Comprehensive ServiceNow data loader for AI/LLM pipelines.

Provides a clean, Pythonic interface for pulling data out of ServiceNow tables
and converting it into document formats that LangChain, LlamaIndex, and other
LLM frameworks can work with directly. Built for production use with proper
pagination, delta sync, and memory-efficient streaming.

Author: Roni Das
"""

from __future__ import annotations

from snowloader.connection import SnowConnection, SnowConnectionError
from snowloader.loaders.attachments import AttachmentLoader
from snowloader.loaders.catalog import CatalogLoader
from snowloader.loaders.changes import ChangeLoader
from snowloader.loaders.cmdb import CMDBLoader
from snowloader.loaders.incidents import IncidentLoader
from snowloader.loaders.knowledge_base import KnowledgeBaseLoader
from snowloader.loaders.problems import ProblemLoader
from snowloader.models import BaseSnowLoader, SnowDocument
from snowloader.utils.parsing import parse_labelled_int

__version__ = "0.2.0"

try:
    from snowloader.async_connection import AsyncSnowConnection  # noqa: F401
    from snowloader.async_models import (  # noqa: F401
        AsyncAttachmentLoader,
        AsyncBaseSnowLoader,
        AsyncCatalogLoader,
        AsyncChangeLoader,
        AsyncCMDBLoader,
        AsyncIncidentLoader,
        AsyncKnowledgeBaseLoader,
        AsyncProblemLoader,
    )

    _ASYNC_EXPORTS = [
        "AsyncAttachmentLoader",
        "AsyncBaseSnowLoader",
        "AsyncCMDBLoader",
        "AsyncCatalogLoader",
        "AsyncChangeLoader",
        "AsyncIncidentLoader",
        "AsyncKnowledgeBaseLoader",
        "AsyncProblemLoader",
        "AsyncSnowConnection",
    ]
except ImportError:
    _ASYNC_EXPORTS = []

__all__ = [
    "AttachmentLoader",
    "BaseSnowLoader",
    "CatalogLoader",
    "ChangeLoader",
    "CMDBLoader",
    "IncidentLoader",
    "KnowledgeBaseLoader",
    "ProblemLoader",
    "SnowConnection",
    "SnowConnectionError",
    "SnowDocument",
    "__version__",
    "parse_labelled_int",
    *_ASYNC_EXPORTS,
]
