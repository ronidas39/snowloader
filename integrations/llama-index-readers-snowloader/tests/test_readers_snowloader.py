"""Tests for the LlamaIndex snowloader readers."""

from llama_index.readers.snowloader import (
    ServiceNowCatalogReader,
    ServiceNowChangeReader,
    ServiceNowCMDBReader,
    ServiceNowIncidentReader,
    ServiceNowKBReader,
    ServiceNowProblemReader,
)


def test_all_readers_importable() -> None:
    """All six reader classes should be importable from the package."""
    readers = [
        ServiceNowIncidentReader,
        ServiceNowKBReader,
        ServiceNowCMDBReader,
        ServiceNowChangeReader,
        ServiceNowProblemReader,
        ServiceNowCatalogReader,
    ]
    assert len(readers) == 6
