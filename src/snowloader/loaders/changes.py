"""Change request loader for snowloader.

Fetches change requests from the ServiceNow change_request table and formats
them into structured documents. The content layout emphasizes the change type,
risk level, implementation window (start/end dates), and assignment details
that are most relevant for LLM-based change analysis and advisory use cases.

Author: Roni Das
"""

from __future__ import annotations

import logging
from typing import Any

from snowloader.loaders.incidents import _display_value, _raw_value
from snowloader.models import BaseSnowLoader, SnowDocument

logger = logging.getLogger(__name__)


class ChangeLoader(BaseSnowLoader):
    """Loads change request records from ServiceNow.

    Produces documents that capture the full change lifecycle: what is
    being changed, the risk assessment, the implementation schedule, who
    is responsible, and which CI is affected. Optionally includes journal
    entries for CAB notes, implementation updates, and post-change reviews.

    Args:
        connection: An initialized SnowConnection instance.
        query: Optional encoded query for filtering change requests.
        fields: Optional field list override.
        include_journals: If True, fetches work notes and comments.

    Example:
        conn = SnowConnection(...)
        loader = ChangeLoader(conn, query="state=3")  # Implement state
        for doc in loader.lazy_load():
            print(doc.page_content[:200])
    """

    table = "change_request"
    content_fields = ["short_description", "description"]

    def _record_to_document(self, record: dict[str, Any]) -> SnowDocument:
        """Build a change request document from a raw API record.

        Args:
            record: Raw change_request record dict from the API.

        Returns:
            SnowDocument with formatted change request content and metadata.
        """
        number = _display_value(record.get("number"))
        summary = _display_value(record.get("short_description"))
        description = _display_value(record.get("description"))
        change_type = _display_value(record.get("type"))
        state = _display_value(record.get("state"))
        priority = _display_value(record.get("priority"))
        risk = _display_value(record.get("risk"))
        category = _display_value(record.get("category"))
        assigned_to = _display_value(record.get("assigned_to"))
        assignment_group = _display_value(record.get("assignment_group"))
        cmdb_ci = _display_value(record.get("cmdb_ci"))
        start_date = _display_value(record.get("start_date"))
        end_date = _display_value(record.get("end_date"))
        opened_at = _display_value(record.get("opened_at"))
        closed_at = _display_value(record.get("closed_at"))

        lines = [
            f"Change Request: {number}",
            f"Summary: {summary}",
        ]

        if description:
            lines.append(f"Description: {description}")

        lines.append(f"Type: {change_type}")
        lines.append(f"State: {state}")
        lines.append(f"Priority: {priority}")
        lines.append(f"Risk: {risk}")

        if category:
            lines.append(f"Category: {category}")
        if assigned_to:
            lines.append(f"Assigned To: {assigned_to}")
        if assignment_group:
            lines.append(f"Assignment Group: {assignment_group}")
        if cmdb_ci:
            lines.append(f"Configuration Item: {cmdb_ci}")

        # Implementation window is critical for change management
        if start_date:
            lines.append(f"Scheduled Start: {start_date}")
        if end_date:
            lines.append(f"Scheduled End: {end_date}")

        if opened_at:
            lines.append(f"Opened: {opened_at}")
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
            "source": f"servicenow://change_request/{number}",
            "type": change_type,
            "state": state,
            "priority": priority,
            "risk": risk,
            "category": category,
            "assigned_to": assigned_to,
            "cmdb_ci": _raw_value(record.get("cmdb_ci")),
            "start_date": start_date,
            "end_date": end_date,
            "sys_created_on": _display_value(record.get("sys_created_on")),
            "sys_updated_on": _display_value(record.get("sys_updated_on")),
        }

        return SnowDocument(page_content=page_content, metadata=metadata)
