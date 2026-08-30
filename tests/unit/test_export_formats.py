"""Writing records out as CSV and Excel, not only JSONL.

JSONL is the right default for a pipeline and the wrong one for a person.
The awkward part is that at ``display_value="all"`` every field arrives as a
two-part dict, which JSON keeps happily and a spreadsheet cell cannot.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from snowloader.exceptions import SnowConnectionError
from snowloader.export import flatten_record, write_csv, write_jsonl, write_records, write_xlsx

BOTH = {"display_value": "1 - Critical", "value": "1"}


def test_a_two_part_field_becomes_two_columns() -> None:
    flat = flatten_record({"number": "INC001", "priority": BOTH})
    assert flat == {"number": "INC001", "priority": "1 - Critical", "priority_value": "1"}


def test_a_nested_structure_survives_as_json() -> None:
    flat = flatten_record({"tags": ["a", "b"]})
    assert json.loads(flat["tags"]) == ["a", "b"]


def test_none_becomes_an_empty_cell_not_the_word_none() -> None:
    assert flatten_record({"resolved_at": None})["resolved_at"] == ""


def test_csv_round_trips(tmp_path: Path) -> None:
    out = tmp_path / "x.csv"
    n = write_csv([{"number": "INC001", "priority": BOTH}], out)
    rows = list(csv.DictReader(out.open()))
    assert n == 1
    assert rows[0]["priority"] == "1 - Critical"
    assert rows[0]["priority_value"] == "1"


def test_heterogeneous_records_inside_the_sample_are_covered(tmp_path: Path) -> None:
    """A populated reference arrives as a dict and an empty one as a string,
    so the columns a record flattens to vary row by row. The header is the
    union across the sample rather than whatever the first row happened to
    have."""
    out = tmp_path / "x.csv"
    n = write_csv([{"a": "1"}, {"a": "1", "b": "2"}], out)
    rows = list(csv.DictReader(out.open()))
    assert n == 2
    assert rows[0]["b"] == ""
    assert rows[1]["b"] == "2"


def test_csv_refuses_a_new_column_appearing_beyond_the_sample(tmp_path: Path) -> None:
    """Past the sample the header is fixed, and a record with a column it does
    not cover would lose those values silently."""
    from snowloader.export import HEADER_SAMPLE

    out = tmp_path / "x.csv"
    records = [{"a": str(i)} for i in range(HEADER_SAMPLE)] + [{"a": "x", "surprise": "y"}]
    with pytest.raises(SnowConnectionError, match="header"):
        write_csv(records, out)


def test_an_empty_sweep_writes_an_empty_file(tmp_path: Path) -> None:
    out = tmp_path / "x.csv"
    assert write_csv([], out) == 0
    assert out.exists()


def test_csv_append_does_not_repeat_the_header(tmp_path: Path) -> None:
    out = tmp_path / "x.csv"
    write_csv([{"a": "1"}], out)
    write_csv([{"a": "2"}], out, append=True)
    assert out.read_text().count("a\n") == 1
    assert len(list(csv.DictReader(out.open()))) == 2


def test_jsonl_keeps_the_original_shape(tmp_path: Path) -> None:
    out = tmp_path / "x.jsonl"
    write_jsonl([{"priority": BOTH}], out)
    assert json.loads(out.read_text())["priority"] == BOTH


def test_xlsx_is_written_and_readable(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    from openpyxl import load_workbook

    out = tmp_path / "x.xlsx"
    n = write_xlsx([{"number": "INC001", "priority": BOTH}], out)
    rows = list(load_workbook(out).active.values)
    assert n == 1
    assert rows[0] == ("number", "priority", "priority_value")
    assert rows[1] == ("INC001", "1 - Critical", "1")


def test_an_unknown_format_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SnowConnectionError, match="Unknown format"):
        write_records([{"a": "1"}], tmp_path / "x.parquet", fmt="parquet")


def test_excel_cannot_be_appended_to(tmp_path: Path) -> None:
    """A workbook is rewritten whole, so resuming into one would silently drop
    everything the earlier run wrote."""
    with pytest.raises(SnowConnectionError, match="append"):
        write_records([{"a": "1"}], tmp_path / "x.xlsx", fmt="xlsx", append=True)


def test_write_records_dispatches_on_format(tmp_path: Path) -> None:
    for fmt, name in (("jsonl", "a.jsonl"), ("csv", "a.csv")):
        out = tmp_path / name
        assert write_records([{"a": "1"}], out, fmt=fmt) == 1
        assert out.stat().st_size > 0
