"""Incident loader for snowloader.

Fetches IT incident records from the ServiceNow incident table and converts
them into structured SnowDocuments suitable for LLM consumption. The document
content is formatted as a readable text block rather than raw JSON, so language
models can parse and reason about incidents without extra preprocessing.

Reference fields (assigned_to, assignment_group, cmdb_ci, etc.) are resolved
to their display values automatically. ServiceNow returns these as
{display_value, value} dicts when you set sysparm_display_value=all, and we
handle both that format and plain strings transparently through the helper
functions at the bottom of this module.

Author: Roni Das
"""

from __future__ import annotations

import logging
from typing import Any

from snowloader.loaders._field_utils import display_value as _display_value
from snowloader.loaders._field_utils import raw_value as _raw_value
from snowloader.models import BaseSnowLoader, SnowDocument

logger = logging.getLogger(__name__)


class IncidentLoader(BaseSnowLoader):
    """Loads incident records from ServiceNow.

    Produces documents with a structured text layout that includes the
    incident number, summary, full description, current state, priority,
    category, assignment info, relevant dates, and optionally the resolution
    notes and journal entries (work notes + comments).

    The text format is designed to give language models enough context to
    answer questions about incidents without needing to understand ServiceNow's
    data model. Each section is clearly labeled so retrieval systems can
    match on specific parts of the content.

    Args:
        connection: An initialized SnowConnection instance.
        query: Optional encoded query for filtering incidents.
        fields: Optional field list. If not set, the loader requests all
            fields needed for document assembly.
        include_journals: If True, fetches work notes and comments from
            sys_journal_field and appends them to each document.

    Example:
        conn = SnowConnection(
            instance_url="https://mycompany.service-now.com",
            username="api_user",
            password="api_pass",
        )
        loader = IncidentLoader(conn, query="active=true^priority<=2")
        for doc in loader.lazy_load():
            print(doc.page_content[:200])
    """

    table = "incident"
    content_fields = ["short_description", "description"]

    def _record_to_document(self, record: dict[str, Any]) -> SnowDocument:
        """Build a structured incident document from a raw API record.

        Overrides the base class to produce a richer text format that
        includes all the fields an LLM would need to understand and
        reason about an incident.

        Args:
            record: Raw incident record dict from the ServiceNow API.

        Returns:
            SnowDocument with formatted incident content and metadata.
        """
        number = _display_value(record.get("number"))
        summary = _display_value(record.get("short_description"))
        description = _display_value(record.get("description"))
        state = _display_value(record.get("state"))
        priority = _display_value(record.get("priority"))
        category = _display_value(record.get("category"))
        subcategory = _display_value(record.get("subcategory"))
        assigned_to = _display_value(record.get("assigned_to"))
        assignment_group = _display_value(record.get("assignment_group"))
        cmdb_ci = _display_value(record.get("cmdb_ci"))
        opened_at = _display_value(record.get("opened_at"))
        resolved_at = _display_value(record.get("resolved_at"))
        closed_at = _display_value(record.get("closed_at"))
        close_notes = _display_value(record.get("close_notes"))

        # Assemble the main content block. Each line is labeled so that
        # both humans and language models can easily find what they need.
        lines = [
            f"Incident: {number}",
            f"Summary: {summary}",
        ]

        if description:
            lines.append(f"Description: {description}")

        lines.append(f"State: {state}")
        lines.append(f"Priority: {priority}")

        if category:
            cat_str = category
            if subcategory:
                cat_str = f"{category} / {subcategory}"
            lines.append(f"Category: {cat_str}")

        if assigned_to:
            lines.append(f"Assigned To: {assigned_to}")
        if assignment_group:
            lines.append(f"Assignment Group: {assignment_group}")
        if cmdb_ci:
            lines.append(f"Configuration Item: {cmdb_ci}")

        if opened_at:
            lines.append(f"Opened: {opened_at}")
        if resolved_at:
            lines.append(f"Resolved: {resolved_at}")
        if closed_at:
            lines.append(f"Closed: {closed_at}")

        if close_notes:
            lines.append(f"Resolution Notes: {close_notes}")

        page_content = "\n".join(lines)

        # Append journal entries if requested
        sys_id = str(record.get("sys_id", ""))
        if self._include_journals and sys_id:
            journals = self._fetch_journals(sys_id)
            journal_text = self._format_journals(journals)
            if journal_text:
                page_content = page_content + "\n\n" + journal_text

        # Build metadata with both display values (for humans) and raw
        # values (for programmatic linking back to ServiceNow)
        metadata: dict[str, Any] = {
            "sys_id": sys_id,
            "number": number,
            "table": self.table,
            "source": f"servicenow://incident/{number}",
            "state": _display_value(record.get("state")),
            "priority": _display_value(record.get("priority")),
            "category": category,
            "assigned_to": assigned_to,
            "assignment_group": assignment_group,
            "cmdb_ci": _raw_value(record.get("cmdb_ci")),
            "opened_at": opened_at,
            "resolved_at": resolved_at,
            "closed_at": closed_at,
            "sys_created_on": _display_value(record.get("sys_created_on")),
            "sys_updated_on": _display_value(record.get("sys_updated_on")),
        }

        return SnowDocument(page_content=page_content, metadata=metadata)
