"""Tests for the shared field extraction utilities."""

from __future__ import annotations

from snowloader.loaders._field_utils import (
    display_value,
    parse_boolean,
    raw_value,
)
from snowloader.utils.parsing import parse_labelled_int


class TestDisplayValue:
    def test_returns_empty_for_none(self) -> None:
        assert display_value(None) == ""

    def test_returns_empty_for_empty_string(self) -> None:
        assert display_value("") == ""

    def test_returns_string_for_plain_string(self) -> None:
        assert display_value("hello") == "hello"

    def test_extracts_display_value_from_dict(self) -> None:
        field = {"display_value": "John Smith", "link": "https://example.com/sys_user/abc"}
        assert display_value(field) == "John Smith"

    def test_handles_dict_with_value_and_display(self) -> None:
        field = {"display_value": "Critical", "value": "1"}
        assert display_value(field) == "Critical"

    def test_handles_dict_without_display(self) -> None:
        assert display_value({"value": "abc"}) == ""


class TestRawValue:
    def test_returns_empty_for_none(self) -> None:
        assert raw_value(None) == ""

    def test_returns_string_for_plain_string(self) -> None:
        assert raw_value("abc123") == "abc123"

    def test_extracts_value_from_all_format(self) -> None:
        field = {"display_value": "John Smith", "value": "abc123"}
        assert raw_value(field) == "abc123"

    def test_extracts_sys_id_from_link_when_no_value(self) -> None:
        field = {
            "display_value": "John Smith",
            "link": "https://example.com/api/now/table/sys_user/abc123",
        }
        assert raw_value(field) == "abc123"

    def test_falls_back_to_display_when_no_value_or_link(self) -> None:
        assert raw_value({"display_value": "fallback"}) == "fallback"


class TestParseBoolean:
    def test_returns_false_for_none(self) -> None:
        assert parse_boolean(None) is False

    def test_returns_actual_bool(self) -> None:
        assert parse_boolean(True) is True
        assert parse_boolean(False) is False

    def test_parses_true_string(self) -> None:
        assert parse_boolean("true") is True
        assert parse_boolean("TRUE") is True
        assert parse_boolean("True") is True

    def test_parses_false_string(self) -> None:
        assert parse_boolean("false") is False

    def test_parses_yes_and_one(self) -> None:
        assert parse_boolean("yes") is True
        assert parse_boolean("1") is True

    def test_parses_unknown_as_false(self) -> None:
        assert parse_boolean("maybe") is False
        assert parse_boolean("0") is False


class TestParseLabelledInt:
    """Regression tests for ServiceNow labelled integer fields.

    Fields like priority, urgency, impact, and severity come back from the
    Table API in different shapes depending on sysparm_display_value:

        - true:  {"display_value": "3 - Moderate", "value": ...}
        - all:   {"display_value": "3 - Moderate", "value": "3"}
        - false: "3"

    Calling int() directly on "3 - Moderate" raises ValueError. This helper
    handles every shape and returns a clean int (or None for missing values).
    """

    def test_returns_none_for_none(self) -> None:
        assert parse_labelled_int(None) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert parse_labelled_int("") is None

    def test_returns_none_for_empty_dict(self) -> None:
        assert parse_labelled_int({}) is None

    def test_parses_plain_integer_string(self) -> None:
        assert parse_labelled_int("3") == 3

    def test_parses_actual_integer(self) -> None:
        assert parse_labelled_int(3) == 3

    def test_parses_labelled_string(self) -> None:
        assert parse_labelled_int("3 - Moderate") == 3

    def test_parses_labelled_string_with_extra_spaces(self) -> None:
        assert parse_labelled_int("  3 - Moderate  ") == 3

    def test_prefers_value_over_display(self) -> None:
        field = {"display_value": "3 - Moderate", "value": "3"}
        assert parse_labelled_int(field) == 3

    def test_falls_back_to_display_value(self) -> None:
        field = {"display_value": "3 - Moderate"}
        assert parse_labelled_int(field) == 3

    def test_handles_one_critical(self) -> None:
        assert parse_labelled_int("1 - Critical") == 1

    def test_handles_five_planning(self) -> None:
        assert parse_labelled_int("5 - Planning") == 5

    def test_returns_none_for_non_numeric_string(self) -> None:
        assert parse_labelled_int("Critical") is None

    def test_returns_none_for_invalid_dict(self) -> None:
        assert parse_labelled_int({"display_value": "Critical"}) is None

    def test_handles_blank_value_in_dict(self) -> None:
        field = {"display_value": "3 - Moderate", "value": ""}
        assert parse_labelled_int(field) == 3
