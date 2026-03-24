"""Tests for LangChain adapter wrappers.

Verifies that our adapters correctly implement the langchain_core BaseLoader
interface: load() returns a list of LangChain Documents, lazy_load() returns
an iterator, and the documents carry the right page_content and metadata.

Author: Roni Das
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import responses

lc_core = __import__("pytest").importorskip("langchain_core")

from langchain_core.documents import Document  # noqa: E402

from snowloader.adapters.langchain import (  # noqa: E402
    ServiceNowCatalogLoader,
    ServiceNowChangeLoader,
    ServiceNowCMDBLoader,
    ServiceNowIncidentLoader,
    ServiceNowKBLoader,
    ServiceNowProblemLoader,
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
def test_incident_loader_inherits_base_loader() -> None:
    """The LangChain adapter should be a proper subclass of BaseLoader."""
    from langchain_core.document_loaders import BaseLoader

    loader = ServiceNowIncidentLoader(connection=_make_connection())
    assert isinstance(loader, BaseLoader)


@responses.activate
def test_incident_loader_load_returns_lc_documents() -> None:
    """load() should return a list of langchain_core Document objects."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [MOCK_INCIDENT]},
        status=200,
    )

    loader = ServiceNowIncidentLoader(connection=_make_connection())
    docs = loader.load()

    assert isinstance(docs, list)
    assert len(docs) == 1
    assert isinstance(docs[0], Document)


@responses.activate
def test_incident_loader_lazy_load_is_iterator() -> None:
    """lazy_load() should return an iterator, not a list."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [MOCK_INCIDENT]},
        status=200,
    )

    loader = ServiceNowIncidentLoader(connection=_make_connection())
    result = loader.lazy_load()

    assert isinstance(result, Iterator)
    docs = list(result)
    assert len(docs) == 1
    assert isinstance(docs[0], Document)


@responses.activate
def test_incident_loader_load_since() -> None:
    """load_since() should pass the datetime through for delta sync."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [MOCK_INCIDENT]},
        status=200,
    )

    loader = ServiceNowIncidentLoader(connection=_make_connection())
    since = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    docs = loader.load_since(since)

    assert len(docs) == 1
    assert isinstance(docs[0], Document)

    sent_params = responses.calls[0].request.params
    assert "sys_updated_on>2024-06-01 00:00:00" in sent_params["sysparm_query"]


@responses.activate
def test_lc_document_has_page_content() -> None:
    """The LangChain Document should carry the formatted incident text."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [MOCK_INCIDENT]},
        status=200,
    )

    loader = ServiceNowIncidentLoader(connection=_make_connection())
    docs = loader.load()

    assert "INC001" in docs[0].page_content
    assert "Test incident" in docs[0].page_content


@responses.activate
def test_lc_document_has_metadata() -> None:
    """The LangChain Document metadata should include the standard fields."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [MOCK_INCIDENT]},
        status=200,
    )

    loader = ServiceNowIncidentLoader(connection=_make_connection())
    docs = loader.load()

    assert docs[0].metadata["sys_id"] == "aaa"
    assert docs[0].metadata["number"] == "INC001"
    assert docs[0].metadata["table"] == "incident"


def test_all_adapters_exist() -> None:
    """All six adapter classes should be importable and instantiable."""
    conn = _make_connection()

    adapters = [
        ServiceNowIncidentLoader(connection=conn),
        ServiceNowKBLoader(connection=conn),
        ServiceNowCMDBLoader(connection=conn),
        ServiceNowChangeLoader(connection=conn),
        ServiceNowProblemLoader(connection=conn),
        ServiceNowCatalogLoader(connection=conn),
    ]

    assert len(adapters) == 6
