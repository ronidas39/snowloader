"""Tests for what a loader puts in document metadata.

Before 0.3.0 the loaders returned labels and discarded the identifiers behind
them, so a document could not be joined to the records it referenced. These
tests pin the replacement contract: the label under the field's own name, the
identifier under a ``_sys_id`` companion, and the primary key as a plain
string in every display value mode.

Author: Roni Das
"""

from __future__ import annotations

import re
from typing import Any

import responses

from snowloader import IncidentLoader, SnowConnection

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"

CALLER_ID = "005d500b536073005e0addeeff7b12f4"
OPENER_ID = "6816f79cc0a8016401c5a33be04be441"
GROUP_ID = "d625dccec0a8016700a222a0f7900d06"
CI_ID = "0c5f3cece1b12010f877971dea0b1449"
INCIDENT_ID = "8d6353ea1b1230103c9a9e0b2b4bcb1f"


def _conn(**overrides: Any) -> SnowConnection:
    kwargs: dict[str, Any] = {
        "instance_url": BASE_URL,
        "username": "admin",
        "password": "secret",
        "display_value": "all",
    }
    kwargs.update(overrides)
    return SnowConnection(**kwargs)


def _incident_record() -> dict[str, Any]:
    """One incident in the shape sysparm_display_value=all returns."""
    return {
        "sys_id": {"display_value": INCIDENT_ID, "value": INCIDENT_ID},
        "number": {"display_value": "INC0010001", "value": "INC0010001"},
        "short_description": {"display_value": "Printer offline", "value": "Printer offline"},
        "description": {"display_value": "The floor 3 printer", "value": "The floor 3 printer"},
        "state": {"display_value": "In Progress", "value": "2"},
        "priority": {"display_value": "5 - Planning", "value": "5"},
        "category": {"display_value": "Hardware", "value": "hardware"},
        "caller_id": {"display_value": "survey user", "value": CALLER_ID},
        "opened_by": {"display_value": "System Administrator", "value": OPENER_ID},
        "assigned_to": {"display_value": "David Loo", "value": OPENER_ID},
        "assignment_group": {"display_value": "Service Desk", "value": GROUP_ID},
        "cmdb_ci": {"display_value": "PROD-DB-01", "value": CI_ID},
        "opened_at": {"display_value": "2026-01-04 10:00:00", "value": "2026-01-04 10:00:00"},
        "sys_created_on": {"display_value": "2026-01-04 10:00:00", "value": "2026-01-04 10:00:00"},
        "sys_updated_on": {"display_value": "2026-01-05 09:00:00", "value": "2026-01-05 09:00:00"},
    }


def _load_one(**loader_kwargs: Any) -> dict[str, Any]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": [_incident_record()]},
            status=200,
        )
        conn = _conn(page_size=10)
        try:
            docs = IncidentLoader(conn, **loader_kwargs).load()
        finally:
            conn.close()
    return dict(docs[0].metadata)


# ---------------------------------------------------------------------------
# The sys_id bug
# ---------------------------------------------------------------------------


def test_sys_id_is_a_plain_string_not_a_stringified_dict() -> None:
    """With display_value=all the API returns sys_id as a dict. Putting
    str(dict) in metadata made the primary key unusable."""
    metadata = _load_one()
    assert metadata["sys_id"] == INCIDENT_ID
    assert "display_value" not in metadata["sys_id"]


# ---------------------------------------------------------------------------
# Both halves of every reference
# ---------------------------------------------------------------------------


def test_reference_fields_carry_a_joinable_companion_key() -> None:
    metadata = _load_one()
    assert metadata["assignment_group"] == "Service Desk"
    assert metadata["assignment_group_sys_id"] == GROUP_ID
    assert metadata["assigned_to"] == "David Loo"
    assert metadata["assigned_to_sys_id"] == OPENER_ID


def test_cmdb_ci_holds_the_label_and_the_sys_id_sits_beside_it() -> None:
    """cmdb_ci used to hold a bare sys_id while every sibling reference held
    a label, so the same metadata dict mixed both conventions."""
    metadata = _load_one()
    assert metadata["cmdb_ci"] == "PROD-DB-01"
    assert metadata["cmdb_ci_sys_id"] == CI_ID


def test_caller_and_opener_reach_metadata() -> None:
    """Neither field appeared in incident metadata at all before 0.3.0."""
    metadata = _load_one()
    assert metadata["caller_id"] == "survey user"
    assert metadata["caller_id_sys_id"] == CALLER_ID
    assert metadata["opened_by"] == "System Administrator"
    assert metadata["opened_by_sys_id"] == OPENER_ID


def test_choice_fields_get_a_value_companion_not_a_sys_id_one() -> None:
    metadata = _load_one()
    assert metadata["priority"] == "5 - Planning"
    assert metadata["priority_value"] == "5"
    assert "priority_sys_id" not in metadata


def test_curated_keys_survive_expansion() -> None:
    """The loader assembles a few entries itself. Expansion fills gaps around
    them and must not overwrite them."""
    metadata = _load_one()
    assert metadata["table"] == "incident"
    assert metadata["source"] == "servicenow://incident/INC0010001"


# ---------------------------------------------------------------------------
# Opting out
# ---------------------------------------------------------------------------


def test_expand_references_off_restores_the_curated_only_metadata() -> None:
    """RAG users who want a small metadata dict can turn expansion off."""
    metadata = _load_one(expand_references=False)
    assert metadata["sys_id"] == INCIDENT_ID
    assert "caller_id" not in metadata
    assert "assignment_group_sys_id" not in metadata


def test_include_raw_attaches_the_untouched_record() -> None:
    metadata = _load_one(include_raw=True)
    assert metadata["raw"]["cmdb_ci"] == {"display_value": "PROD-DB-01", "value": CI_ID}


def test_include_raw_is_off_by_default() -> None:
    assert "raw" not in _load_one()


# ---------------------------------------------------------------------------
# The other display value modes
# ---------------------------------------------------------------------------


def test_display_value_true_recovers_sys_ids_from_links() -> None:
    """With display_value=true there is no value key, only a link. The sys_id
    is the last path segment of it."""
    record = {
        "sys_id": INCIDENT_ID,
        "number": "INC0010001",
        "assignment_group": {
            "display_value": "Service Desk",
            "link": f"{TABLE_API}/sys_user_group/{GROUP_ID}",
        },
    }

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": [record]},
            status=200,
        )
        conn = _conn(page_size=10, display_value="true")
        try:
            metadata = IncidentLoader(conn).load()[0].metadata
        finally:
            conn.close()

    assert metadata["sys_id"] == INCIDENT_ID
    assert metadata["assignment_group"] == "Service Desk"
    assert metadata["assignment_group_sys_id"] == GROUP_ID


def test_display_value_false_leaves_plain_strings_alone() -> None:
    record = {
        "sys_id": INCIDENT_ID,
        "number": "INC0010001",
        "assignment_group": GROUP_ID,
        "short_description": "Printer offline",
    }

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": [record]},
            status=200,
        )
        conn = _conn(page_size=10, display_value="false")
        try:
            metadata = IncidentLoader(conn).load()[0].metadata
        finally:
            conn.close()

    assert metadata["sys_id"] == INCIDENT_ID
    assert metadata["assignment_group"] == GROUP_ID
    assert "assignment_group_sys_id" not in metadata
