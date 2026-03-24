"""Tests for CMDBLoader with relationship traversal.

Covers default and custom CI classes, document assembly with network and OS
info, outbound and inbound relationship fetching from cmdb_rel_ci, relationship
formatting in both document text and metadata, and the flag to skip relationship
lookups entirely.

Author: Roni Das
"""

from __future__ import annotations

import responses

from snowloader.connection import SnowConnection
from snowloader.loaders.cmdb import CMDBLoader

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"


def _make_connection() -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret")


SAMPLE_CI: dict = {
    "sys_id": "ci_001",
    "name": "EXCH-PROD-01",
    "sys_class_name": "cmdb_ci_server",
    "short_description": "Primary Exchange server for building 4",
    "operational_status": {"display_value": "Operational", "value": "1"},
    "environment": "production",
    "ip_address": "10.0.4.50",
    "fqdn": "exch-prod-01.corp.local",
    "os": "Windows Server 2022",
    "os_version": "21H2",
    "category": "Server",
    "subcategory": "Email",
    "assigned_to": {"display_value": "John Smith", "value": "user_001"},
    "support_group": {"display_value": "Server Team", "value": "group_001"},
    "sys_created_on": "2023-01-15 10:00:00",
    "sys_updated_on": "2024-06-01 08:00:00",
}


def test_cmdb_loader_default_class() -> None:
    """CMDBLoader without a ci_class argument should target the base
    cmdb_ci table."""
    loader = CMDBLoader(connection=_make_connection())
    assert loader.table == "cmdb_ci"


def test_cmdb_loader_custom_class() -> None:
    """Passing ci_class should override the table to the specific
    CMDB class table."""
    loader = CMDBLoader(connection=_make_connection(), ci_class="cmdb_ci_server")
    assert loader.table == "cmdb_ci_server"


@responses.activate
def test_cmdb_to_document_basic() -> None:
    """A basic CI should produce a document with name, class, status,
    and description."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_ci",
        json={"result": [SAMPLE_CI]},
        status=200,
    )

    loader = CMDBLoader(connection=_make_connection())
    docs = loader.load()

    assert len(docs) == 1
    content = docs[0].page_content
    assert "EXCH-PROD-01" in content
    assert "Primary Exchange server" in content


@responses.activate
def test_cmdb_with_network_info() -> None:
    """CIs with IP address and FQDN should include network info in
    the document text."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_ci",
        json={"result": [SAMPLE_CI]},
        status=200,
    )

    loader = CMDBLoader(connection=_make_connection())
    docs = loader.load()
    content = docs[0].page_content

    assert "10.0.4.50" in content
    assert "exch-prod-01.corp.local" in content


@responses.activate
def test_cmdb_with_os_info() -> None:
    """CIs with OS fields should show them in the document."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_ci",
        json={"result": [SAMPLE_CI]},
        status=200,
    )

    loader = CMDBLoader(connection=_make_connection())
    docs = loader.load()
    content = docs[0].page_content

    assert "Windows Server 2022" in content


@responses.activate
def test_cmdb_relationships_outbound() -> None:
    """When include_relationships is True, the loader should fetch
    outbound relationships (this CI is the parent) from cmdb_rel_ci."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_ci",
        json={"result": [SAMPLE_CI]},
        status=200,
    )
    # Outbound relationships (parent=ci_001)
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_rel_ci",
        json={
            "result": [
                {
                    "child": {"display_value": "Exchange DB", "value": "ci_002"},
                    "type": {"display_value": "Depends on::Used by", "value": "type_001"},
                },
            ]
        },
        status=200,
    )
    # Inbound relationships (child=ci_001)
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_rel_ci",
        json={"result": []},
        status=200,
    )

    loader = CMDBLoader(connection=_make_connection(), include_relationships=True)
    docs = loader.load()
    content = docs[0].page_content

    assert "Exchange DB" in content


@responses.activate
def test_cmdb_relationships_inbound() -> None:
    """Inbound relationships (this CI is the child) should also be
    included when fetching relationships."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_ci",
        json={"result": [SAMPLE_CI]},
        status=200,
    )
    # Outbound: none
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_rel_ci",
        json={"result": []},
        status=200,
    )
    # Inbound relationships (child=ci_001)
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_rel_ci",
        json={
            "result": [
                {
                    "parent": {"display_value": "Email Service", "value": "ci_003"},
                    "type": {"display_value": "Depends on::Used by", "value": "type_001"},
                },
            ]
        },
        status=200,
    )

    loader = CMDBLoader(connection=_make_connection(), include_relationships=True)
    docs = loader.load()
    content = docs[0].page_content

    assert "Email Service" in content


@responses.activate
def test_cmdb_relationships_in_text() -> None:
    """Relationship direction should be indicated with arrows in the
    document text."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_ci",
        json={"result": [SAMPLE_CI]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_rel_ci",
        json={
            "result": [
                {
                    "child": {"display_value": "Exchange DB", "value": "ci_002"},
                    "type": {"display_value": "Depends on::Used by", "value": "type_001"},
                },
            ]
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_rel_ci",
        json={
            "result": [
                {
                    "parent": {"display_value": "Email Service", "value": "ci_003"},
                    "type": {"display_value": "Contains::Contained by", "value": "type_002"},
                },
            ]
        },
        status=200,
    )

    loader = CMDBLoader(connection=_make_connection(), include_relationships=True)
    docs = loader.load()
    content = docs[0].page_content

    # Outbound arrow
    assert "->" in content or ">" in content
    # Inbound arrow
    assert "<-" in content or "<" in content


@responses.activate
def test_cmdb_relationships_in_metadata() -> None:
    """Relationships should also be stored in metadata as a list of dicts
    for programmatic access."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_ci",
        json={"result": [SAMPLE_CI]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_rel_ci",
        json={
            "result": [
                {
                    "child": {"display_value": "Exchange DB", "value": "ci_002"},
                    "type": {"display_value": "Depends on::Used by", "value": "type_001"},
                },
            ]
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_rel_ci",
        json={"result": []},
        status=200,
    )

    loader = CMDBLoader(connection=_make_connection(), include_relationships=True)
    docs = loader.load()
    meta = docs[0].metadata

    assert "relationships" in meta
    assert len(meta["relationships"]) == 1
    assert meta["relationships"][0]["target"] == "Exchange DB"


@responses.activate
def test_cmdb_no_relationships() -> None:
    """When include_relationships is False (default), no relationship
    queries should be made."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_ci",
        json={"result": [SAMPLE_CI]},
        status=200,
    )

    loader = CMDBLoader(connection=_make_connection())
    docs = loader.load()

    # Only one API call should have been made (the CI fetch)
    assert len(responses.calls) == 1
    assert "relationships" not in docs[0].metadata


@responses.activate
def test_cmdb_metadata_keys() -> None:
    """Metadata should carry the standard set of identifying fields."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/cmdb_ci",
        json={"result": [SAMPLE_CI]},
        status=200,
    )

    loader = CMDBLoader(connection=_make_connection())
    docs = loader.load()
    meta = docs[0].metadata

    assert meta["sys_id"] == "ci_001"
    assert meta["name"] == "EXCH-PROD-01"
    assert meta["table"] == "cmdb_ci"
    assert "source" in meta
