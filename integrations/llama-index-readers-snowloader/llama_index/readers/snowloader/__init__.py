"""ServiceNow data readers for LlamaIndex, powered by snowloader.

Provides a reader for each of the core ServiceNow tables plus a generic one
for everything else, each producing LlamaIndex Documents ready for indexing in
any vector store.
"""

from llama_index.readers.snowloader.base import (
    ServiceNowAttachmentReader,
    ServiceNowCatalogReader,
    ServiceNowChangeReader,
    ServiceNowCMDBReader,
    ServiceNowIncidentReader,
    ServiceNowKBReader,
    ServiceNowProblemReader,
    ServiceNowRelationshipReader,
    ServiceNowTableReader,
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
    "ServiceNowRelationshipReader",
    "ServiceNowTableReader",
    *_ASYNC_EXPORTS,
]
