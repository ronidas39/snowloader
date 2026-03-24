"""ServiceNow table loaders for snowloader.

Each loader in this package handles one ServiceNow table (or a small group
of related tables). They all inherit from BaseSnowLoader and produce
SnowDocument instances that the adapter layer can convert into framework
specific document types.
"""

from __future__ import annotations

from snowloader.loaders.incidents import IncidentLoader
from snowloader.loaders.knowledge_base import KnowledgeBaseLoader

__all__ = [
    "IncidentLoader",
    "KnowledgeBaseLoader",
]
