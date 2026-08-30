"""What changed on a table between two points in time.

A sync asks three questions and ``load_since`` answers one of them. Rows whose
``sys_updated_on`` moved are a mixture of new and edited records, and a
deletion leaves no row behind to report at all, so a copy maintained that way
gains ghosts and never loses them.

:class:`ReconciliationReport` keeps the three apart. The split between added
and updated comes from comparing ``sys_created_on`` against the same cutoff,
which costs one more field on a sweep already being made. Deletions come from
``sys_audit_delete``, which has a retention horizon worth knowing about; see
:meth:`snowloader.SnowConnection.get_deletion_horizon`.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

__all__ = ["ReconciliationReport"]


@dataclass
class ReconciliationReport:
    """Everything that happened to a table since a cutoff.

    Attributes:
        table: The table reconciled.
        since: The cutoff the three lists are relative to.
        added: Records created after the cutoff, in full.
        updated: Records that existed before it and have been edited since.
        deleted: One entry per deletion, carrying ``sys_id``, ``table`` and
            ``deleted_at``. The record itself is gone, so only the identifier
            survives.
        horizon: Oldest deletion the instance still remembers, when it was
            looked up. A cutoff earlier than this means deletions are being
            missed rather than absent.
    """

    table: str
    since: datetime
    added: list[dict[str, Any]] = field(default_factory=list)
    updated: list[dict[str, Any]] = field(default_factory=list)
    deleted: list[dict[str, Any]] = field(default_factory=list)
    horizon: datetime | None = None

    @property
    def total_changes(self) -> int:
        """How many records need attention in total."""
        return len(self.added) + len(self.updated) + len(self.deleted)

    @property
    def is_complete(self) -> bool:
        """Whether deletions before the cutoff could still be seen.

        False means the audit had already been pruned past the cutoff, so the
        deleted list is a floor rather than the whole truth.
        """
        if self.horizon is None:
            return True
        cutoff = self.since if self.since.tzinfo else self.since.replace(tzinfo=self.horizon.tzinfo)
        return cutoff >= self.horizon

    def __str__(self) -> str:
        return (
            f"table={self.table} since={self.since:%Y-%m-%d %H:%M:%S} "
            f"added={len(self.added)} updated={len(self.updated)} "
            f"deleted={len(self.deleted)} complete={self.is_complete}"
        )
