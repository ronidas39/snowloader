"""Core document model and base loader for snowloader.

This module defines the two building blocks that everything else in snowloader
depends on:

    SnowDocument: A framework-agnostic container for document content and metadata.
        Intentionally kept simple so it can be converted to LangChain Documents,
        LlamaIndex Documents, or any other format with minimal fuss.

    BaseSnowLoader: Abstract base class for all table-specific loaders. Provides
        the shared machinery for fetching records through SnowConnection, converting
        them to SnowDocuments, handling delta sync via load_since(), and pulling
        journal entries (work notes / comments) from sys_journal_field.

Subclasses only need to set a couple of class attributes (table name, content
fields) and optionally override _record_to_document() if they need custom
content assembly logic.

Author: Roni Das
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from snowloader.connection import SnowConnection, SnowConnectionError
from snowloader.fields import display_value, expand_reference_keys, raw_value

logger = logging.getLogger(__name__)


@dataclass
class SnowDocument:
    """A single document extracted from a ServiceNow table.

    This is the intermediate format that lives between the raw API response
    and whatever the framework adapters produce. Every loader yields these,
    and every adapter consumes them.

    Attributes:
        page_content: The main text content of the document. How this is
            assembled depends on the specific loader (could be a short
            description, a KB article body, a concatenation of fields, etc).
        metadata: Key-value pairs describing where this document came from.
            Typically includes sys_id, number, table name, and any other
            fields the loader considers useful for retrieval or filtering.
    """

    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseSnowLoader:
    """Shared foundation for all ServiceNow table loaders.

    Subclasses must define two class attributes:

    - ``table``: the ServiceNow table name to query, for example
      ``"incident"``.
    - ``content_fields``: field names whose values get concatenated into the
      document's ``page_content``.

    The base class takes care of pagination, document assembly, delta sync,
    and journal fetching. Most loaders will not need to override anything
    beyond the class attributes, but _record_to_document() is available
    as a hook for loaders that need fancier content formatting.

    Args:
        connection: An initialized SnowConnection instance.
        query: Optional encoded query string for filtering records.
        fields: Optional list of specific fields to request from the API.
            When left as None, the API returns all fields on the table.
        include_journals: Whether to fetch and append work notes and
            comments from sys_journal_field for each record.
        expand_references: When True (the default), every field on the
            record reaches metadata, and any field whose two halves differ
            gains a companion key: ``assignment_group`` holds the label and
            ``assignment_group_sys_id`` holds the identifier you can join
            on. Set it False to get only the fields the loader curates,
            which is the behaviour before 0.3.0.
        include_raw: When True, the untouched API record is attached to
            metadata under ``"raw"``. Useful when something downstream needs
            a field the loader does not surface, at the cost of holding two
            copies of every record.

    Example:
        .. code-block:: python

            class IncidentLoader(BaseSnowLoader):
                table = "incident"
                content_fields = ["short_description", "description"]

            conn = SnowConnection(...)
            loader = IncidentLoader(connection=conn, query="active=true")
            for doc in loader.lazy_load():
                print(doc.page_content)
    """

    # Subclasses must set these
    table: str = ""
    content_fields: list[str] = []

    def __init__(
        self,
        connection: SnowConnection,
        query: str | None = None,
        fields: list[str] | None = None,
        include_journals: bool = False,
        expand_references: bool = True,
        include_raw: bool = False,
    ) -> None:
        self._connection = connection
        self._query = query
        self._fields = fields
        self._include_journals = include_journals
        self._expand_references = expand_references
        self._include_raw = include_raw

    def load(self, verify: bool = False, on_error: str = "raise") -> list[SnowDocument]:
        """Fetch all matching records and return them as a list.

        This is the simple, non-streaming interface. Under the hood it
        just drains lazy_load() into a list. For large tables, prefer
        lazy_load() directly to avoid holding everything in memory.

        Args:
            verify: Raise if the sweep did not return every record the
                instance reports. See
                :meth:`snowloader.SnowConnection.get_records`.
            on_error: ``"raise"`` (default) or ``"skip"``.

        Returns:
            List of SnowDocument instances, one per record.

        Raises:
            SweepIncompleteError: If ``verify`` is set and the sweep came up
                short.
        """
        return list(self.lazy_load(verify=verify, on_error=on_error))

    def lazy_load(
        self,
        since: datetime | None = None,
        verify: bool = False,
        on_error: str = "raise",
    ) -> Generator[SnowDocument, None, None]:
        """Fetch records and yield them one at a time as SnowDocuments.

        This is the primary loading interface. It streams records through
        SnowConnection's paginated API and converts each one to a document
        on the fly. Memory usage stays flat regardless of how many records
        are in the table.

        Args:
            since: Optional cutoff datetime for delta sync. When set,
                only records changed after this point are fetched.
            verify: Raise if the sweep did not return every record the
                instance reports.
            on_error: ``"raise"`` (default) or ``"skip"``.

        Yields:
            SnowDocument instances, one per ServiceNow record.

        Raises:
            SweepIncompleteError: If ``verify`` is set and the sweep came up
                short.
        """
        records = self._connection.get_records(
            table=self.table,
            query=self._query,
            fields=self._fields,
            since=since,
            verify=verify,
            on_error=on_error,
        )

        for record in records:
            doc = self._record_to_document(record)
            yield doc

    def load_since(self, since: datetime) -> list[SnowDocument]:
        """Fetch only records updated after the given datetime.

        Convenience wrapper around lazy_load() for incremental syncing.
        Pass the timestamp of your last successful sync and you will only
        get records that changed since then.

        Args:
            since: Cutoff datetime. Records with sys_updated_on after
                this value are included.

        Returns:
            List of SnowDocument instances for the updated records.
        """
        return list(self.lazy_load(since=since))

    def concurrent_lazy_load(
        self,
        since: datetime | None = None,
        max_workers: int = 16,
        verify: bool = False,
        on_error: str = "raise",
    ) -> Generator[SnowDocument, None, None]:
        """Fetch records in parallel and yield them as SnowDocuments.

        This is the threaded counterpart to lazy_load(). It dispatches page
        fetches across a ThreadPoolExecutor inside SnowConnection, so wall
        clock time on large tables drops roughly proportional to max_workers
        (subject to ServiceNow rate limits and instance capacity). Memory
        stays flat because results are still streamed as they arrive.

        Records are yielded in the order pages complete, which is not the
        same as sys_created_on order. If you need a stable ordering, sort
        downstream or use lazy_load() instead.

        Args:
            since: Optional cutoff datetime for delta sync. When set,
                only records updated after this point are fetched.
            max_workers: Number of worker threads to use for page fetches.
                Defaults to 16, which is where measured throughput flattens.
                Higher values speed up large tables but may trip ServiceNow
                rate limits on smaller instances.
            verify: Raise if the sweep did not return every record the
                instance reports. Free on this path, because the count it
                checks against was already fetched to plan the pages.
            on_error: ``"raise"`` (default) or ``"skip"``.

        Yields:
            SnowDocument instances, one per ServiceNow record, in the
            order their pages complete (not sys_created_on order).

        Raises:
            SweepIncompleteError: If ``verify`` is set and the sweep came up
                short.
        """
        records = self._connection.concurrent_get_records(
            table=self.table,
            query=self._query,
            fields=self._fields,
            since=since,
            max_workers=max_workers,
            verify=verify,
            on_error=on_error,
        )

        for record in records:
            yield self._record_to_document(record)

    def concurrent_load(
        self,
        max_workers: int = 16,
        verify: bool = False,
        on_error: str = "raise",
    ) -> list[SnowDocument]:
        """Fetch all matching records in parallel and return them as a list.

        Threaded counterpart to load(). Drains concurrent_lazy_load() into
        a list, so the same ordering caveat applies: documents come back
        in page-completion order, not sys_created_on order. For very large
        tables, prefer concurrent_lazy_load() to keep memory bounded.

        Args:
            max_workers: Number of worker threads to use for page fetches.
                Defaults to 16.
            verify: Raise if the sweep did not return every record.
            on_error: ``"raise"`` (default) or ``"skip"``.

        Returns:
            List of SnowDocument instances, one per record, in the order
            their pages completed.

        Raises:
            SweepIncompleteError: If ``verify`` is set and the sweep came up
                short.
        """
        return list(
            self.concurrent_lazy_load(
                max_workers=max_workers,
                verify=verify,
                on_error=on_error,
            )
        )

    def _record_to_document(self, record: dict[str, Any]) -> SnowDocument:
        """Convert a single API record dict into a SnowDocument.

        Concatenates the values of content_fields into page_content,
        separated by newlines, reading the label half of each so a field that
        arrived as a two-halved dict does not land in the text as the string
        form of that dict. Everything else goes to metadata via
        :meth:`_build_metadata`. Subclasses can override this for custom
        assembly logic.

        Args:
            record: Raw record dict from the ServiceNow API.

        Returns:
            A SnowDocument with assembled content and metadata.
        """
        content_parts = []
        for field_name in self.content_fields:
            text = display_value(record.get(field_name))
            if text:
                content_parts.append(text)

        page_content = "\n".join(content_parts)

        # If journals are requested, fetch and append them.
        # Journal fetch is resilient - failures are logged, not raised,
        # so a single inaccessible journal table does not crash the load.
        sys_id = raw_value(record.get("sys_id"))
        if self._include_journals and sys_id:
            journals = self._fetch_journals(sys_id)
            journal_text = self._format_journals(journals)
            if journal_text:
                page_content = page_content + "\n\n" + journal_text

        metadata = self._build_metadata(record, {"table": self.table, "sys_id": sys_id})

        return SnowDocument(page_content=page_content, metadata=metadata)

    def _build_metadata(
        self,
        record: dict[str, Any],
        curated: dict[str, Any],
    ) -> dict[str, Any]:
        """Assemble document metadata from a loader's curated keys.

        Curated entries always win. Expansion only fills what the loader did
        not set, so a loader that deliberately formats a field keeps its
        version while the fields it never mentioned still arrive, both
        halves included.

        Args:
            record: Raw record dict from the ServiceNow API.
            curated: Keys the loader assembled by hand.

        Returns:
            The metadata dict for the document.
        """
        metadata: dict[str, Any] = dict(curated)

        if self._expand_references:
            expand_reference_keys(record, into=metadata)

        if self._include_raw:
            metadata["raw"] = record

        return metadata

    def _fetch_journals(self, sys_id: str) -> list[dict[str, Any]]:
        """Pull work notes and comments for a record from sys_journal_field.

        ServiceNow stores journal entries (work_notes, comments) in a
        separate table linked by element_id. This method queries that
        table for all entries belonging to the given record.

        This method is resilient: if the journal table is inaccessible
        (permissions, network error, etc.), it logs a warning and returns
        an empty list instead of raising an exception.

        Args:
            sys_id: The sys_id of the parent record.

        Returns:
            List of journal entry dicts with value, element, sys_created_on,
            and sys_created_by fields. Empty list on failure.
        """
        try:
            query = f"element_id={sys_id}^elementINwork_notes,comments"
            records = self._connection.get_records(
                table="sys_journal_field",
                query=query,
                fields=["value", "element", "sys_created_on", "sys_created_by"],
            )
            return list(records)
        except SnowConnectionError:
            logger.warning(
                "Failed to fetch journals for record %s. Continuing without journal entries.",
                sys_id,
                exc_info=True,
            )
            return []

    def _format_journals(self, journals: list[dict[str, Any]]) -> str:
        """Turn a list of journal entry dicts into a readable text block.

        Each entry gets a header line with the type (work_notes or comments),
        timestamp, and author, followed by the entry text. Entries are
        separated by blank lines for readability.

        Args:
            journals: List of journal dicts as returned by _fetch_journals().

        Returns:
            Formatted string with all journal entries, or empty string if
            the input list is empty.
        """
        if not journals:
            return ""

        parts = []
        for entry in journals:
            element = entry.get("element", "note")
            author = entry.get("sys_created_by", "unknown")
            timestamp = entry.get("sys_created_on", "")
            text = entry.get("value", "")

            header = f"[{element}] {timestamp} by {author}"
            parts.append(f"{header}\n{text}")

        return "\n\n".join(parts)
