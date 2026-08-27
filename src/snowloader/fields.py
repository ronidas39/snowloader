"""Field shape helpers for ServiceNow API responses.

A ServiceNow field arrives in one of three shapes depending on the
``sysparm_display_value`` setting on the request:

    display_value=true   {"display_value": "David Loo", "link": "https://.../<sys_id>"}
    display_value=all    {"display_value": "David Loo", "value": "<sys_id>"}
    display_value=false  "<sys_id>"

Every one of those carries two different pieces of information: a label meant
for a human, and a value meant for a join. Reading the wrong half is easy and
fails quietly, so the helpers here always name which half they return.

Author: Roni Das
Created: 2026-08-27
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from snowloader.utils.parsing import parse_labelled_int  # noqa: F401

_SYS_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")

# The primary key is the one field that must never gain a companion key,
# because "sys_id_sys_id" would be nonsense.
_NO_COMPANION = frozenset({"sys_id"})


def is_sys_id(value: Any) -> bool:
    """Report whether a value looks like a ServiceNow sys_id.

    A sys_id is always 32 hexadecimal characters. Nothing else on a record
    has that shape often enough to matter, which makes it a reliable way to
    tell a reference field's value half from a choice field's.

    Args:
        value: Any field value.

    Returns:
        True if the value is a 32-character hex string.
    """
    if not isinstance(value, str):
        return False
    return _SYS_ID_PATTERN.match(value) is not None


def display_value(field: Any) -> str:
    """Extract the human-readable label from a field.

    Args:
        field: Raw field value from the API response.

    Returns:
        The label, or an empty string for None and empty values.
    """
    if field is None:
        return ""
    if isinstance(field, dict):
        return str(field.get("display_value", ""))
    return str(field)


def raw_value(field: Any) -> str:
    """Extract the joinable value from a field.

    Counterpart to :func:`display_value`. For a reference field this is the
    sys_id of the referenced record. For a choice field it is the stored
    choice key rather than its label. For a plain field both halves are the
    same string.

    With ``display_value=true`` the response carries no value key, so the
    sys_id is recovered from the link URL instead.

    Args:
        field: Raw field value from the API response.

    Returns:
        The value half, or an empty string for None and empty values.
    """
    if field is None:
        return ""
    if isinstance(field, dict):
        if "value" in field:
            return str(field["value"])
        link = str(field.get("link", ""))
        if link:
            return link.rsplit("/", 1)[-1]
        return str(field.get("display_value", ""))
    return str(field)


def parse_boolean(field: Any) -> bool:
    """Convert a ServiceNow boolean field to a Python bool.

    ServiceNow returns booleans as the strings ``"true"`` and ``"false"``,
    but depending on the display value setting they can also arrive as real
    booleans, as 0 and 1, or as None.

    Args:
        field: Raw field value from the API response.

    Returns:
        True if the field represents a truthy value, False otherwise.
    """
    if field is None:
        return False
    if isinstance(field, bool):
        return field
    return str(field).lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class ReferenceField:
    """Both halves of a ServiceNow field, kept together.

    Attributes:
        label: The human-readable display value, e.g. ``"Service Desk"``.
        value: The joinable value. A sys_id for a reference field, the
            stored choice key for a choice field, e.g. ``"5"`` where the
            label reads ``"5 - Planning"``.
    """

    label: str
    value: str

    def __bool__(self) -> bool:
        """A field with neither half populated is an empty reference."""
        return bool(self.label or self.value)

    def __str__(self) -> str:
        return self.label


def reference(record: dict[str, Any], name: str) -> ReferenceField:
    """Read one field off a record as both halves at once.

    Use this when a caller needs the sys_id to build a join and the label to
    show a person, without having to remember which accessor returns which.

    Args:
        record: Raw record dict from the ServiceNow API.
        name: Field name to read.

    Returns:
        A :class:`ReferenceField`. Missing fields come back empty rather
        than raising, so optional references do not need a guard.

    Example:
        >>> ci = reference(record, "cmdb_ci")
        >>> ci.value    # sys_id, joinable
        >>> ci.label    # readable
    """
    field = record.get(name)
    return ReferenceField(label=display_value(field), value=raw_value(field))


def _is_reference_shape(field: dict[str, Any], value: str) -> bool:
    """Decide whether a two-halved field points at another record.

    A ``link`` key is conclusive: only reference fields carry one. Without a
    link the sys_id shape of the value is the next best signal.
    """
    if "link" in field:
        return True
    return is_sys_id(value)


def expand_reference_keys(
    record: dict[str, Any],
    into: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten a record so every field's second half is reachable by name.

    Fields whose two halves differ gain a companion key alongside the label:

        ``assignment_group``          'Service Desk'
        ``assignment_group_sys_id``   'd625dcce...'

        ``priority``                  '5 - Planning'
        ``priority_value``            '5'

    The ``_sys_id`` suffix is used when the value half identifies another
    record, and ``_value`` when it does not, so a key named ``_sys_id``
    always holds something that can be joined on. Fields whose halves are
    identical, and fields that arrived as plain strings, are copied through
    unchanged with no companion.

    Existing keys in ``into`` are never overwritten. A loader that curates a
    metadata entry by hand keeps its version; expansion only fills gaps.

    Args:
        record: Raw record dict from the ServiceNow API.
        into: Optional dict to write into. A new dict is created when
            omitted.

    Returns:
        The dict that was written to.
    """
    target = {} if into is None else into

    for key, field in record.items():
        if not isinstance(field, dict):
            target.setdefault(key, field)
            continue

        label = display_value(field)
        value = raw_value(field)

        if key in _NO_COMPANION:
            # Both halves hold the same identifier, so store the plain string
            # and never derive a companion key from it.
            target.setdefault(key, value or label)
            continue

        target.setdefault(key, label)

        if not value or value == label:
            continue

        suffix = "_sys_id" if _is_reference_shape(field, value) else "_value"
        target.setdefault(f"{key}{suffix}", value)

    return target
