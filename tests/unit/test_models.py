"""Tests for SnowDocument and BaseSnowLoader.

SnowDocument is the intermediate document format that sits between the raw
ServiceNow API response and whatever the framework adapters need. BaseSnowLoader
is the abstract parent class that all table-specific loaders inherit from. It
handles the common plumbing: connection management, lazy loading, delta sync,
and journal entry fetching.

Author: Roni Das
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

import responses

from snowloader.connection import SnowConnection
from snowloader.models import BaseSnowLoader, SnowDocument

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"


# -- SnowDocument tests --


def test_snow_document_creation() -> None:
    """SnowDocument should hold page_content and metadata as provided."""
    doc = SnowDocument(
        page_content="Something broke in prod",
        metadata={
            "sys_id": "abc123",
            "number": "INC0010001",
            "table": "incident",
        },
    )
    assert doc.page_content == "Something broke in prod"
    assert doc.metadata["sys_id"] == "abc123"
    assert doc.metadata["number"] == "INC0010001"
    assert doc.metadata["table"] == "incident"


def test_snow_document_default_metadata() -> None:
    """When no metadata dict is passed, SnowDocument should default to
    an empty dict rather than None."""
    doc = SnowDocument(page_content="bare doc")
    assert doc.metadata == {}


# -- BaseSnowLoader tests --
# We need a concrete subclass since BaseSnowLoader is abstract.


class _FakeIncidentLoader(BaseSnowLoader):
    """Minimal subclass that targets the incident table for testing."""

    table = "incident"
    content_fields = ["short_description", "description"]


def _make_connection() -> SnowConnection:
    """Shortcut for building a basic auth connection to our test instance."""
    return SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
    )


@responses.activate
def test_base_loader_load_calls_lazy_load() -> None:
    """load() should return a plain list by consuming lazy_load() under
    the hood. This test checks that the list comes back correctly."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={
            "result": [
                {
                    "sys_id": "aaa",
                    "short_description": "Printer on fire",
                    "description": "Third floor printer is literally on fire.",
                },
            ]
        },
        status=200,
    )

    loader = _FakeIncidentLoader(connection=_make_connection())
    docs = loader.load()

    assert isinstance(docs, list)
    assert len(docs) == 1
    assert "Printer on fire" in docs[0].page_content


@responses.activate
def test_base_loader_lazy_load_yields_documents() -> None:
    """lazy_load() must be a generator that yields SnowDocument instances
    one at a time, not a list. This matters for memory efficiency on
    large tables."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={
            "result": [
                {
                    "sys_id": "aaa",
                    "short_description": "Disk full",
                    "description": "Root partition at 100%.",
                },
                {
                    "sys_id": "bbb",
                    "short_description": "Network flap",
                    "description": "Core switch rebooted itself.",
                },
            ]
        },
        status=200,
    )

    loader = _FakeIncidentLoader(connection=_make_connection())
    result = loader.lazy_load()

    assert isinstance(result, Generator)

    docs = list(result)
    assert len(docs) == 2
    assert all(isinstance(d, SnowDocument) for d in docs)


@responses.activate
def test_base_loader_load_since_filters_by_datetime() -> None:
    """load_since() should pass the cutoff datetime through to
    SnowConnection so that only records updated after that point
    are returned."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={
            "result": [
                {
                    "sys_id": "ccc",
                    "short_description": "Recent ticket",
                    "description": "Filed today.",
                },
            ]
        },
        status=200,
    )

    loader = _FakeIncidentLoader(connection=_make_connection())
    since = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    docs = loader.load_since(since)

    assert len(docs) == 1
    # Verify the datetime filter made it into the request
    sent_params = responses.calls[0].request.params
    assert "sys_updated_on>2024-06-01 00:00:00" in sent_params["sysparm_query"]


@responses.activate
def test_base_loader_fetch_journals() -> None:
    """_fetch_journals() should query the sys_journal_field table for
    work notes and comments tied to a specific record sys_id."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/sys_journal_field",
        json={
            "result": [
                {
                    "value": "Restarted the service, seems fine now.",
                    "element": "work_notes",
                    "sys_created_on": "2024-06-15 09:30:00",
                    "sys_created_by": "admin",
                },
                {
                    "value": "Thanks for the quick fix!",
                    "element": "comments",
                    "sys_created_on": "2024-06-15 10:00:00",
                    "sys_created_by": "end_user",
                },
            ]
        },
        status=200,
    )

    loader = _FakeIncidentLoader(connection=_make_connection())
    journals = loader._fetch_journals("abc123")

    assert len(journals) == 2
    assert journals[0]["element"] == "work_notes"
    assert journals[1]["element"] == "comments"


def test_base_loader_format_journals_output() -> None:
    """_format_journals() should turn a list of journal entry dicts into
    a readable string with timestamps and authors."""
    loader = _FakeIncidentLoader(connection=_make_connection())
    journals = [
        {
            "value": "Looking into this now.",
            "element": "work_notes",
            "sys_created_on": "2024-06-15 09:30:00",
            "sys_created_by": "admin",
        },
        {
            "value": "Still happening on my end.",
            "element": "comments",
            "sys_created_on": "2024-06-15 10:00:00",
            "sys_created_by": "end_user",
        },
    ]

    formatted = loader._format_journals(journals)

    assert "admin" in formatted
    assert "Looking into this now." in formatted
    assert "end_user" in formatted
    assert "Still happening on my end." in formatted
    assert "work_notes" in formatted
    assert "comments" in formatted


def test_base_loader_format_journals_empty() -> None:
    """_format_journals() on an empty list should return an empty string,
    not blow up or return None."""
    loader = _FakeIncidentLoader(connection=_make_connection())
    formatted = loader._format_journals([])
    assert formatted == ""
