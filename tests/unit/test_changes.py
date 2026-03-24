"""Tests for ChangeLoader.

Covers table config, basic document assembly, scheduled date handling,
journal inclusion, and metadata population for change requests.

Author: Roni Das
"""

from __future__ import annotations

import responses

from snowloader.connection import SnowConnection
from snowloader.loaders.changes import ChangeLoader

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"


def _make_connection() -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret")


SAMPLE_CHANGE: dict = {
    "sys_id": "chg_001",
    "number": "CHG0040001",
    "short_description": "Upgrade Exchange to latest CU",
    "description": "Apply the June cumulative update to the production Exchange cluster.",
    "type": {"display_value": "Standard", "value": "standard"},
    "state": {"display_value": "Implement", "value": "3"},
    "priority": {"display_value": "3 - Moderate", "value": "3"},
    "risk": {"display_value": "Moderate", "value": "3"},
    "category": "Software",
    "assigned_to": {"display_value": "Mike Chen", "value": "user_003"},
    "assignment_group": {"display_value": "Server Team", "value": "group_001"},
    "cmdb_ci": {"display_value": "EXCH-PROD-01", "value": "ci_001"},
    "start_date": "2024-06-20 02:00:00",
    "end_date": "2024-06-20 06:00:00",
    "opened_at": "2024-06-10 09:00:00",
    "closed_at": "",
    "sys_created_on": "2024-06-10 09:00:00",
    "sys_updated_on": "2024-06-18 14:00:00",
}


def test_change_loader_table_name() -> None:
    """ChangeLoader should target the change_request table."""
    loader = ChangeLoader(connection=_make_connection())
    assert loader.table == "change_request"


@responses.activate
def test_change_to_document_basic() -> None:
    """A change request should produce a document with number, summary,
    type, state, and risk information."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/change_request",
        json={"result": [SAMPLE_CHANGE]},
        status=200,
    )

    loader = ChangeLoader(connection=_make_connection())
    docs = loader.load()

    assert len(docs) == 1
    content = docs[0].page_content
    assert "CHG0040001" in content
    assert "Upgrade Exchange" in content
    assert "Standard" in content
    assert "Moderate" in content


@responses.activate
def test_change_with_schedule_dates() -> None:
    """The implementation window (start_date and end_date) should appear
    in the document so the LLM knows the change schedule."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/change_request",
        json={"result": [SAMPLE_CHANGE]},
        status=200,
    )

    loader = ChangeLoader(connection=_make_connection())
    docs = loader.load()
    content = docs[0].page_content

    assert "2024-06-20 02:00:00" in content
    assert "2024-06-20 06:00:00" in content


@responses.activate
def test_change_with_journals() -> None:
    """When include_journals is True, work notes should be appended."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/change_request",
        json={"result": [SAMPLE_CHANGE]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{TABLE_API}/sys_journal_field",
        json={
            "result": [
                {
                    "value": "CAB approved, proceed with the change.",
                    "element": "work_notes",
                    "sys_created_on": "2024-06-15 10:00:00",
                    "sys_created_by": "change_manager",
                },
            ]
        },
        status=200,
    )

    loader = ChangeLoader(connection=_make_connection(), include_journals=True)
    docs = loader.load()
    content = docs[0].page_content

    assert "CAB approved" in content


@responses.activate
def test_change_metadata_keys() -> None:
    """Metadata should carry the fields needed for filtering and linking."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/change_request",
        json={"result": [SAMPLE_CHANGE]},
        status=200,
    )

    loader = ChangeLoader(connection=_make_connection())
    docs = loader.load()
    meta = docs[0].metadata

    assert meta["sys_id"] == "chg_001"
    assert meta["number"] == "CHG0040001"
    assert meta["table"] == "change_request"
    assert "source" in meta
