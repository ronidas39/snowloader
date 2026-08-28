"""snowloader -- Comprehensive ServiceNow data loader for AI/LLM pipelines.

Provides a clean, Pythonic interface for pulling data out of ServiceNow tables
and converting it into document formats that LangChain, LlamaIndex, and other
LLM frameworks can work with directly. Built for production use with proper
pagination, delta sync, and memory-efficient streaming.

Author: Roni Das
"""

from __future__ import annotations

from snowloader.checkpoints import Checkpoint, FileCheckpoint
from snowloader.connection import SnowConnection
from snowloader.exceptions import SnowConnectionError, SweepIncompleteError
from snowloader.fields import (
    ReferenceField,
    display_value,
    expand_reference_keys,
    is_sys_id,
    parse_boolean,
    raw_value,
    reference,
)
from snowloader.loaders.attachments import AttachmentLoader
from snowloader.loaders.catalog import CatalogLoader
from snowloader.loaders.changes import ChangeLoader
from snowloader.loaders.cmdb import CMDBLoader
from snowloader.loaders.incidents import IncidentLoader
from snowloader.loaders.knowledge_base import KnowledgeBaseLoader
from snowloader.loaders.problems import ProblemLoader
from snowloader.loaders.relationships import RelationshipLoader
from snowloader.loaders.table import TableLoader
from snowloader.models import BaseSnowLoader, SnowDocument
from snowloader.sweep import SweepReport
from snowloader.utils.parsing import parse_labelled_int

__version__ = "0.5.0"

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
        AsyncRelationshipLoader,
        AsyncTableLoader,
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
        "AsyncRelationshipLoader",
        "AsyncSnowConnection",
        "AsyncTableLoader",
    ]
except ImportError:
    _ASYNC_EXPORTS = []

__all__ = [
    "AttachmentLoader",
    "BaseSnowLoader",
    "CatalogLoader",
    "Checkpoint",
    "ChangeLoader",
    "FileCheckpoint",
    "CMDBLoader",
    "IncidentLoader",
    "KnowledgeBaseLoader",
    "ProblemLoader",
    "ReferenceField",
    "RelationshipLoader",
    "SnowConnection",
    "SnowConnectionError",
    "SnowDocument",
    "SweepIncompleteError",
    "SweepReport",
    "TableLoader",
    "__version__",
    "display_value",
    "expand_reference_keys",
    "is_sys_id",
    "parse_boolean",
    "parse_labelled_int",
    "raw_value",
    "reference",
    *_ASYNC_EXPORTS,
]
