"""Finding out what was deleted.

A delta sync built on ``sys_updated_on`` can never report a deletion, because
a deleted row has no timestamp left to compare. Anyone using ``load_since`` to
keep a copy in step therefore accumulates records that no longer exist, and
nothing tells them.

ServiceNow records deletions in ``sys_audit_delete``, one row per deleted
record carrying the table it came from and its ``documentkey``, which is the
``sys_id``. Two things about that table decide whether a sync built on it is
correct.

**Deletions are recorded against the real class, not the base table.** Sweeping
``cmdb_ci`` returns every subclass, but ``sys_audit_delete`` files the deletion
of a Linux server under ``cmdb_ci_linux_server``. Querying the base name alone
returns nothing at all: on a developer instance ``tablename=cmdb_ci`` gave 0
deletions while the class tables underneath it held 895.

**The audit is not kept forever.** A sync that runs less often than the
instance retains audit rows misses deletions permanently, so the horizon is
reported rather than assumed away.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import pytest
import responses

from snowloader import SnowConnection
from snowloader.exceptions import SnowConnectionError

BASE_URL = "https://test.service-now.com"
AUDIT_RE = re.compile(rf"^{re.escape(BASE_URL)}/api/now/table/sys_audit_delete(\?.*)?$")
DB_OBJECT_RE = re.compile(rf"^{re.escape(BASE_URL)}/api/now/table/sys_db_object(\?.*)?$")

SINCE = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _conn(**kwargs: Any) -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret", **kwargs)


def _audit(rows: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "result": [
            {
                "sys_id": f"a{i:031x}",
                "tablename": table,
                "documentkey": key,
                "sys_created_on": "2026-08-15 10:00:00",
            }
            for i, (table, key) in enumerate(rows)
        ]
    }


def _tables(rows: list[tuple[str, str, str]]) -> dict[str, Any]:
    """sys_db_object rows as (sys_id, name, super_class)."""
    return {
        "result": [{"sys_id": sid, "name": name, "super_class": sup} for sid, name, sup in rows]
    }


# ---------------------------------------------------------------------------
# The basic contract
# ---------------------------------------------------------------------------


def test_deleted_sys_ids_are_returned() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, DB_OBJECT_RE, json=_tables([("t1", "incident", "")]), status=200)
        rsps.add(responses.GET, DB_OBJECT_RE, json={"result": []}, status=200)
        rsps.add(
            responses.GET,
            AUDIT_RE,
            json=_audit([("incident", "aaa"), ("incident", "bbb")]),
            status=200,
        )
        rsps.add(responses.GET, AUDIT_RE, json={"result": []}, status=200)
        with _conn() as conn:
            got = list(conn.get_deleted_records("incident", since=SINCE))

    assert [r["sys_id"] for r in got] == ["aaa", "bbb"]
    assert all(r["table"] == "incident" for r in got)


def test_the_cutoff_reaches_the_query() -> None:
    from urllib.parse import parse_qs, urlparse

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, DB_OBJECT_RE, json=_tables([("t1", "incident", "")]), status=200)
        rsps.add(responses.GET, DB_OBJECT_RE, json={"result": []}, status=200)
        rsps.add(responses.GET, AUDIT_RE, json=_audit([("incident", "aaa")]), status=200)
        rsps.add(responses.GET, AUDIT_RE, json={"result": []}, status=200)
        with _conn() as conn:
            list(conn.get_deleted_records("incident", since=SINCE))
        q = [
            parse_qs(urlparse(c.request.url).query)["sysparm_query"][0]
            for c in rsps.calls
            if "sys_audit_delete" in c.request.url
        ][0]

    assert "sys_created_on>=2026-08-01" in q


# ---------------------------------------------------------------------------
# The subclass trap
# ---------------------------------------------------------------------------


def test_subclass_deletions_are_found() -> None:
    """The trap. cmdb_ci is a base table and deletions are filed under the
    real class, so querying the base name alone returns nothing."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            DB_OBJECT_RE,
            json=_tables(
                [
                    ("base", "cmdb_ci", ""),
                    ("lin", "cmdb_ci_linux_server", "base"),
                    ("win", "cmdb_ci_win_server", "base"),
                    ("other", "incident", ""),
                ]
            ),
            status=200,
        )
        rsps.add(responses.GET, DB_OBJECT_RE, json={"result": []}, status=200)
        rsps.add(
            responses.GET,
            AUDIT_RE,
            json=_audit([("cmdb_ci_linux_server", "lin1"), ("cmdb_ci_win_server", "win1")]),
            status=200,
        )
        rsps.add(responses.GET, AUDIT_RE, json={"result": []}, status=200)
        with _conn() as conn:
            got = list(conn.get_deleted_records("cmdb_ci", since=SINCE))

    assert {r["sys_id"] for r in got} == {"lin1", "win1"}


def test_a_table_that_merely_shares_a_prefix_is_not_a_subclass() -> None:
    """incident_task is its own table, not a subclass of incident. Matching on
    the name prefix would count its deletions as incident deletions."""
    from urllib.parse import parse_qs, urlparse

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            DB_OBJECT_RE,
            json=_tables([("i", "incident", ""), ("it", "incident_task", "")]),
            status=200,
        )
        rsps.add(responses.GET, DB_OBJECT_RE, json={"result": []}, status=200)
        rsps.add(responses.GET, AUDIT_RE, json={"result": []}, status=200)
        with _conn() as conn:
            list(conn.get_deleted_records("incident", since=SINCE))
        q = [
            parse_qs(urlparse(c.request.url).query)["sysparm_query"][0]
            for c in rsps.calls
            if "sys_audit_delete" in c.request.url
        ][0]

    assert "incident_task" not in q


def test_subclass_expansion_can_be_turned_off() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, AUDIT_RE, json=_audit([("incident", "aaa")]), status=200)
        rsps.add(responses.GET, AUDIT_RE, json={"result": []}, status=200)
        with _conn() as conn:
            got = list(conn.get_deleted_records("incident", since=SINCE, include_subclasses=False))
        assert not [c for c in rsps.calls if "sys_db_object" in c.request.url]

    assert [r["sys_id"] for r in got] == ["aaa"]


# ---------------------------------------------------------------------------
# The retention horizon
# ---------------------------------------------------------------------------


def test_the_audit_horizon_is_reported() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            AUDIT_RE,
            json={"result": [{"sys_created_on": "2026-06-12 13:58:13"}]},
            status=200,
        )
        with _conn() as conn:
            horizon = conn.get_deletion_horizon()

    assert horizon is not None
    assert horizon.year == 2026 and horizon.month == 6 and horizon.day == 12


def test_asking_for_deletions_older_than_the_horizon_is_refused() -> None:
    """Returning an empty list would look like nothing was deleted, when the
    truth is that the instance no longer knows."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, DB_OBJECT_RE, json=_tables([("t1", "incident", "")]), status=200)
        rsps.add(responses.GET, DB_OBJECT_RE, json={"result": []}, status=200)
        rsps.add(
            responses.GET,
            AUDIT_RE,
            json={"result": [{"sys_created_on": "2026-08-20 00:00:00"}]},
            status=200,
        )
        with _conn() as conn, pytest.raises(SnowConnectionError, match="horizon"):
            list(conn.get_deleted_records("incident", since=SINCE, check_horizon=True))


def test_an_empty_audit_table_yields_no_horizon() -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, AUDIT_RE, json={"result": []}, status=200)
        with _conn() as conn:
            assert conn.get_deletion_horizon() is None


# ---------------------------------------------------------------------------
# Query size
# ---------------------------------------------------------------------------


def test_a_table_with_many_subclasses_does_not_blow_the_uri_limit() -> None:
    """Found live, not in review. cmdb_ci resolves to 711 tables on a stock
    instance and one OR clause per table returned 414 Request-URI Too Large."""
    from urllib.parse import parse_qs, urlparse

    many = [("base", "cmdb_ci", "")] + [
        (f"c{i}", f"cmdb_ci_class_number_{i:04d}", "base") for i in range(700)
    ]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, DB_OBJECT_RE, json=_tables(many), status=200)
        rsps.add(responses.GET, DB_OBJECT_RE, json={"result": []}, status=200)
        rsps.add(responses.GET, AUDIT_RE, json={"result": []}, status=200)
        with _conn() as conn:
            list(conn.get_deleted_records("cmdb_ci", since=SINCE))
        queries = [
            parse_qs(urlparse(c.request.url).query).get("sysparm_query", [""])[0]
            for c in rsps.calls
            if "sys_audit_delete" in c.request.url
        ]

    assert queries, "no audit query was issued"
    longest = max(len(q) for q in queries)
    assert longest < 6000, f"a query reached {longest} characters"
    assert len(queries) > 1, "701 tables should have been split across batches"


def test_every_subclass_is_covered_across_the_batches() -> None:
    """Splitting must not drop a table on a boundary."""
    from urllib.parse import parse_qs, urlparse

    many = [("base", "cmdb_ci", "")] + [
        (f"c{i}", f"cmdb_ci_class_number_{i:04d}", "base") for i in range(700)
    ]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, DB_OBJECT_RE, json=_tables(many), status=200)
        rsps.add(responses.GET, DB_OBJECT_RE, json={"result": []}, status=200)
        rsps.add(responses.GET, AUDIT_RE, json={"result": []}, status=200)
        # Derived from the fixture rather than by calling the resolver, which
        # would consume the registry the call under test still needs.
        expected = {name for _, name, _ in many}
        with _conn() as conn:
            list(conn.get_deleted_records("cmdb_ci", since=SINCE))
        seen: set[str] = set()
        for c in rsps.calls:
            if "sys_audit_delete" not in c.request.url:
                continue
            q = parse_qs(urlparse(c.request.url).query).get("sysparm_query", [""])[0]
            for part in q.split("^"):
                if part.startswith("tablenameIN"):
                    seen.update(part[len("tablenameIN") :].split(","))

    assert expected <= seen, f"{len(expected - seen)} tables never queried"
