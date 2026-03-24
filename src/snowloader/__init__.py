"""snowloader -- Comprehensive ServiceNow data loader for AI/LLM pipelines.

Provides a clean, Pythonic interface for pulling data out of ServiceNow tables
and converting it into document formats that LangChain, LlamaIndex, and other
LLM frameworks can work with directly. Built for production use with proper
pagination, delta sync, and memory-efficient streaming.

Author: Roni Das
"""

from __future__ import annotations

from snowloader.connection import SnowConnection, SnowConnectionError
from snowloader.models import BaseSnowLoader, SnowDocument

__version__ = "0.1.0"

__all__ = [
    "BaseSnowLoader",
    "SnowConnection",
    "SnowConnectionError",
    "SnowDocument",
    "__version__",
]
