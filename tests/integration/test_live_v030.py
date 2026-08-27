"""Live integration tests for the 0.3.0 guarantees.

Everything here talks to a real instance. The point is that the promises this
release makes are about a remote system's behaviour, and a mock cannot check
any of them: whether ServiceNow honours a two column sort, whether a sweep
under the old order really did lose rows, whether reference fields come back
with both halves populated.

Requires environment variables:
    SNOW_INSTANCE  - e.g. https://dev123456.service-now.com
    SNOW_USER      - e.g. admin
    SNOW_PASS      - the account password

Run with:
    pytest tests/integration/test_live_v030.py -x --tb=short -v

Author: Roni Das
Created: 2026-08-27
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

from snowloader import (
    IncidentLoader,
    RelationshipLoader,
    SnowConnection,
    SweepIncompleteError,
    TableLoader,
)

INSTANCE = os.environ.get("SNOW_INSTANCE", "")
USER = os.environ.get("SNOW_USER", "")
PASS = os.environ.get("SNOW_PASS", "")

pytestmark = pytest.mark.skipif(
    not all([INSTANCE, USER, PASS]),
    reason="SNOW_INSTANCE, SNOW_USER, SNOW_PASS env vars required",
)

# cmdb_ci is the table the loss reproduces on: thousands of rows spread over
# a few hundred distinct sys_created_on values, so page boundaries land
# inside tied groups constantly.
TIED_TABLE = "cmdb_ci"


@pytest.fixture(scope="module")
def conn() -> Iterator[SnowConnection]:
    connection = SnowConnection(
        instance_url=INSTANCE,
        username=USER,
        password=PASS,
        page_size=100,
    )
    yield connection
    connection.close()


def _ids(records: list[dict[str, Any]]) -> list[str]:
    out = []
    for record in records:
        value = record.get("sys_id")
        out.append(value["value"] if isinstance(value, dict) else str(value))
    return out


# ===================================================================
# 1. The ordering fix
# ===================================================================


def test_the_table_under_test_actually_has_timestamp_ties(conn: SnowConnection) -> None:
    """If this table had a unique sys_created_on the rest of these tests
    would pass for the wrong reason."""
    rows = list(conn.get_records(TIED_TABLE, fields=["sys_id", "sys_created_on"]))
    stamps = {str(row.get("sys_created_on")) for row in rows}
    assert len(rows) > len(stamps), (
        f"{TIED_TABLE} has {len(rows)} rows across {len(stamps)} distinct timestamps; "
        "no ties means this instance cannot exercise the ordering fix"
    )


def test_default_order_sweeps_the_tied_table_without_losing_rows(conn: SnowConnection) -> None:
    """The headline fix. Under the pre-0.3.0 order this table came back with
    the right total and the wrong contents."""
    expected = conn.get_count(TIED_TABLE)
    ids = _ids(list(conn.get_records(TIED_TABLE, fields=["sys_id"])))

    assert len(ids) == expected
    assert len(set(ids)) == expected


def test_threaded_path_sweeps_the_tied_table_without_losing_rows(conn: SnowConnection) -> None:
    expected = conn.get_count(TIED_TABLE)
    ids = _ids(list(conn.concurrent_get_records(TIED_TABLE, fields=["sys_id"], max_workers=16)))

    assert len(ids) == expected
    assert len(set(ids)) == expected


def test_the_order_chain_is_a_real_two_column_sort(conn: SnowConnection) -> None:
    """ServiceNow could have ignored the second ORDERBY. It does not: inside
    every group of rows sharing a timestamp, sys_id ascends."""
    rows = list(conn.get_records(TIED_TABLE, fields=["sys_id", "sys_created_on"]))

    ties = 0
    for previous, current in zip(rows, rows[1:], strict=False):
        assert current["sys_created_on"] >= previous["sys_created_on"]
        if current["sys_created_on"] == previous["sys_created_on"]:
            ties += 1
            assert current["sys_id"] > previous["sys_id"]

    assert ties > 0, "no tied pairs, so the secondary sort was never exercised"


def test_ordering_off_is_still_available_for_callers_who_want_it(
    conn: SnowConnection,
) -> None:
    """order_by=None is an escape hatch, not a trap: it works, it just gives
    up the guarantee."""
    unordered = SnowConnection(
        instance_url=INSTANCE,
        username=USER,
        password=PASS,
        page_size=100,
        order_by=None,
    )
    try:
        page = list(unordered.get_records("incident", fields=["sys_id"]))
    finally:
        unordered.close()

    assert page


# ===================================================================
# 2. Sweep verification
# ===================================================================


def test_verify_passes_on_a_real_sweep(conn: SnowConnection) -> None:
    """The check that finds nothing, which is the point of it."""
    expected = conn.get_count(TIED_TABLE)
    records = list(conn.get_records(TIED_TABLE, fields=["sys_id"], verify=True))

    assert len(records) == expected


def test_verify_passes_on_the_threaded_path(conn: SnowConnection) -> None:
    records = list(
        conn.concurrent_get_records(
            TIED_TABLE,
            fields=["sys_id"],
            max_workers=16,
            verify=True,
        )
    )

    assert len(records) == conn.get_count(TIED_TABLE)


def test_verify_catches_a_sweep_that_really_did_lose_rows(conn: SnowConnection) -> None:
    """Reproduce the pre-0.3.0 behaviour exactly and confirm verification
    refuses it.

    Ordering is turned off on the connection and the old clause is passed in
    the query instead, because ``order_by`` will not build a chain without a
    unique tiebreak, which is the whole point of it. This is the test that
    proves the check is worth having. If the instance ever stops losing rows
    under the old order it will fail, and that is the correct outcome: the
    check would then have nothing to catch here.
    """
    lossy = SnowConnection(
        instance_url=INSTANCE,
        username=USER,
        password=PASS,
        page_size=100,
        order_by=None,
    )
    try:
        with pytest.raises(SweepIncompleteError) as excinfo:
            list(
                lossy.get_records(
                    TIED_TABLE,
                    query="ORDERBYsys_created_on",
                    fields=["sys_id"],
                    verify=True,
                )
            )
    finally:
        lossy.close()

    report = excinfo.value.report
    assert report.missing > 0
    assert report.duplicates > 0
    # The failure mode worth naming: the returned count still reconciles.
    assert report.returned == report.expected


def test_verify_refuses_a_projection_without_sys_id(conn: SnowConnection) -> None:
    with pytest.raises(Exception, match="sys_id"):
        list(conn.get_records("incident", fields=["number"], verify=True))


# ===================================================================
# 3. Reference fields on real records
# ===================================================================


@pytest.mark.parametrize("display_value", ["true", "all"])
def test_incident_metadata_carries_both_halves(display_value: str) -> None:
    """The gaps report measured 15 metadata keys, no sys_id companions at
    all, and a stringified dict where the primary key should be."""
    connection = SnowConnection(
        instance_url=INSTANCE,
        username=USER,
        password=PASS,
        page_size=100,
        display_value=display_value,
    )
    try:
        docs = IncidentLoader(connection).load()
    finally:
        connection.close()

    assert docs, "no incidents on this instance to check"
    metadata = docs[0].metadata

    assert isinstance(metadata["sys_id"], str)
    assert len(metadata["sys_id"]) == 32
    assert "display_value" not in metadata["sys_id"]

    companions = [key for key in metadata if key.endswith("_sys_id")]
    assert companions, f"no reference companions in {sorted(metadata)}"

    for key in companions:
        assert len(metadata[key]) == 32, f"{key} is not a sys_id: {metadata[key]!r}"


def test_caller_and_opener_are_present_and_joinable() -> None:
    """Both fields were absent from incident metadata entirely."""
    connection = SnowConnection(
        instance_url=INSTANCE,
        username=USER,
        password=PASS,
        page_size=100,
        display_value="all",
    )
    try:
        docs = IncidentLoader(connection).load()
    finally:
        connection.close()

    with_caller = [doc for doc in docs if doc.metadata.get("caller_id_sys_id")]
    assert with_caller, "no incident on this instance has a caller to check"

    metadata = with_caller[0].metadata
    assert len(metadata["caller_id_sys_id"]) == 32
    assert metadata["caller_id"] != metadata["caller_id_sys_id"]


def test_a_reference_sys_id_resolves_to_a_real_record() -> None:
    """The join has to actually work, not just look like a sys_id."""
    connection = SnowConnection(
        instance_url=INSTANCE,
        username=USER,
        password=PASS,
        page_size=100,
        display_value="all",
    )
    try:
        docs = IncidentLoader(connection).load()
        joinable = [doc for doc in docs if doc.metadata.get("caller_id_sys_id")]
        assert joinable, "no incident on this instance has a caller to join"

        metadata = joinable[0].metadata
        user = connection.get_record("sys_user", metadata["caller_id_sys_id"])
    finally:
        connection.close()

    assert user
    name = user.get("name")
    resolved = name["display_value"] if isinstance(name, dict) else name
    assert resolved == metadata["caller_id"]


def test_sys_class_name_gives_the_table_name_not_the_pretty_label() -> None:
    """The trap the gaps report names: reading the display half of
    sys_class_name files a MySQL instance as "MySQL Instance" rather than
    cmdb_ci_db_mysql_instance."""
    connection = SnowConnection(
        instance_url=INSTANCE,
        username=USER,
        password=PASS,
        page_size=100,
        display_value="all",
    )
    try:
        docs = TableLoader(
            connection,
            table=TIED_TABLE,
            fields=["sys_id", "name", "sys_class_name"],
        ).load()
    finally:
        connection.close()

    typed = [doc for doc in docs if doc.metadata.get("sys_class_name_value")]
    assert typed, "no CI on this instance reports a class to check"

    metadata = typed[0].metadata
    assert metadata["sys_class_name_value"].startswith("cmdb_ci")


# ===================================================================
# 4. The new loaders
# ===================================================================


def test_table_loader_reads_a_table_with_no_dedicated_loader(
    conn: SnowConnection,
) -> None:
    docs = TableLoader(conn, table="sys_user").load()

    assert docs
    assert docs[0].metadata["table"] == "sys_user"
    assert len(docs[0].metadata["sys_id"]) == 32


def test_table_loader_sweep_is_complete(conn: SnowConnection) -> None:
    docs = TableLoader(conn, table="sys_user").load(verify=True)

    assert len(docs) == conn.get_count("sys_user")


def test_relationship_loader_returns_loadable_edges(conn: SnowConnection) -> None:
    """Both endpoints and the type come back as identifiers, so the edges go
    straight into a graph with no resolution step."""
    docs = RelationshipLoader(conn).load()

    assert docs, "no CI relationships on this instance"
    for doc in docs[:25]:
        assert len(doc.metadata["parent_sys_id"]) == 32
        assert len(doc.metadata["child_sys_id"]) == 32
        assert doc.metadata["type"]


def test_relationship_edges_point_at_configuration_items_that_exist(
    conn: SnowConnection,
) -> None:
    """A dangling edge would mean the sys_ids are not what they claim."""
    edges = RelationshipLoader(conn).load()[:5]
    assert edges

    for edge in edges:
        parent = conn.get_record(TIED_TABLE, edge.metadata["parent_sys_id"])
        assert parent


def test_relationship_sweep_beats_per_ci_traversal_on_call_count(
    conn: SnowConnection,
) -> None:
    """CMDBLoader(include_relationships=True) costs two requests per CI. One
    sweep of cmdb_rel_ci costs a page per hundred edges."""
    edges = conn.get_count("cmdb_rel_ci")
    cis = conn.get_count(TIED_TABLE)

    sweep_requests = (edges + 99) // 100
    traversal_requests = cis * 2

    assert sweep_requests < traversal_requests


# ===================================================================
# 5. Partial failure and delta sync
# ===================================================================


def test_on_error_skip_does_not_change_a_healthy_sweep(conn: SnowConnection) -> None:
    """Nothing fails on a healthy instance, so the policy must be a no-op
    rather than a behaviour change."""
    strict = list(conn.get_records("incident", fields=["sys_id"]))
    lenient = list(conn.get_records("incident", fields=["sys_id"], on_error="skip"))

    assert _ids(strict) == _ids(lenient)


def test_since_field_can_target_the_creation_column() -> None:
    """An append-only table has no useful sys_updated_on, and on some tables
    that column is not indexed."""
    from datetime import datetime, timezone

    connection = SnowConnection(
        instance_url=INSTANCE,
        username=USER,
        password=PASS,
        page_size=50,
        since_field="sys_created_on",
    )
    cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None)
    try:
        records = list(connection.get_records("incident", fields=["sys_id"], since=cutoff))
        total = connection.get_count("incident")
    finally:
        connection.close()

    assert len(records) == total
