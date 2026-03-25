"""Shared field extraction utilities for ServiceNow API responses.

These helpers normalize the varied shapes that ServiceNow fields can
take depending on the ``sysparm_display_value`` setting. Every loader
in the package uses them to safely pull human-readable text and raw
sys_id values from record dicts.

Author: Roni Das
"""

from __future__ import annotations

from typing import Any


def display_value(field: Any) -> str:
    """Extract the human-readable display value from a field.

    ServiceNow reference fields come back in different shapes depending
    on the ``sysparm_display_value`` setting:

        - ``"true"``:  ``{"display_value": "John Smith", "link": "..."}``
        - ``"all"``:   ``{"display_value": "John Smith", "value": "abc123"}``
        - ``"false"``: ``"abc123"`` (plain string)
        - Empty:       ``None`` or ``""``

    This function normalizes all of them into a simple string.

    Args:
        field: Raw field value from the API response.

    Returns:
        The display string, or empty string for None/empty values.
    """
    if field is None:
        return ""
    if isinstance(field, dict):
        return str(field.get("display_value", ""))
    return str(field)


def raw_value(field: Any) -> str:
    """Extract the underlying sys_id or raw value from a field.

    Counterpart to :func:`display_value`. When we need the actual sys_id
    behind a reference field (for linking, dedup, etc.), this pulls the
    ``value`` key from the dict format. With ``sysparm_display_value=true``,
    reference fields arrive as ``{"display_value": "...", "link": "..."}``
    so we fall back to extracting the sys_id from the link URL.

    Args:
        field: Raw field value from the API response.

    Returns:
        The raw value string, or empty string for None/empty values.
    """
    if field is None:
        return ""
    if isinstance(field, dict):
        # sysparm_display_value=all → {"display_value": "...", "value": "sys_id"}
        if "value" in field:
            return str(field["value"])
        # sysparm_display_value=true → {"display_value": "...", "link": "https://.../sys_id"}
        link = str(field.get("link", ""))
        if link:
            return link.rsplit("/", 1)[-1]
        return str(field.get("display_value", ""))
    return str(field)


def parse_boolean(field: Any) -> bool:
    """Convert a ServiceNow boolean field to a Python bool.

    ServiceNow returns boolean fields as strings (``"true"``/``"false"``),
    but depending on the display_value setting they might also come back
    as actual booleans, integers (0/1), or None.

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
