"""Parsing helpers for ServiceNow field values.

ServiceNow's Table API returns the same field in different shapes depending
on the ``sysparm_display_value`` setting. These helpers normalize the common
cases so user code does not need to special-case each shape.

Author: Roni Das
"""

from __future__ import annotations

from typing import Any


def parse_labelled_int(field: Any) -> int | None:
    """Convert a ServiceNow labelled integer field to a Python int.

    Fields like ``priority``, ``urgency``, ``impact``, and ``severity`` come
    back from the Table API as labelled strings ("3 - Moderate") rather than
    plain integers. The exact shape depends on ``sysparm_display_value``:

        - ``"true"``:  ``"3 - Moderate"`` or ``{"display_value": "3 - Moderate", ...}``
        - ``"all"``:   ``{"display_value": "3 - Moderate", "value": "3"}``
        - ``"false"``: ``"3"``

    Calling :func:`int` directly on ``"3 - Moderate"`` raises ``ValueError``.
    This helper handles every shape and returns a clean integer, or ``None``
    if the field is missing or cannot be parsed.

    Args:
        field: Raw field value from the API response.

    Returns:
        The integer value (e.g. 3), or None for missing / unparseable values.

    Example:
        >>> parse_labelled_int({"display_value": "3 - Moderate", "value": "3"})
        3
        >>> parse_labelled_int("1 - Critical")
        1
        >>> parse_labelled_int(None)
        >>> parse_labelled_int("Critical")
    """
    if field is None:
        return None
    if isinstance(field, bool):
        return None
    if isinstance(field, int):
        return field
    if isinstance(field, dict):
        raw = field.get("value")
        if raw not in (None, ""):
            try:
                return int(str(raw).strip())
            except (ValueError, TypeError):
                pass
        disp = field.get("display_value")
        if disp not in (None, ""):
            return _leading_int(str(disp))
        return None
    text = str(field).strip()
    if not text:
        return None
    return _leading_int(text)


def _leading_int(text: str) -> int | None:
    """Return the leading integer from a string like ``"3 - Moderate"``.

    Returns None if the string does not start with digits.
    """
    head = text.strip().split()[0].rstrip("-").strip() if text.strip() else ""
    if not head:
        return None
    try:
        return int(head)
    except (ValueError, TypeError):
        return None
