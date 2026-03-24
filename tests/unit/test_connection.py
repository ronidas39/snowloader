"""Tests for SnowConnection, the core ServiceNow API client.

Covers authentication modes (basic auth and OAuth), pagination behavior,
query filtering, delta sync, single record fetches, error handling,
and URL normalization. All HTTP calls are mocked using the responses library
so nothing hits a real ServiceNow instance.

Author: Roni Das
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import responses

from snowloader.connection import SnowConnection, SnowConnectionError

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"


# -- Authentication tests --


def test_basic_auth_initialization() -> None:
    """SnowConnection should store basic auth credentials when given
    a username and password, and no OAuth fields."""
    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
    )
    assert conn.instance_url == BASE_URL
    assert conn.auth_type == "basic"


def test_oauth_initialization() -> None:
    """When client_id and client_secret are provided alongside user
    credentials, SnowConnection should prefer OAuth authentication."""
    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
        client_id="my_client",
        client_secret="my_secret",
    )
    assert conn.auth_type == "oauth"


def test_missing_credentials_raises_error() -> None:
    """Constructing a SnowConnection without any credentials at all
    should raise SnowConnectionError immediately."""
    with pytest.raises(SnowConnectionError):
        SnowConnection(instance_url=BASE_URL)


# -- Record fetching tests --


@responses.activate
def test_get_records_single_page() -> None:
    """When the API returns fewer records than the page size, pagination
    should not kick in. We expect a single request and the full result set."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={
            "result": [
                {"sys_id": "aaa", "number": "INC0010001"},
                {"sys_id": "bbb", "number": "INC0010002"},
            ]
        },
        status=200,
    )

    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
    )
    records = list(conn.get_records("incident"))
    assert len(records) == 2
    assert records[0]["number"] == "INC0010001"
    assert records[1]["number"] == "INC0010002"


@responses.activate
def test_get_records_pagination() -> None:
    """When the first page returns exactly page_size records, the client
    must fetch the next page. Pagination stops when a page returns fewer
    records than page_size."""
    # First page: full batch (2 records, page_size=2)
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={
            "result": [
                {"sys_id": "aaa", "number": "INC001"},
                {"sys_id": "bbb", "number": "INC002"},
            ]
        },
        status=200,
    )
    # Second page: partial batch means we're done
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={
            "result": [
                {"sys_id": "ccc", "number": "INC003"},
            ]
        },
        status=200,
    )

    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
        page_size=2,
    )
    records = list(conn.get_records("incident"))
    assert len(records) == 3
    assert records[2]["number"] == "INC003"


@responses.activate
def test_get_records_empty_result() -> None:
    """An empty result set from the API should yield zero records
    without raising any errors."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": []},
        status=200,
    )

    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
    )
    records = list(conn.get_records("incident"))
    assert records == []


@responses.activate
def test_get_records_with_fields_filter() -> None:
    """Passing a fields list should send sysparm_fields as a
    comma-separated string in the query parameters."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": [{"sys_id": "aaa", "number": "INC001"}]},
        status=200,
    )

    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
    )
    list(conn.get_records("incident", fields=["sys_id", "number"]))

    sent_params = responses.calls[0].request.params
    assert "sysparm_fields" in sent_params
    assert "sys_id" in sent_params["sysparm_fields"]
    assert "number" in sent_params["sysparm_fields"]


@responses.activate
def test_get_records_with_query_filter() -> None:
    """A custom query string should be passed through as sysparm_query,
    with the ordering suffix appended for consistent pagination."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": []},
        status=200,
    )

    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
    )
    list(conn.get_records("incident", query="active=true^priority=1"))

    sent_params = responses.calls[0].request.params
    query = sent_params["sysparm_query"]
    assert "active=true^priority=1" in query
    assert "ORDERBYsys_created_on" in query


@responses.activate
def test_get_records_since_delta_sync() -> None:
    """When a 'since' datetime is passed, the query should include a
    sys_updated_on filter so we only pull records modified after that
    timestamp. This is the basis for incremental/delta syncing."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"result": []},
        status=200,
    )

    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
    )
    since = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    list(conn.get_records("incident", since=since))

    sent_params = responses.calls[0].request.params
    query = sent_params["sysparm_query"]
    assert "sys_updated_on>2024-06-15 12:00:00" in query


@responses.activate
def test_get_record_single_by_sys_id() -> None:
    """Fetching a single record by sys_id should hit the /table/{name}/{sys_id}
    endpoint and return a single dict, not a list."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident/abc123",
        json={"result": {"sys_id": "abc123", "number": "INC001"}},
        status=200,
    )

    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
    )
    record = conn.get_record("incident", "abc123")
    assert record["sys_id"] == "abc123"
    assert record["number"] == "INC001"


# -- Error handling tests --


@responses.activate
def test_api_error_raises_exception_401() -> None:
    """A 401 Unauthorized response should raise SnowConnectionError."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"error": {"message": "User not authenticated"}},
        status=401,
    )

    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="wrong",
    )
    with pytest.raises(SnowConnectionError):
        list(conn.get_records("incident"))


@responses.activate
def test_api_error_raises_exception_404() -> None:
    """A 404 Not Found response should raise SnowConnectionError."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/nonexistent",
        json={"error": {"message": "Table not found"}},
        status=404,
    )

    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
    )
    with pytest.raises(SnowConnectionError):
        list(conn.get_records("nonexistent"))


@responses.activate
def test_api_error_raises_exception_500() -> None:
    """A 500 Internal Server Error should raise SnowConnectionError."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/incident",
        json={"error": {"message": "Internal error"}},
        status=500,
    )

    conn = SnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
    )
    with pytest.raises(SnowConnectionError):
        list(conn.get_records("incident"))


# -- URL normalization tests --


def test_instance_url_trailing_slash_stripped() -> None:
    """A trailing slash on the instance URL should be stripped during
    initialization so we never end up with double slashes in API calls."""
    conn = SnowConnection(
        instance_url="https://test.service-now.com/",
        username="admin",
        password="secret",
    )
    assert conn.instance_url == "https://test.service-now.com"
