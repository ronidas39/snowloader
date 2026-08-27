"""Sweep completeness accounting.

A paginated read can come up short without anything failing: no error status,
no exception, and a returned row count that still matches what the instance
reports. That happens when rows are duplicated in place of rows that went
missing. The tracker here counts distinct primary keys as records stream past
and compares the total against the count the instance gave before the sweep
started, which is the only way to tell the difference.

Author: Roni Das
Created: 2026-08-27
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from snowloader.exceptions import SweepIncompleteError
from snowloader.fields import raw_value

logger = logging.getLogger(__name__)


@dataclass
class SweepReport:
    """The numbers behind a completeness decision.

    Attributes:
        table: Table that was swept.
        query: Encoded query the sweep ran with, or None.
        expected: Record count the instance reported before the sweep began.
        returned: Number of records the sweep actually yielded.
        distinct: Number of distinct sys_ids among them.
        failed_pages: Pages that could not be fetched and were skipped
            because the sweep ran with ``on_error="skip"``.
    """

    table: str
    query: str | None
    expected: int
    returned: int
    distinct: int
    failed_pages: int = 0

    @property
    def missing(self) -> int:
        """Records the instance reported that never arrived.

        Zero when the sweep returned at least as many distinct records as
        were expected, which includes the case of a table that grew during
        the read.
        """
        return max(0, self.expected - self.distinct)

    @property
    def duplicates(self) -> int:
        """Records that arrived more than once."""
        return max(0, self.returned - self.distinct)

    @property
    def complete(self) -> bool:
        """Whether the sweep can be trusted to hold every record.

        A sweep is complete when nothing is missing and nothing was
        duplicated. Coming back with more distinct records than expected is
        not a failure: it means rows were inserted while the sweep ran.
        """
        return self.missing == 0 and self.duplicates == 0

    def __str__(self) -> str:
        return (
            f"table={self.table} expected={self.expected} returned={self.returned} "
            f"distinct={self.distinct} missing={self.missing} "
            f"duplicated={self.duplicates} failed_pages={self.failed_pages}"
        )


@dataclass
class SweepTracker:
    """Counts distinct primary keys while a sweep streams past.

    Holding one 32-character key per record measures at about 100 bytes
    each once Python's string and set overhead is counted, so roughly 50 MB
    on a half million row table. That is why verification is opt-in rather
    than always on. Everything else about the stream is unchanged: records are yielded as
    they arrive and nothing is buffered.

    Args:
        table: Table being swept, for the report.
        query: Encoded query, for the report.
        expected: Count the instance reported before the sweep began.
    """

    table: str
    query: str | None
    expected: int
    failed_pages: int = 0
    _returned: int = 0
    _seen: set[str] = field(default_factory=set)

    def observe(self, record: dict[str, Any]) -> None:
        """Record one row against the running totals.

        Args:
            record: A raw record dict, in any display value shape.
        """
        self._returned += 1
        self._seen.add(raw_value(record.get("sys_id")))

    def page_failed(self) -> None:
        """Note that a page was skipped after its retries were exhausted."""
        self.failed_pages += 1

    def build_report(self) -> SweepReport:
        """Assemble the report for everything observed so far."""
        return SweepReport(
            table=self.table,
            query=self.query,
            expected=self.expected,
            returned=self._returned,
            distinct=len(self._seen),
            failed_pages=self.failed_pages,
        )

    def check(self) -> SweepReport:
        """Finish the sweep and fail if it did not return everything.

        Returns:
            The report, when the sweep is complete.

        Raises:
            SweepIncompleteError: If records went missing or arrived twice.
        """
        report = self.build_report()

        if not report.complete:
            raise SweepIncompleteError(report)

        if report.distinct > report.expected:
            logger.warning(
                "Sweep of '%s' returned %d distinct records against an expected %d. "
                "Records were most likely inserted while the sweep was running.",
                report.table,
                report.distinct,
                report.expected,
            )
        else:
            logger.info("Sweep verified: %s", report)

        return report
