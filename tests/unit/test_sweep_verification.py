"""Tests for sweep completeness verification.

A sweep that silently drops rows is worse than one that fails, because the
record count still reconciles and nothing downstream can tell. ``verify=True``
turns that silent failure into a raised exception by comparing the number of
distinct sys_ids actually yielded against the count the instance reports.

Author: Roni Das
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import responses

from snowloader.connection import SnowConnection
from snowloader.exceptions import SnowConnectionError, SweepIncompleteError
from snowloader.sweep import SweepReport

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"
STATS_API = f"{BASE_URL}/api/now/stats"


def _conn(**overrides: Any) -> SnowConnection:
    kwargs: dict[str, Any] = {
        "instance_url": BASE_URL,
        "username": "admin",
        "password": "secret",
    }
    kwargs.update(overrides)
    return SnowConnection(**kwargs)


def _rows(start: int, count: int) -> list[dict[str, str]]:
    return [{"sys_id": f"{i:032x}", "number": f"INC{i:07d}"} for i in range(start, start + count)]


# ---------------------------------------------------------------------------
# SweepReport
# ---------------------------------------------------------------------------


def test_sweep_report_is_complete_when_numbers_agree() -> None:
    report = SweepReport(
        table="incident", query=None, expected=10, returned=10, distinct=10, failed_pages=0
    )
    assert report.complete is True
    assert report.missing == 0
    assert report.duplicates == 0


def test_sweep_report_counts_missing_and_duplicate_rows() -> None:
    """The failure the ordering bug produced: the count reconciles but nine
    records were replaced by nine duplicates."""
    report = SweepReport(
        table="cmdb_ci", query=None, expected=2784, returned=2784, distinct=2775, failed_pages=0
    )
    assert report.complete is False
    assert report.missing == 9
    assert report.duplicates == 9


def test_sweep_report_str_carries_every_number() -> None:
    """The report is what lands in an unattended run's log, so it has to be
    readable on its own."""
    report = SweepReport(
        table="cmdb_ci", query="active=true", expected=100, returned=98, distinct=98, failed_pages=1
    )
    text = str(report)
    assert "cmdb_ci" in text
    assert "expected=100" in text
    assert "distinct=98" in text
    assert "failed_pages=1" in text


# ---------------------------------------------------------------------------
# get_records(verify=True)
# ---------------------------------------------------------------------------


def test_verify_passes_when_sweep_is_complete() -> None:
    """A clean sweep must yield every record and raise nothing."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "6"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": _rows(0, 6)},
            status=200,
        )

        conn = _conn(page_size=10)
        try:
            records = list(conn.get_records("incident", verify=True))
        finally:
            conn.close()

    assert len(records) == 6


def test_verify_raises_when_rows_are_missing() -> None:
    """Fewer distinct sys_ids than the instance reports means data was lost."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "10"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": _rows(0, 7)},
            status=200,
        )

        conn = _conn(page_size=20)
        try:
            with pytest.raises(SweepIncompleteError) as excinfo:
                list(conn.get_records("incident", verify=True))
        finally:
            conn.close()

    report = excinfo.value.report
    assert report.expected == 10
    assert report.distinct == 7
    assert report.missing == 3


def test_verify_raises_when_duplicates_replace_missing_rows() -> None:
    """This is the exact shape of the tied-sort failure: the returned count
    matches the API count, but nine rows are duplicates of others and nine
    real records never arrived."""
    duplicated = _rows(0, 7) + _rows(0, 3)  # 10 rows, only 7 distinct

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "10"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": duplicated},
            status=200,
        )

        conn = _conn(page_size=20)
        try:
            with pytest.raises(SweepIncompleteError) as excinfo:
                list(conn.get_records("incident", verify=True))
        finally:
            conn.close()

    report = excinfo.value.report
    assert report.expected == 10
    assert report.returned == 10
    assert report.distinct == 7
    assert report.duplicates == 3
    assert report.missing == 3


def test_verify_tolerates_records_created_during_the_sweep() -> None:
    """More distinct rows than the pre-sweep count means the table grew while
    we were reading it. That is not data loss, so it must not raise."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "5"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": _rows(0, 8)},
            status=200,
        )

        conn = _conn(page_size=20)
        try:
            records = list(conn.get_records("incident", verify=True))
        finally:
            conn.close()

    assert len(records) == 8


def test_verify_is_off_by_default_and_costs_no_stats_call() -> None:
    """Verification adds a count request, so it must stay opt-in."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": _rows(0, 3)},
            status=200,
        )

        conn = _conn(page_size=20)
        try:
            list(conn.get_records("incident"))
        finally:
            conn.close()

        assert not any("/api/now/stats/" in c.request.url for c in rsps.calls)


def test_verify_rejects_a_field_list_without_sys_id() -> None:
    """Verification is built on distinct sys_ids. If the caller has projected
    that column away we cannot verify anything, so say so instead of
    pretending the sweep was checked."""
    conn = _conn()
    try:
        with pytest.raises(SnowConnectionError) as excinfo:
            list(conn.get_records("incident", fields=["number", "state"], verify=True))
    finally:
        conn.close()

    assert "sys_id" in str(excinfo.value)


def test_verify_accepts_a_field_list_containing_sys_id() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "3"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": _rows(0, 3)},
            status=200,
        )

        conn = _conn(page_size=20)
        try:
            records = list(conn.get_records("incident", fields=["sys_id", "number"], verify=True))
        finally:
            conn.close()

    assert len(records) == 3


def test_verify_reads_sys_id_from_display_value_all_shape() -> None:
    """With sysparm_display_value=all every field arrives as a dict. The
    verifier must read the value half, not stringify the dict."""
    rows = [{"sys_id": {"display_value": f"{i:032x}", "value": f"{i:032x}"}} for i in range(4)]

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "4"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": rows},
            status=200,
        )

        conn = _conn(page_size=20, display_value="all")
        try:
            records = list(conn.get_records("incident", verify=True))
        finally:
            conn.close()

    assert len(records) == 4


# ---------------------------------------------------------------------------
# concurrent_get_records(verify=True)
# ---------------------------------------------------------------------------


def test_concurrent_verify_raises_when_rows_are_missing() -> None:
    """The threaded paginator reuses the count it already fetched for page
    planning, so verification there costs nothing extra."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "20"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": _rows(0, 5)},
            status=200,
        )

        conn = _conn(page_size=10)
        try:
            with pytest.raises(SweepIncompleteError) as excinfo:
                list(conn.concurrent_get_records("incident", verify=True, max_workers=2))
        finally:
            conn.close()

    # Two pages, both returning the same five rows: 10 returned, 5 distinct.
    report = excinfo.value.report
    assert report.expected == 20
    assert report.distinct == 5


def test_concurrent_verify_does_not_issue_a_second_count_call() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "4"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": _rows(0, 4)},
            status=200,
        )

        conn = _conn(page_size=10)
        try:
            list(conn.concurrent_get_records("incident", verify=True, max_workers=2))
        finally:
            conn.close()

        stats_calls = [c for c in rsps.calls if "/api/now/stats/" in c.request.url]
        assert len(stats_calls) == 1


# ---------------------------------------------------------------------------
# Partial failure policy
# ---------------------------------------------------------------------------


def test_concurrent_on_error_raise_is_the_default() -> None:
    """An unrecoverable page must abort the sweep unless told otherwise."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "20"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"error": {"message": "boom"}},
            status=403,
        )

        conn = _conn(page_size=10, max_retries=0)
        try:
            with pytest.raises(SnowConnectionError):
                list(conn.concurrent_get_records("incident", max_workers=2))
        finally:
            conn.close()


def test_concurrent_on_error_skip_continues_past_a_dead_page() -> None:
    """An unattended run usually wants the other 99 percent of the table plus
    a loud record of what it lost, rather than nothing at all."""
    calls: dict[str, int] = {"n": 0}

    def flaky(request: Any) -> tuple[int, dict[str, str], str]:
        import json as _json

        calls["n"] += 1
        offset = int(dict(request.params).get("sysparm_offset", "0"))
        if offset == 10:
            return (403, {"Content-Type": "application/json"}, _json.dumps({"error": {}}))
        return (
            200,
            {"Content-Type": "application/json"},
            _json.dumps({"result": _rows(offset, 10)}),
        )

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "30"}}},
            status=200,
        )
        rsps.add_callback(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            callback=flaky,
            content_type="application/json",
        )

        conn = _conn(page_size=10, max_retries=0)
        try:
            records = list(conn.concurrent_get_records("incident", max_workers=3, on_error="skip"))
        finally:
            conn.close()

    # Pages at offset 0 and 20 survived; the page at offset 10 was skipped.
    assert len(records) == 20


def test_skipped_pages_are_reported_by_verification() -> None:
    """on_error='skip' and verify=True compose: the run finishes, and the
    exception at the end says exactly how much was lost."""

    def flaky(request: Any) -> tuple[int, dict[str, str], str]:
        import json as _json

        offset = int(dict(request.params).get("sysparm_offset", "0"))
        if offset == 10:
            return (403, {"Content-Type": "application/json"}, _json.dumps({"error": {}}))
        return (
            200,
            {"Content-Type": "application/json"},
            _json.dumps({"result": _rows(offset, 10)}),
        )

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "30"}}},
            status=200,
        )
        rsps.add_callback(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            callback=flaky,
            content_type="application/json",
        )

        conn = _conn(page_size=10, max_retries=0)
        try:
            with pytest.raises(SweepIncompleteError) as excinfo:
                list(
                    conn.concurrent_get_records(
                        "incident", max_workers=3, on_error="skip", verify=True
                    )
                )
        finally:
            conn.close()

    report = excinfo.value.report
    assert report.expected == 30
    assert report.distinct == 20
    assert report.missing == 10
    assert report.failed_pages == 1


def test_on_error_rejects_an_unknown_policy() -> None:
    conn = _conn()
    try:
        with pytest.raises(SnowConnectionError):
            list(conn.concurrent_get_records("incident", on_error="pretend-it-worked"))
    finally:
        conn.close()


def test_sequential_on_error_skip_continues_past_a_dead_page() -> None:
    """The sequential path needs the same policy, since it is what runs
    inside the plain loaders."""

    def flaky(request: Any) -> tuple[int, dict[str, str], str]:
        import json as _json

        offset = int(dict(request.params).get("sysparm_offset", "0"))
        if offset == 10:
            return (403, {"Content-Type": "application/json"}, _json.dumps({"error": {}}))
        if offset >= 30:
            return (200, {"Content-Type": "application/json"}, _json.dumps({"result": []}))
        return (
            200,
            {"Content-Type": "application/json"},
            _json.dumps({"result": _rows(offset, 10)}),
        )

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_callback(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            callback=flaky,
            content_type="application/json",
        )

        conn = _conn(page_size=10, max_retries=0)
        try:
            records = list(conn.get_records("incident", on_error="skip"))
        finally:
            conn.close()

    assert len(records) == 20


# ---------------------------------------------------------------------------
# SweepIncompleteError is catchable as a connection error
# ---------------------------------------------------------------------------


def test_sweep_incomplete_error_subclasses_snow_connection_error() -> None:
    """Existing code catches SnowConnectionError around loads. The new
    exception must not slip past those handlers."""
    assert issubclass(SweepIncompleteError, SnowConnectionError)


def test_sequential_skip_gives_up_after_a_run_of_failures() -> None:
    """on_error='skip' means tolerate gaps, not loop forever. The sequential
    paginator stops when a page comes back short, so a table where every page
    fails has nothing to tell it the end was reached."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"error": {"message": "no"}},
            status=403,
        )

        conn = _conn(page_size=10, max_retries=0)
        try:
            with pytest.raises(SnowConnectionError, match="consecutive"):
                list(conn.get_records("incident", on_error="skip"))
        finally:
            conn.close()


def test_a_single_dead_page_does_not_trip_the_give_up_limit() -> None:
    """One bad page mid-sweep is exactly the case skip exists for."""

    def flaky(request: Any) -> tuple[int, dict[str, str], str]:
        import json as _json

        offset = int(dict(request.params).get("sysparm_offset", "0"))
        if offset == 10:
            return (403, {"Content-Type": "application/json"}, _json.dumps({"error": {}}))
        if offset >= 30:
            return (200, {"Content-Type": "application/json"}, _json.dumps({"result": []}))
        return (
            200,
            {"Content-Type": "application/json"},
            _json.dumps({"result": _rows(offset, 10)}),
        )

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_callback(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            callback=flaky,
            content_type="application/json",
        )

        conn = _conn(page_size=10, max_retries=0)
        try:
            records = list(conn.get_records("incident", on_error="skip"))
        finally:
            conn.close()

    assert len(records) == 20


def test_verification_only_runs_when_the_sweep_is_fully_consumed() -> None:
    """These are generators and the check happens after the last record. A
    caller that abandons the generator never reaches it, which is correct
    (half a sweep cannot be complete) but worth pinning so nobody assumes
    verify=True protects a partial read."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "50"}}},
            status=200,
        )
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$"),
            json={"result": _rows(0, 3)},
            status=200,
        )

        conn = _conn(page_size=20)
        try:
            stream = conn.get_records("incident", verify=True)
            first = next(stream)
            stream.close()
        finally:
            conn.close()

    assert first["sys_id"] == f"{0:032x}"
