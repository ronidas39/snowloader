"""Writing records out as JSONL, CSV or Excel.

JSONL was the only format the command could produce, which is the right
default for a pipeline and the wrong one for a person. A spreadsheet is what
most people actually open, and a CSV is what most other systems actually read.

Two things make this less trivial than it looks.

**Nested fields.** At ``display_value="all"`` every field arrives as
``{"display_value": ..., "value": ...}``. JSON keeps that happily; a CSV cell
cannot. Each such field is written as two columns, the label under the field's
own name and the identifier under ``<field>_value``, which matches how the
loaders already expand references.

**Column discovery.** A CSV needs its header before the first row is written,
and records stream. Taking the header from the first record is not enough: a
populated reference field arrives as a dict and an empty one as a bare string,
so the columns a record flattens to depend on which of its fields happen to be
filled in. Fifty incident rows produced one raw key set and twenty six
flattened ones.

So a bounded sample is read first and the header is the union of what it
flattens to. A record beyond the sample carrying a new column is a real
surprise rather than something to paper over, so it raises.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from snowloader.exceptions import SnowConnectionError

logger = logging.getLogger(__name__)

__all__ = ["FORMATS", "flatten_record", "write_csv", "write_jsonl", "write_records", "write_xlsx"]

FORMATS = ("jsonl", "csv", "xlsx")

# How many records to read before fixing the header. Large enough that a
# column appearing only on rarely populated fields is still caught, small
# enough that memory stays bounded on a half million row sweep.
HEADER_SAMPLE = 1000


def flatten_record(record: dict[str, Any]) -> dict[str, str]:
    """Turn one record into flat columns.

    A field carrying both halves becomes two columns: the readable label under
    the field's own name, and the identifier under ``<field>_value``. Anything
    else is stringified, because a spreadsheet cell has no other option.

    Args:
        record: One record as the API returned it.

    Returns:
        A flat mapping of column name to string value.

    Example:
        >>> flatten_record({"priority": {"display_value": "1 - Critical", "value": "1"}})
        {'priority': '1 - Critical', 'priority_value': '1'}
    """
    flat: dict[str, str] = {}
    for key, value in record.items():
        if isinstance(value, dict) and ("display_value" in value or "value" in value):
            flat[key] = str(value.get("display_value") or "")
            flat[f"{key}_value"] = str(value.get("value") or "")
        elif isinstance(value, (dict, list)):
            flat[key] = json.dumps(value, ensure_ascii=False)
        elif value is None:
            flat[key] = ""
        else:
            flat[key] = str(value)
    return flat


def write_jsonl(records: Iterable[dict[str, Any]], path: Path, append: bool = False) -> int:
    """Write one JSON object per line, exactly as the API returned it.

    Args:
        records: Records to write.
        path: Destination file.
        append: Add to the file rather than replacing it.

    Returns:
        How many records were written.
    """
    written = 0
    with path.open("a" if append else "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
    return written


def write_csv(records: Iterable[dict[str, Any]], path: Path, append: bool = False) -> int:
    """Write records as CSV, flattening any field that carries both halves.

    Args:
        records: Records to write.
        path: Destination file.
        append: Add rows to an existing file, whose header is reused.

    Returns:
        How many records were written.

    Raises:
        SnowConnectionError: If a record beyond the header sample carries a
            column the header does not cover, which would silently lose data.
    """
    stream = iter(records)
    sample, header = _sample_header(stream)
    if not sample:
        if not append:
            path.write_text("", encoding="utf-8")
        return 0

    mode = "a" if append and path.exists() and path.stat().st_size else "w"
    written = 0
    with path.open(mode, encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="raise", restval="")
        if mode == "w":
            writer.writeheader()
        for record in _chain_all(sample, stream):
            row = flatten_record(record)
            unexpected = set(row) - set(header)
            if unexpected:
                raise SnowConnectionError(
                    f"Record {written + 1} carries columns the header does not "
                    f"cover: {sorted(unexpected)}.",
                    detail=(
                        f"The header is the union of the first {HEADER_SAMPLE} "
                        "records, because a CSV needs its columns before any "
                        "row is written. A record beyond that carrying a new "
                        "field would lose those values silently. Pass an "
                        "explicit field list to the sweep so every record has "
                        "the same shape."
                    ),
                )
            writer.writerow(row)
            written += 1
    return written


def write_xlsx(records: Iterable[dict[str, Any]], path: Path, sheet: str = "records") -> int:
    """Write records to an Excel workbook.

    Args:
        records: Records to write.
        path: Destination ``.xlsx`` file.
        sheet: Worksheet name.

    Returns:
        How many records were written.

    Raises:
        SnowConnectionError: If openpyxl is not installed, or a record carries
            a column the header does not cover.
    """
    try:
        # openpyxl publishes stubs as a separate types- package. Requiring it
        # would add a dependency for the sake of a type checker on an import
        # that only runs when Excel output is asked for.
        from openpyxl import Workbook  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised by the message
        raise SnowConnectionError(
            "Excel output needs openpyxl.",
            detail="Install it with: pip install 'snowloader[excel]'",
        ) from exc

    stream = iter(records)
    sample, header = _sample_header(stream)
    book = Workbook(write_only=True)
    page = book.create_sheet(title=sheet[:31] or "records")

    written = 0
    if sample:
        page.append(header)
        for record in _chain_all(sample, stream):
            row = flatten_record(record)
            unexpected = set(row) - set(header)
            if unexpected:
                raise SnowConnectionError(
                    f"Record {written + 1} carries columns the header does not "
                    f"cover: {sorted(unexpected)}.",
                    detail="Pass an explicit field list so every record matches.",
                )
            page.append([row.get(column, "") for column in header])
            written += 1
    book.save(str(path))
    return written


def write_records(
    records: Iterable[dict[str, Any]],
    path: Path,
    fmt: str = "jsonl",
    append: bool = False,
) -> int:
    """Write records in whichever format was asked for.

    Args:
        records: Records to write.
        path: Destination file.
        fmt: One of ``jsonl``, ``csv`` or ``xlsx``.
        append: Add to the file rather than replacing it. Excel cannot append,
            because a workbook is rewritten whole.

    Returns:
        How many records were written.

    Raises:
        SnowConnectionError: On an unknown format, or on appending to Excel.
    """
    if fmt not in FORMATS:
        raise SnowConnectionError(f"Unknown format '{fmt}'. Choose one of {', '.join(FORMATS)}.")
    if fmt == "xlsx":
        if append:
            raise SnowConnectionError(
                "Excel output cannot be appended to.",
                detail=(
                    "A workbook is written whole, so resuming into one would "
                    "rewrite it from the records of this run alone. Use jsonl "
                    "or csv for a resumable extraction and convert afterwards."
                ),
            )
        return write_xlsx(records, path)
    if fmt == "csv":
        return write_csv(records, path, append=append)
    return write_jsonl(records, path, append=append)


def _sample_header(
    stream: Iterator[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read enough records to know the columns, keeping their order.

    Column order follows first appearance rather than sorting, so a file opened
    by a person reads in the order the table declares its fields.
    """
    sample: list[dict[str, Any]] = []
    header: list[str] = []
    seen: set[str] = set()
    for record in stream:
        sample.append(record)
        for column in flatten_record(record):
            if column not in seen:
                seen.add(column)
                header.append(column)
        if len(sample) >= HEADER_SAMPLE:
            break
    return sample, header


def _chain_all(
    sample: list[dict[str, Any]], rest: Iterator[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """Put the sampled records back in front of the stream."""
    yield from sample
    yield from rest
