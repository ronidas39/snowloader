"""Answering the only question a sync actually asks.

"What changed since I last ran" is three questions, and until now the package
answered one of them. ``load_since`` returns rows whose ``sys_updated_on`` moved,
which mixes new records in with edited ones and cannot mention deletions at all.

A caller keeping a copy in step needs the three apart:

    added    created after the cutoff
    updated  existing before the cutoff and edited since
    deleted  gone, which only sys_audit_delete knows about

The split between added and updated comes from comparing ``sys_created_on``
against the same cutoff, so it costs nothing beyond a field.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import responses

from snowloader import SnowConnection

BASE_URL = "https://test.service-now.com"
INCIDENT_RE = re.compile(rf"^{re.escape(BASE_URL)}/api/now/table/incident(\?.*)?$")
AUDIT_RE = re.compile(rf"^{re.escape(BASE_URL)}/api/now/table/sys_audit_delete(\?.*)?$")
DB_OBJECT_RE = re.compile(rf"^{re.escape(BASE_URL)}/api/now/table/sys_db_object(\?.*)?$")

SINCE = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _conn(**kwargs: Any) -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret", **kwargs)


def _row(sys_id: str, created: str, updated: str) -> dict[str, str]:
    return {"sys_id": sys_id, "sys_created_on": created, "sys_updated_on": updated}


def _wire(rsps: Any, changed: list[dict[str, str]], deleted: list[str]) -> None:
    rsps.add(
        responses.GET,
        DB_OBJECT_RE,
        json={"result": [{"sys_id": "t1", "name": "incident", "super_class": ""}]},
        status=200,
    )
    rsps.add(responses.GET, DB_OBJECT_RE, json={"result": []}, status=200)
    rsps.add(responses.GET, INCIDENT_RE, json={"result": changed}, status=200)
    rsps.add(responses.GET, INCIDENT_RE, json={"result": []}, status=200)
    # reconcile asks for the retention horizon before it asks for deletions,
    # so the first audit read is that single oldest row.
    rsps.add(
        responses.GET,
        AUDIT_RE,
        json={"result": [{"sys_created_on": "2026-06-12 13:58:13"}]},
        status=200,
    )
    rsps.add(
        responses.GET,
        AUDIT_RE,
        json={
            "result": [
                {
                    "sys_id": f"a{i}",
                    "tablename": "incident",
                    "documentkey": key,
                    "sys_created_on": "2026-08-15 10:00:00",
                }
                for i, key in enumerate(deleted)
            ]
        },
        status=200,
    )
    rsps.add(responses.GET, AUDIT_RE, json={"result": []}, status=200)


def test_added_updated_and_deleted_come_back_apart() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _wire(
            rsps,
            changed=[
                _row("new1", "2026-08-10 00:00:00", "2026-08-10 00:00:00"),
                _row("old1", "2026-01-01 00:00:00", "2026-08-12 00:00:00"),
            ],
            deleted=["gone1"],
        )
        with _conn() as conn:
            report = conn.reconcile("incident", since=SINCE)

    assert [r["sys_id"] for r in report.added] == ["new1"]
    assert [r["sys_id"] for r in report.updated] == ["old1"]
    assert [r["sys_id"] for r in report.deleted] == ["gone1"]


def test_the_report_counts_itself() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _wire(
            rsps,
            changed=[
                _row("new1", "2026-08-10 00:00:00", "2026-08-10 00:00:00"),
                _row("new2", "2026-08-11 00:00:00", "2026-08-11 00:00:00"),
                _row("old1", "2026-01-01 00:00:00", "2026-08-12 00:00:00"),
            ],
            deleted=["gone1", "gone2"],
        )
        with _conn() as conn:
            report = conn.reconcile("incident", since=SINCE)

    assert report.total_changes == 5
    assert (len(report.added), len(report.updated), len(report.deleted)) == (2, 1, 2)
    assert report.table == "incident"


def test_a_record_created_and_deleted_between_runs_is_only_deleted() -> None:
    """It never existed as far as the target is concerned, and reporting it as
    added as well would have a sync write a row then remove it."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _wire(
            rsps,
            changed=[_row("blip", "2026-08-10 00:00:00", "2026-08-10 00:00:00")],
            deleted=["blip"],
        )
        with _conn() as conn:
            report = conn.reconcile("incident", since=SINCE)

    assert [r["sys_id"] for r in report.deleted] == ["blip"]
    assert report.added == []


def test_nothing_changed_is_an_empty_report_not_an_error() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _wire(rsps, changed=[], deleted=[])
        with _conn() as conn:
            report = conn.reconcile("incident", since=SINCE)

    assert report.total_changes == 0
    assert not report.added and not report.updated and not report.deleted


def test_deletions_can_be_skipped_for_an_append_only_table() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            INCIDENT_RE,
            json={"result": [_row("new1", "2026-08-10 00:00:00", "2026-08-10 00:00:00")]},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT_RE, json={"result": []}, status=200)
        with _conn() as conn:
            report = conn.reconcile("incident", since=SINCE, include_deletes=False)
        assert not [c for c in rsps.calls if "sys_audit_delete" in c.request.url]

    assert len(report.added) == 1
    assert report.deleted == []


def test_the_report_reads_as_a_line_of_text() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _wire(
            rsps,
            changed=[_row("new1", "2026-08-10 00:00:00", "2026-08-10 00:00:00")],
            deleted=["gone1"],
        )
        with _conn() as conn:
            text = str(conn.reconcile("incident", since=SINCE))

    assert "incident" in text
    assert "added=1" in text and "deleted=1" in text
