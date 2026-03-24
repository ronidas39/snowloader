"""Tests for LlamaIndex adapter wrappers.

Verifies that our adapters correctly implement the llama_index BaseReader
interface: load_data() returns a list of LlamaIndex Documents, the documents
carry the right text and metadata, and sys_id is excluded from LLM metadata.

Author: Roni Das
"""

from __future__ import annotations

from datetime import datetime, timezone

import responses

li_core = __import__("pytest").importorskip("llama_index.core")

from llama_index.core.schema import Document  # noqa: E402

from snowloader.adapters.llamaindex import (  # noqa: E402
    ServiceNowCatalogReader,
    ServiceNowChangeReader,
    ServiceNowCMDBReader,
    ServiceNowIncidentReader,
    ServiceNowKBReader,
    ServiceNowProblemReader,
)
from snowloader.connection import SnowConnection  # noqa: E402

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"


def _make_connection() -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret")


MOCK_INCIDENT: dict = {
    "sys_id": "aaa",
    "number": "INC001",
    "short_description": "Test incident",
    "description": "Something went wrong.",
    "state": {"display_value": "New", "value": "1"},
    "priority": {"display_value": "1 - Critical", "value": "1"},
    "category": "software",
    "assigned_to": {"display_value": "Admin", "value": "user1"},
    "assignment_group": "",
    "cmdb_ci": "",
    "opened_at": "2024-06-01 09:00:00",
    "closed_at": "",
    "resolved_at": "",
    "close_notes": "",
    "subcategory": "",
    "sys_created_on": "2024-06-01 09:00:00",
    "sys_updated_on": "2024-06-01 09:00:00",
}


@responses.activate
def test_incident_reader_inherits_base_reader() -> None:
    """The LlamaIndex adapter should be a proper subclass of BaseReader."""
    from llama_index.core.readers.base import BaseReader

    reader = ServiceNowIncidentReader(connection=_make_connection())
    assert isinstance(reader, BaseReader)


@responses.activate
def test_incident_reader_load_data_returns_li_documents() -> None:
    """load_data() should return a list of LlamaIndex Document objects."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [MOCK_INCIDENT]},
        status=200,
    )

    reader = ServiceNowIncidentReader(connection=_make_connection())
    docs = reader.load_data()

    assert isinstance(docs, list)
    assert len(docs) == 1
    assert isinstance(docs[0], Document)


@responses.activate
def test_li_document_has_text() -> None:
    """The LlamaIndex Document should carry the formatted incident text."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [MOCK_INCIDENT]},
        status=200,
    )

    reader = ServiceNowIncidentReader(connection=_make_connection())
    docs = reader.load_data()

    assert "INC001" in docs[0].text
    assert "Test incident" in docs[0].text


@responses.activate
def test_li_document_has_metadata() -> None:
    """The LlamaIndex Document metadata should include the standard fields."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [MOCK_INCIDENT]},
        status=200,
    )

    reader = ServiceNowIncidentReader(connection=_make_connection())
    docs = reader.load_data()

    assert docs[0].metadata["sys_id"] == "aaa"
    assert docs[0].metadata["number"] == "INC001"
    assert docs[0].metadata["table"] == "incident"


@responses.activate
def test_li_document_excludes_sys_id_from_llm() -> None:
    """sys_id should be in excluded_llm_metadata_keys so the LLM doesn't see it."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [MOCK_INCIDENT]},
        status=200,
    )

    reader = ServiceNowIncidentReader(connection=_make_connection())
    docs = reader.load_data()

    assert "sys_id" in docs[0].excluded_llm_metadata_keys


@responses.activate
def test_load_data_since() -> None:
    """load_data_since() should pass the datetime through for delta sync."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [MOCK_INCIDENT]},
        status=200,
    )

    reader = ServiceNowIncidentReader(connection=_make_connection())
    since = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    docs = reader.load_data_since(since)

    assert len(docs) == 1
    assert isinstance(docs[0], Document)

    sent_params = responses.calls[0].request.params
    assert "sys_updated_on>2024-06-01 00:00:00" in sent_params["sysparm_query"]


def test_all_readers_exist() -> None:
    """All six reader classes should be importable and instantiable."""
    conn = _make_connection()

    readers = [
        ServiceNowIncidentReader(connection=conn),
        ServiceNowKBReader(connection=conn),
        ServiceNowCMDBReader(connection=conn),
        ServiceNowChangeReader(connection=conn),
        ServiceNowProblemReader(connection=conn),
        ServiceNowCatalogReader(connection=conn),
    ]

    assert len(readers) == 6
