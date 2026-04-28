"""ServiceNow data readers for LlamaIndex, powered by snowloader.

Provides six readers covering the core ServiceNow tables, each producing
LlamaIndex Documents ready for indexing in any vector store.
"""

from llama_index.readers.snowloader.base import (
    ServiceNowAttachmentReader,
    ServiceNowCatalogReader,
    ServiceNowChangeReader,
    ServiceNowCMDBReader,
    ServiceNowIncidentReader,
    ServiceNowKBReader,
    ServiceNowProblemReader,
)

# Async variants are re-exported when aiohttp is installed alongside snowloader.
try:
    from snowloader.adapters.llamaindex import (  # noqa: F401
        AsyncServiceNowAttachmentReader,
        AsyncServiceNowCatalogReader,
        AsyncServiceNowChangeReader,
        AsyncServiceNowCMDBReader,
        AsyncServiceNowIncidentReader,
        AsyncServiceNowKBReader,
        AsyncServiceNowProblemReader,
    )

    _ASYNC_EXPORTS = [
        "AsyncServiceNowAttachmentReader",
        "AsyncServiceNowCatalogReader",
        "AsyncServiceNowChangeReader",
        "AsyncServiceNowCMDBReader",
        "AsyncServiceNowIncidentReader",
        "AsyncServiceNowKBReader",
        "AsyncServiceNowProblemReader",
    ]
except ImportError:
    _ASYNC_EXPORTS = []

__all__ = [
    "ServiceNowAttachmentReader",
    "ServiceNowIncidentReader",
    "ServiceNowKBReader",
    "ServiceNowCMDBReader",
    "ServiceNowChangeReader",
    "ServiceNowProblemReader",
    "ServiceNowCatalogReader",
    *_ASYNC_EXPORTS,
]
