"""Resume support for extractions that are too long to repeat.

A sweep of half a million records takes long enough that something will
eventually interrupt one: a dropped connection, a restarted container, a
laptop lid. Starting again from zero wastes the part that already worked.

A checkpoint writes down where a run had reached, so running the same call
again continues from there.

The danger a checkpoint brings with it is subtler than the problem it solves.
A state file is just a file, and nothing about it says which extraction it
belongs to. Read one back against a different table, a different filter or a
different page size and the result is a corpus that is partly one thing and
partly another, with nothing to show for it. Every checkpoint here therefore
carries a fingerprint of the run that wrote it, and refuses to be read by a
run that does not match.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from snowloader.exceptions import SnowConnectionError

logger = logging.getLogger(__name__)


@runtime_checkable
class Checkpoint(Protocol):
    """Somewhere a run can write down how far it got.

    Implement this to keep progress somewhere other than a local file, for
    instance a database row or an object store, when several machines need to
    see the same run.
    """

    def load(self, fingerprint: str) -> dict[str, Any] | None:
        """Return the saved state for this run, or None if there is none.

        Args:
            fingerprint: Identifies the extraction being resumed.

        Returns:
            The state previously saved, or None to start from the beginning.

        Raises:
            SnowConnectionError: If state exists but belongs to a different
                extraction.
        """
        ...

    def save(self, fingerprint: str, state: dict[str, Any]) -> None:
        """Record how far the run has got.

        Args:
            fingerprint: Identifies the extraction being saved.
            state: Position to write down.
        """
        ...

    def clear(self) -> None:
        """Discard the saved state, once the run has finished."""
        ...


def fingerprint(
    table: str,
    query: str | None,
    page_size: int,
    mode: str,
    fields: list[str] | None = None,
) -> str:
    """Identify one extraction, so its state cannot be applied to another.

    Args:
        table: ServiceNow table name.
        query: The full encoded query, ordering included.
        page_size: Records per request. A different page size means different
            page boundaries, so recorded offsets no longer mean the same thing.
        mode: ``"keyset"`` or ``"offset"``.
        fields: Requested field list, or None for all.

    Returns:
        A short stable digest of those inputs.
    """
    material = json.dumps(
        {
            "table": table,
            "query": query or "",
            "page_size": page_size,
            "mode": mode,
            "fields": sorted(fields) if fields else None,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


class FileCheckpoint:
    """Keeps a run's position in a JSON file beside the output.

    Writes are atomic: the state goes to a temporary file which is then moved
    into place, so a process killed mid-write leaves either the previous state
    or the new one, never half of either.

    Args:
        path: Where to keep the state.

    Example:
        >>> from snowloader import FileCheckpoint, SnowConnection
        >>> checkpoint = FileCheckpoint("cmdb_sweep.json")
        >>> for record in conn.get_records(
        ...     "cmdb_ci", keyset=True, checkpoint=checkpoint
        ... ):
        ...     handle.write(json.dumps(record) + "\\n")
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    # The fingerprint helper is exposed on the instance too, so a caller
    # writing state by hand does not have to import the module function.
    fingerprint = staticmethod(fingerprint)

    def load(self, fingerprint: str) -> dict[str, Any] | None:
        """Read the saved position, refusing state from a different run.

        A file that cannot be parsed is treated as absent rather than fatal:
        a run killed part way through a write should not stop the next one.

        Args:
            fingerprint: Identifies the extraction being resumed.

        Returns:
            The saved state, or None.

        Raises:
            SnowConnectionError: If the file holds state for a different
                extraction.
        """
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text())
        except (ValueError, OSError) as exc:
            logger.warning(
                "Checkpoint at %s could not be read (%s). Starting from the beginning.",
                self.path,
                exc,
            )
            return None

        if not isinstance(payload, dict) or "fingerprint" not in payload:
            logger.warning(
                "Checkpoint at %s is not in the expected shape. Starting from the beginning.",
                self.path,
            )
            return None

        if payload["fingerprint"] != fingerprint:
            raise SnowConnectionError(
                f"The checkpoint at {self.path} belongs to a different extraction.",
                detail=(
                    "Table, query, field list or page size has changed since it "
                    "was written. Resuming would mix two different result sets "
                    "into one output. Delete the file to start again, or point "
                    "this run at its own checkpoint."
                ),
            )

        state = payload.get("state")
        return state if isinstance(state, dict) else None

    def save(self, fingerprint: str, state: dict[str, Any]) -> None:
        """Write the position atomically.

        Args:
            fingerprint: Identifies the extraction being saved.
            state: Position to write down.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"fingerprint": fingerprint, "state": state}))
        os.replace(tmp, self.path)

    def clear(self) -> None:
        """Remove the file, so a finished run leaves nothing behind."""
        self.path.unlink(missing_ok=True)
