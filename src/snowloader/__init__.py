"""snowloader -- Comprehensive ServiceNow data loader for AI/LLM pipelines.

Provides a clean, Pythonic interface for pulling data out of ServiceNow tables
and converting it into document formats that LangChain, LlamaIndex, and other
LLM frameworks can work with directly. Built for production use with proper
pagination, delta sync, and memory-efficient streaming.

Author: Roni Das
"""

from __future__ import annotations

from snowloader.connection import SnowConnection, SnowConnectionError
from snowloader.loaders.catalog import CatalogLoader
from snowloader.loaders.changes import ChangeLoader
from snowloader.loaders.cmdb import CMDBLoader
from snowloader.loaders.incidents import IncidentLoader
from snowloader.loaders.knowledge_base import KnowledgeBaseLoader
from snowloader.loaders.problems import ProblemLoader
from snowloader.models import BaseSnowLoader, SnowDocument

__version__ = "0.1.0"

__all__ = [
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
]
