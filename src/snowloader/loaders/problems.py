"""Problem record loader for snowloader.

Fetches problem records from the ServiceNow problem table and formats them
into documents that capture the problem lifecycle: initial description, root
cause analysis, known error status, and fix notes. This is particularly
valuable for LLM use cases around incident correlation and proactive problem
management.

Author: Roni Das
"""

from __future__ import annotations

import logging
from typing import Any

from snowloader.loaders.incidents import _display_value, _raw_value
from snowloader.models import BaseSnowLoader, SnowDocument

logger = logging.getLogger(__name__)


class ProblemLoader(BaseSnowLoader):
    """Loads problem records from ServiceNow.

    Produces documents that include the problem description, root cause
    analysis (when available), known error flagging, and fix notes. This
    gives language models the context they need for pattern recognition
    across incidents and proactive problem identification.

    Args:
        connection: An initialized SnowConnection instance.
        query: Optional encoded query for filtering problems.
        fields: Optional field list override.
        include_journals: If True, fetches work notes and comments.

    Example:
        conn = SnowConnection(...)
        loader = ProblemLoader(conn, query="known_error=true")
        for doc in loader.lazy_load():
            print(doc.page_content[:200])
    """

    table = "problem"
    content_fields = ["short_description", "description"]

    def _record_to_document(self, record: dict[str, Any]) -> SnowDocument:
        """Build a problem document from a raw API record.

        Args:
            record: Raw problem record dict from the API.

        Returns:
            SnowDocument with formatted problem content and metadata.
        """
        number = _display_value(record.get("number"))
        summary = _display_value(record.get("short_description"))
        description = _display_value(record.get("description"))
        state = _display_value(record.get("state"))
        priority = _display_value(record.get("priority"))
        category = _display_value(record.get("category"))
        assigned_to = _display_value(record.get("assigned_to"))
        assignment_group = _display_value(record.get("assignment_group"))
        cmdb_ci = _display_value(record.get("cmdb_ci"))
        cause_notes = _display_value(record.get("cause_notes"))
        known_error = _display_value(record.get("known_error"))
        fix_notes = _display_value(record.get("fix_notes"))
        opened_at = _display_value(record.get("opened_at"))
        resolved_at = _display_value(record.get("resolved_at"))
        closed_at = _display_value(record.get("closed_at"))

        lines = [
            f"Problem: {number}",
            f"Summary: {summary}",
        ]

        if description:
            lines.append(f"Description: {description}")

        lines.append(f"State: {state}")
        lines.append(f"Priority: {priority}")

        if category:
            lines.append(f"Category: {category}")
        if assigned_to:
            lines.append(f"Assigned To: {assigned_to}")
        if assignment_group:
            lines.append(f"Assignment Group: {assignment_group}")
        if cmdb_ci:
            lines.append(f"Configuration Item: {cmdb_ci}")

        # Root cause and known error info is the most valuable part
        if cause_notes:
            lines.append(f"Root Cause: {cause_notes}")

        is_known_error = str(known_error).lower() == "true" if known_error else False
        if is_known_error:
            lines.append("Known Error: Yes")
            if fix_notes:
                lines.append(f"Fix: {fix_notes}")

        if opened_at:
            lines.append(f"Opened: {opened_at}")
        if resolved_at:
            lines.append(f"Resolved: {resolved_at}")
        if closed_at:
            lines.append(f"Closed: {closed_at}")

        page_content = "\n".join(lines)

        sys_id = str(record.get("sys_id", ""))
        if self._include_journals and sys_id:
            journals = self._fetch_journals(sys_id)
            journal_text = self._format_journals(journals)
            if journal_text:
                page_content = page_content + "\n\n" + journal_text

        metadata: dict[str, Any] = {
            "sys_id": sys_id,
            "number": number,
            "table": self.table,
            "source": f"servicenow://problem/{number}",
            "state": state,
            "priority": priority,
            "category": category,
            "assigned_to": assigned_to,
            "known_error": is_known_error,
            "cmdb_ci": _raw_value(record.get("cmdb_ci")),
            "opened_at": opened_at,
            "resolved_at": resolved_at,
            "sys_created_on": _display_value(record.get("sys_created_on")),
            "sys_updated_on": _display_value(record.get("sys_updated_on")),
        }

        return SnowDocument(page_content=page_content, metadata=metadata)
