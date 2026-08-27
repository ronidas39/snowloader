"""Exception types raised by snowloader.

These live in their own module so that both the sync and the async connection
can import them without either one importing the other. Everything here is
re-exported from :mod:`snowloader.connection` as well, so existing imports
keep working.

Author: Roni Das
Created: 2026-08-27
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from snowloader.sweep import SweepReport


class SnowConnectionError(Exception):
    """Raised when something goes wrong talking to the ServiceNow API.

    Attributes:
        status_code: HTTP status code if the error came from an API response.
            None for network-level failures (timeout, DNS, connection refused).
        detail: Human-readable error detail extracted from the response body
            or the underlying exception message.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class SweepIncompleteError(SnowConnectionError):
    """Raised when a verified sweep did not return every record.

    A sweep can come up short in two ways, and both are silent without this
    check. Rows can go missing, and rows can be returned twice in place of
    rows that went missing, which leaves the total count reconciling
    perfectly while the data is wrong.

    Subclasses :class:`SnowConnectionError` so callers that already wrap a
    load in ``except SnowConnectionError`` keep catching it.

    Attributes:
        report: The :class:`~snowloader.sweep.SweepReport` with every count
            that went into the decision.
    """

    def __init__(self, report: SweepReport) -> None:
        super().__init__(
            f"Sweep of '{report.table}' did not return every record: {report}",
            detail=str(report),
        )
        self.report = report
