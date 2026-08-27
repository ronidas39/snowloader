"""Generic loader for any ServiceNow table.

snowloader ships a purpose-built loader for six tables. ServiceNow has
thousands, and the ones a given site cares about are rarely all in that six.
This loader covers the rest: point it at a table name and it returns the same
SnowDocument shape as everything else, with metadata carrying both halves of
every reference field.

Author: Roni Das
Created: 2026-08-27
"""

from __future__ import annotations

import logging
from typing import Any

from snowloader.connection import SnowConnection, SnowConnectionError
from snowloader.loaders._field_utils import display_value as _display_value
from snowloader.loaders._field_utils import raw_value as _raw_value
from snowloader.models import BaseSnowLoader, SnowDocument

logger = logging.getLogger(__name__)

# Text-bearing columns, in the order a reader would want them. Used only when
# the caller does not say which fields carry the document text. These cover
# the task, cmdb, sys and sc table families between them.
_CANDIDATE_CONTENT_FIELDS = (
    "short_description",
    "description",
    "name",
    "title",
    "text",
    "comments",
    "close_notes",
    "work_notes",
)


class TableLoader(BaseSnowLoader):
    """Loads records from any ServiceNow table.

    Page content is assembled from ``content_fields``. When those are not
    given the loader uses whichever of the usual text columns the record
    actually has, so an unfamiliar table still produces something readable
    rather than an empty document.

    Metadata is where the value is for anything other than retrieval: every
    field on the record reaches it, and any reference field arrives as both
    the label and the sys_id it points at.

    Args:
        connection: An initialized SnowConnection instance.
        table: ServiceNow table name, e.g. ``"sc_task"`` or ``"sys_user"``.
        query: Optional encoded query for filtering records.
        fields: Optional field list. When omitted the API returns every
            field on the table.
        content_fields: Field names whose values make up page_content, in
            order. When omitted, chosen per record from the usual text
            columns.
        include_journals: Fetch work notes and comments for each record.
            Only meaningful on tables that extend ``task``.
        expand_references: Surface both halves of every field in metadata.
            Defaults to True.
        include_raw: Attach the untouched API record under ``"raw"``.

    Raises:
        SnowConnectionError: If table is empty.

    Example:
        >>> loader = TableLoader(conn, table="sc_task", query="active=true")
        >>> for doc in loader.lazy_load():
        ...     print(doc.metadata["assignment_group_sys_id"])
    """

    def __init__(
        self,
        connection: SnowConnection,
        table: str,
        query: str | None = None,
        fields: list[str] | None = None,
        content_fields: list[str] | None = None,
        include_journals: bool = False,
        expand_references: bool = True,
        include_raw: bool = False,
    ) -> None:
        if not table or not table.strip():
            raise SnowConnectionError(
                "TableLoader needs a table name.",
                detail="Pass the ServiceNow table you want to read, e.g. 'sc_task'.",
            )

        super().__init__(
            connection=connection,
            query=query,
            fields=fields,
            include_journals=include_journals,
            expand_references=expand_references,
            include_raw=include_raw,
        )
        self.table = table.strip()
        self.content_fields = list(content_fields) if content_fields else []

    def _record_to_document(self, record: dict[str, Any]) -> SnowDocument:
        """Build a document from a record on an arbitrary table.

        Args:
            record: Raw record dict from the ServiceNow API.

        Returns:
            SnowDocument with the record's text as content and every field
            in metadata.
        """
        names = self.content_fields or self._guess_content_fields(record)

        parts = []
        for name in names:
            text = _display_value(record.get(name))
            if text:
                parts.append(text)
        page_content = "\n".join(parts)

        sys_id = _raw_value(record.get("sys_id"))
        if self._include_journals and sys_id:
            journal_text = self._format_journals(self._fetch_journals(sys_id))
            if journal_text:
                page_content = page_content + "\n\n" + journal_text

        metadata: dict[str, Any] = {
            "sys_id": sys_id,
            "table": self.table,
            "source": f"servicenow://{self.table}/{sys_id}",
        }

        return SnowDocument(
            page_content=page_content,
            metadata=self._build_metadata(record, metadata),
        )

    @staticmethod
    def _guess_content_fields(record: dict[str, Any]) -> list[str]:
        """Pick the text columns this record actually has.

        Args:
            record: Raw record dict from the ServiceNow API.

        Returns:
            Candidate field names present on the record, in reading order.
            Empty when the table carries no recognisable text, which is
            normal for link tables.
        """
        return [name for name in _CANDIDATE_CONTENT_FIELDS if name in record]
