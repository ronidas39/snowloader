"""Attachment loader for the ServiceNow ``sys_attachment`` table.

Fetches attachment metadata and (optionally) downloads the binary content
of each file. Attachments live in their own table separate from the parent
records they belong to; each row has a ``table_name`` + ``table_sys_id``
pair pointing back at the parent (e.g. an incident or KB article) plus
``file_name``, ``content_type``, ``size_bytes``, and so on.

Two access modes are supported:

    1. **Metadata only** (default): yields :class:`SnowDocument` objects whose
       ``page_content`` is a short textual summary and whose ``metadata`` carries
       all the file attributes including a ``download_url``. No binary fetches
       happen unless the user calls :meth:`AttachmentLoader.download`.

    2. **Eager download**: pass ``download=True`` and the loader will fetch
       each file's bytes during iteration. The bytes are stored in the document
       ``metadata`` under the key ``content_bytes``. This can be slow and
       memory-heavy on large attachments; prefer the metadata-only mode plus
       :meth:`download_to` for selective downloads.

Author: Roni Das
"""

from __future__ import annotations

import logging
from collections.abc import Generator, Iterable
from pathlib import Path
from typing import Any

from snowloader.connection import SnowConnection, SnowConnectionError
from snowloader.loaders._field_utils import display_value as _display_value
from snowloader.loaders._field_utils import raw_value as _raw_value
from snowloader.models import BaseSnowLoader, SnowDocument

logger = logging.getLogger(__name__)


class AttachmentLoader(BaseSnowLoader):
    """Loads attachment metadata (and optionally content) from ServiceNow.

    By default this is a metadata-only loader: each ``SnowDocument`` describes
    one attachment without fetching its binary content. Pass ``download=True``
    to eagerly fetch every file. For selective downloads, leave ``download``
    off and call :meth:`download` or :meth:`download_to` for the attachments
    you actually need.

    Args:
        connection: An initialized SnowConnection.
        query: Optional encoded query (e.g. ``"table_name=kb_knowledge"`` to
            limit to KB attachments).
        fields: Optional field list override.
        download: If True, fetch each attachment's bytes during iteration and
            store them under ``metadata["content_bytes"]``. Defaults to False.
        max_size_bytes: When set, attachments larger than this are skipped from
            downloads (metadata still flows through). Useful to avoid pulling
            multi-GB files into memory.

    Example:
        conn = SnowConnection(...)
        loader = AttachmentLoader(conn, query="table_name=kb_knowledge")
        for doc in loader.lazy_load():
            print(doc.metadata["file_name"], doc.metadata["size_bytes"])

        # Selectively download a single attachment by sys_id
        first = next(iter(loader.lazy_load()))
        loader.download_to(first.metadata["sys_id"], Path("./out") / first.metadata["file_name"])
    """

    table = "sys_attachment"
    content_fields = ["file_name"]

    def __init__(
        self,
        connection: SnowConnection,
        query: str | None = None,
        fields: list[str] | None = None,
        download: bool = False,
        max_size_bytes: int | None = None,
    ) -> None:
        super().__init__(connection=connection, query=query, fields=fields)
        self._download = download
        self._max_size_bytes = max_size_bytes

    def _record_to_document(self, record: dict[str, Any]) -> SnowDocument:
        """Build a SnowDocument describing one attachment.

        ``page_content`` is a short, human-readable summary line useful for
        embedding or text search. The full file metadata lives in ``metadata``
        with a ``download_url`` pointing at the binary endpoint.

        Args:
            record: Raw ``sys_attachment`` record dict from the API.

        Returns:
            SnowDocument summarizing the attachment.
        """
        sys_id = _raw_value(record.get("sys_id"))
        file_name = _display_value(record.get("file_name"))
        content_type = _display_value(record.get("content_type"))
        table_name = _display_value(record.get("table_name"))
        table_sys_id = _raw_value(record.get("table_sys_id"))
        size_bytes_raw = _display_value(record.get("size_bytes"))
        try:
            size_bytes: int | None = int(size_bytes_raw) if size_bytes_raw else None
        except (TypeError, ValueError):
            size_bytes = None

        download_url = (
            f"{self._connection.instance_url}/api/now/attachment/{sys_id}/file" if sys_id else ""
        )

        page_content = (
            f"Attachment: {file_name}\n"
            f"Content-Type: {content_type}\n"
            f"Size: {size_bytes if size_bytes is not None else 'unknown'} bytes\n"
            f"Parent: {table_name}/{table_sys_id}"
        )

        metadata: dict[str, Any] = {
            "sys_id": sys_id,
            "file_name": file_name,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "table_name": table_name,
            "table_sys_id": table_sys_id,
            "table": self.table,
            "source": f"servicenow://sys_attachment/{sys_id}",
            "download_url": download_url,
            "sys_created_on": _display_value(record.get("sys_created_on")),
            "sys_updated_on": _display_value(record.get("sys_updated_on")),
        }

        if self._download and sys_id:
            too_large = (
                self._max_size_bytes is not None
                and size_bytes is not None
                and size_bytes > self._max_size_bytes
            )
            if too_large:
                logger.info(
                    "Skipping download of %s (%d bytes > max_size_bytes=%d)",
                    file_name,
                    size_bytes,
                    self._max_size_bytes,
                )
            else:
                try:
                    metadata["content_bytes"] = self.download(sys_id)
                except SnowConnectionError as exc:
                    logger.warning(
                        "Failed to download attachment %s (%s): %s",
                        sys_id,
                        file_name,
                        exc,
                    )

        return SnowDocument(page_content=page_content, metadata=metadata)

    def download(self, sys_id: str) -> bytes:
        """Fetch the binary content of a single attachment.

        Args:
            sys_id: The ``sys_id`` of the attachment record.

        Returns:
            Raw bytes of the attachment file.

        Raises:
            SnowConnectionError: On any non-2xx response.
        """
        if not sys_id or not sys_id.strip():
            raise SnowConnectionError("sys_id must not be empty for attachment download.")

        return self._connection.get_attachment(sys_id)

    def download_to(self, sys_id: str, dest: Path | str) -> Path:
        """Download an attachment and write it to disk.

        Args:
            sys_id: The ``sys_id`` of the attachment record.
            dest: Destination path. Parent directory is created if missing.

        Returns:
            The :class:`Path` that was written.
        """
        path = Path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.download(sys_id)
        path.write_bytes(data)
        return path

    def iter_files(self) -> Generator[tuple[dict[str, Any], bytes], None, None]:
        """Yield ``(metadata, bytes)`` pairs for every matching attachment.

        Convenience wrapper for users who want both pieces in one pass without
        the SnowDocument layer. Honors ``max_size_bytes`` from the constructor.
        """
        for doc in self.lazy_load():
            sys_id = doc.metadata.get("sys_id")
            if not sys_id:
                continue
            size_bytes = doc.metadata.get("size_bytes")
            if (
                self._max_size_bytes is not None
                and isinstance(size_bytes, int)
                and size_bytes > self._max_size_bytes
            ):
                continue
            try:
                content = self.download(sys_id)
            except SnowConnectionError as exc:
                logger.warning("Skipping %s: %s", sys_id, exc)
                continue
            yield doc.metadata, content


def filter_by_table(records: Iterable[SnowDocument], table_name: str) -> Iterable[SnowDocument]:
    """Filter attachment documents by parent table name.

    A small convenience for users who load all attachments and want to slice
    them by parent table without hitting the API again.
    """
    for rec in records:
        if rec.metadata.get("table_name") == table_name:
            yield rec
