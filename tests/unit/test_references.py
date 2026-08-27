"""Tests for reference field handling.

A graph is built out of identifiers, but the loaders historically returned
only labels. These tests pin the contract that every reference field is
available as both halves: the readable label under its own name, and the
joinable sys_id under a ``_sys_id`` companion key.

They also cover the sys_id bug this replaced, where the primary key came back
as the string form of a dict.

Author: Roni Das
"""

from __future__ import annotations

from typing import Any

import pytest

from snowloader.fields import (
    ReferenceField,
    expand_reference_keys,
    is_sys_id,
    reference,
)

SYS_USER_ID = "6816f79cc0a8016401c5a33be04be441"
GROUP_ID = "d625dccec0a8016700a222a0f7900d06"
CI_ID = "0c5f3cece1b12010f877971dea0b1449"


# ---------------------------------------------------------------------------
# is_sys_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        SYS_USER_ID,
        CI_ID,
        "0" * 32,
        "ABCDEF0123456789ABCDEF0123456789",
    ],
)
def test_is_sys_id_accepts_32_hex_characters(value: str) -> None:
    assert is_sys_id(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "5",
        "5 - Planning",
        "cmdb_ci_db_mysql_instance",
        SYS_USER_ID[:31],
        SYS_USER_ID + "0",
        "g" * 32,
        "David Loo",
    ],
)
def test_is_sys_id_rejects_everything_else(value: str) -> None:
    assert is_sys_id(value) is False


# ---------------------------------------------------------------------------
# reference / ReferenceField
# ---------------------------------------------------------------------------


def test_reference_splits_a_display_value_all_field_into_both_halves() -> None:
    record = {"caller_id": {"display_value": "survey user", "value": SYS_USER_ID}}
    ref = reference(record, "caller_id")
    assert isinstance(ref, ReferenceField)
    assert ref.label == "survey user"
    assert ref.value == SYS_USER_ID
    assert bool(ref) is True


def test_reference_recovers_the_sys_id_from_a_link() -> None:
    """With sysparm_display_value=true there is no value key, but the sys_id
    is still recoverable from the link URL."""
    record = {
        "assigned_to": {
            "display_value": "David Loo",
            "link": f"https://x.service-now.com/api/now/table/sys_user/{SYS_USER_ID}",
        }
    }
    ref = reference(record, "assigned_to")
    assert ref.label == "David Loo"
    assert ref.value == SYS_USER_ID


def test_reference_of_a_plain_string_field_puts_the_string_in_both_halves() -> None:
    ref = reference({"number": "INC0010001"}, "number")
    assert ref.label == "INC0010001"
    assert ref.value == "INC0010001"


def test_reference_of_an_empty_field_is_falsy() -> None:
    assert bool(reference({"cmdb_ci": ""}, "cmdb_ci")) is False
    assert bool(reference({"cmdb_ci": {"display_value": "", "value": ""}}, "cmdb_ci")) is False
    assert bool(reference({}, "cmdb_ci")) is False


def test_reference_exposes_the_class_name_trap() -> None:
    """Reading the display half of sys_class_name gives a human label, not a
    table name. Both halves have to be reachable so callers stop guessing."""
    record = {
        "sys_class_name": {
            "display_value": "MySQL Instance",
            "value": "cmdb_ci_db_mysql_instance",
        }
    }
    ref = reference(record, "sys_class_name")
    assert ref.label == "MySQL Instance"
    assert ref.value == "cmdb_ci_db_mysql_instance"


# ---------------------------------------------------------------------------
# expand_reference_keys
# ---------------------------------------------------------------------------


def test_expand_adds_a_sys_id_companion_for_a_reference_field() -> None:
    record = {"assignment_group": {"display_value": "Service Desk", "value": GROUP_ID}}
    out = expand_reference_keys(record)
    assert out["assignment_group"] == "Service Desk"
    assert out["assignment_group_sys_id"] == GROUP_ID


def test_expand_adds_a_value_companion_for_a_choice_field() -> None:
    """A choice field's raw half is not a sys_id, so calling it one would be
    a lie. It gets a _value companion instead."""
    record = {"priority": {"display_value": "5 - Planning", "value": "5"}}
    out = expand_reference_keys(record)
    assert out["priority"] == "5 - Planning"
    assert out["priority_value"] == "5"
    assert "priority_sys_id" not in out


def test_expand_adds_nothing_when_both_halves_are_identical() -> None:
    record = {"number": {"display_value": "INC0010001", "value": "INC0010001"}}
    out = expand_reference_keys(record)
    assert out == {"number": "INC0010001"}


def test_expand_normalises_sys_id_without_creating_sys_id_sys_id() -> None:
    """The primary key is the one field that must never gain a companion."""
    record = {"sys_id": {"display_value": CI_ID, "value": CI_ID}}
    out = expand_reference_keys(record)
    assert out["sys_id"] == CI_ID
    assert "sys_id_sys_id" not in out


def test_expand_leaves_plain_string_fields_alone() -> None:
    record = {"short_description": "Printer offline", "state": "2"}
    out = expand_reference_keys(record)
    assert out == {"short_description": "Printer offline", "state": "2"}


def test_expand_handles_an_empty_reference_without_inventing_keys() -> None:
    record = {"cmdb_ci": {"display_value": "", "value": ""}}
    out = expand_reference_keys(record)
    assert out["cmdb_ci"] == ""
    assert "cmdb_ci_sys_id" not in out


def test_expand_treats_a_linked_field_as_a_reference() -> None:
    record = {
        "opened_by": {
            "display_value": "System Administrator",
            "link": f"https://x.service-now.com/api/now/table/sys_user/{SYS_USER_ID}",
        }
    }
    out = expand_reference_keys(record)
    assert out["opened_by"] == "System Administrator"
    assert out["opened_by_sys_id"] == SYS_USER_ID


def test_expand_does_not_clobber_keys_the_caller_already_set() -> None:
    """Loaders curate some metadata by hand. Expansion fills gaps; it does
    not overwrite a considered choice."""
    record = {"assignment_group": {"display_value": "Service Desk", "value": GROUP_ID}}
    target: dict[str, Any] = {"assignment_group": "already set by the loader"}
    expand_reference_keys(record, into=target)
    assert target["assignment_group"] == "already set by the loader"
    assert target["assignment_group_sys_id"] == GROUP_ID


def test_expand_writes_into_a_supplied_dict_and_returns_it() -> None:
    record = {"cmdb_ci": {"display_value": "PROD-DB-01", "value": CI_ID}}
    target: dict[str, Any] = {"table": "incident"}
    out = expand_reference_keys(record, into=target)
    assert out is target
    assert target["table"] == "incident"
    assert target["cmdb_ci_sys_id"] == CI_ID


def test_expand_skips_non_scalar_values() -> None:
    """Journal lists and relationship lists are not reference fields."""
    record = {"relationships": [{"target": "x"}], "sys_id": CI_ID}
    out = expand_reference_keys(record)
    assert out["relationships"] == [{"target": "x"}]
    assert out["sys_id"] == CI_ID
