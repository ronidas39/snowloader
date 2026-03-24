"""Tests for IncidentLoader.

Covers table configuration, document assembly from raw incident records,
resolution notes handling, journal inclusion, reference field extraction,
metadata population, source URI formatting, and the display/raw value
helper functions that deal with ServiceNow's mixed field formats.

Author: Roni Das
"""

from __future__ import annotations

import responses

from snowloader.connection import SnowConnection
from snowloader.loaders.incidents import (
    IncidentLoader,
    _display_value,
    _raw_value,
)

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"


def _make_connection() -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret")


# Sample incident record that looks like a real SN API response with
# sysparm_display_value=all (reference fields come back as dicts)
SAMPLE_INCIDENT: dict = {
    "sys_id": "abc123def456",
    "number": "INC0010001",
    "short_description": "Email server not responding",
    "description": "Users in building 4 cannot send or receive email since 9am.",
    "state": {"display_value": "In Progress", "value": "2"},
    "priority": {"display_value": "2 - High", "value": "2"},
    "category": "email",
    "subcategory": "send/receive",
    "assigned_to": {"display_value": "John Smith", "value": "user_sys_id_001"},
    "assignment_group": {"display_value": "Email Support", "value": "group_sys_id_001"},
    "cmdb_ci": {"display_value": "EXCH-PROD-01", "value": "ci_sys_id_001"},
    "opened_at": "2024-06-15 09:00:00",
    "closed_at": "",
    "resolved_at": "",
    "close_notes": "",
    "sys_created_on": "2024-06-15 09:00:00",
    "sys_updated_on": "2024-06-15 11:30:00",
}


def test_incident_loader_table_name() -> None:
    """IncidentLoader should target the 'incident' table."""
    loader = IncidentLoader(connection=_make_connection())
    assert loader.table == "incident"


def test_incident_loader_default_fields() -> None:
    """The content_fields list should include the fields we need for
    building useful incident documents."""
    loader = IncidentLoader(connection=_make_connection())
    assert "short_description" in loader.content_fields
    assert "description" in loader.content_fields


@responses.activate
def test_incident_to_document_basic() -> None:
    """A basic incident should produce a document with the key details
    laid out in a structured, readable format."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [SAMPLE_INCIDENT]},
        status=200,
    )

    loader = IncidentLoader(connection=_make_connection())
    docs = loader.load()

    assert len(docs) == 1
    content = docs[0].page_content

    # The formatted output should contain the important pieces
    assert "INC0010001" in content
    assert "Email server not responding" in content
    assert "Users in building 4" in content
    assert "In Progress" in content
    assert "2 - High" in content


@responses.activate
def test_incident_to_document_with_resolution() -> None:
    """A closed incident with close_notes should include those notes
    in the document content."""
    closed_incident = {
        **SAMPLE_INCIDENT,
        "state": {"display_value": "Closed", "value": "7"},
        "closed_at": "2024-06-15 14:00:00",
        "resolved_at": "2024-06-15 13:30:00",
        "close_notes": "Restarted Exchange transport service. Mail flow restored.",
    }
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [closed_incident]},
        status=200,
    )

    loader = IncidentLoader(connection=_make_connection())
    docs = loader.load()

    content = docs[0].page_content
    assert "Restarted Exchange transport service" in content


@responses.activate
def test_incident_to_document_with_journals() -> None:
    """When include_journals is True, the loader should fetch journal
    entries and append them to the document."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [SAMPLE_INCIDENT]},
        status=200,
    )
    # Journal entries for this incident
    responses.add(
        responses.GET,
        f"{TABLE_API}/sys_journal_field",
        json={
            "result": [
                {
                    "value": "Checked the mail queue, 500+ messages stuck.",
                    "element": "work_notes",
                    "sys_created_on": "2024-06-15 10:00:00",
                    "sys_created_by": "john.smith",
                },
            ]
        },
        status=200,
    )

    loader = IncidentLoader(connection=_make_connection(), include_journals=True)
    docs = loader.load()

    content = docs[0].page_content
    assert "500+ messages stuck" in content
    assert "john.smith" in content


@responses.activate
def test_incident_to_document_reference_fields() -> None:
    """Reference fields come back as {display_value, value} dicts when
    sysparm_display_value=all. The loader should extract display_value
    for the document content."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [SAMPLE_INCIDENT]},
        status=200,
    )

    loader = IncidentLoader(connection=_make_connection())
    docs = loader.load()

    content = docs[0].page_content
    # Should show the human-readable display values, not sys_ids
    assert "John Smith" in content
    assert "Email Support" in content


@responses.activate
def test_incident_metadata_contains_required_keys() -> None:
    """Metadata should carry the essential fields that downstream systems
    need for filtering, deduplication, and linking back to ServiceNow."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [SAMPLE_INCIDENT]},
        status=200,
    )

    loader = IncidentLoader(connection=_make_connection())
    docs = loader.load()
    meta = docs[0].metadata

    assert meta["sys_id"] == "abc123def456"
    assert meta["number"] == "INC0010001"
    assert meta["table"] == "incident"
    assert "source" in meta


@responses.activate
def test_incident_source_format() -> None:
    """The source field in metadata should follow the
    servicenow://incident/{number} URI pattern."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [SAMPLE_INCIDENT]},
        status=200,
    )

    loader = IncidentLoader(connection=_make_connection())
    docs = loader.load()

    assert docs[0].metadata["source"] == "servicenow://incident/INC0010001"


# -- Helper function tests --


def test_display_value_helper_with_dict() -> None:
    """_display_value should pull display_value from a reference field dict."""
    field = {"display_value": "John Smith", "value": "user_sys_id"}
    assert _display_value(field) == "John Smith"


def test_display_value_helper_with_string() -> None:
    """_display_value on a plain string should return it as-is."""
    assert _display_value("just a string") == "just a string"


def test_display_value_helper_with_none() -> None:
    """_display_value on None should return empty string."""
    assert _display_value(None) == ""


def test_raw_value_helper() -> None:
    """_raw_value should pull the raw value from a reference field dict,
    falling back to str() for plain values."""
    assert _raw_value({"display_value": "John", "value": "sys_id_123"}) == "sys_id_123"
    assert _raw_value("plain") == "plain"
    assert _raw_value(None) == ""
