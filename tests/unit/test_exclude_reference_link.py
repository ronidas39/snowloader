"""Reference links are dropped from record reads unless asked for.

ServiceNow puts a ``link`` beside every reference field, pointing back at the
instance. The sys_id is already in ``value`` and the label is already in
``display_value``, so the URL is reconstructible and nothing here reads it. It
costs response size on every reference of every record, and it carries the
instance hostname into whatever consumes the documents.

Author: Roni Das
Created: 2026-09-08
"""

from __future__ import annotations

import pytest
import responses

from snowloader.async_connection import AsyncSnowConnection
from snowloader.connection import SnowConnection

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"


def _connection(**kwargs: object) -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret", **kwargs)


@responses.activate
def test_reference_links_are_excluded_by_default():
    # Arrange
    connection = _connection()
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": []}, status=200)

    # Act
    list(connection.get_records("incident"))

    # Assert
    assert responses.calls[0].request.params["sysparm_exclude_reference_link"] == "true"


@responses.activate
def test_reference_links_are_kept_when_asked_for():
    # Arrange
    connection = _connection(exclude_reference_link=False)
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": []}, status=200)

    # Act
    list(connection.get_records("incident"))

    # Assert
    assert "sysparm_exclude_reference_link" not in responses.calls[0].request.params


@responses.activate
def test_the_count_endpoint_does_not_send_it():
    """A count returns no records, so there is no reference field to trim."""
    # Arrange
    connection = _connection()
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/now/stats/incident",
        json={"result": {"stats": {"count": "7"}}},
        status=200,
    )

    # Act
    total = connection.get_count("incident")

    # Assert
    assert total == 7
    assert "sysparm_exclude_reference_link" not in responses.calls[0].request.params


@pytest.mark.parametrize("display_value", ["true", "false", "all"])
@responses.activate
def test_it_is_sent_whatever_the_display_value_setting(display_value):
    # Arrange
    connection = _connection(display_value=display_value)
    responses.add(responses.GET, f"{TABLE_API}/incident", json={"result": []}, status=200)

    # Act
    list(connection.get_records("incident"))

    # Assert
    assert responses.calls[0].request.params["sysparm_exclude_reference_link"] == "true"


def test_the_flag_defaults_to_true_on_the_connection():
    # Arrange, Act
    connection = _connection()

    # Assert
    assert connection.exclude_reference_link is True


@pytest.mark.asyncio
async def test_the_async_connection_excludes_them_too():
    """The async path builds its own params, so it needs its own check."""
    # Arrange
    connection = AsyncSnowConnection(instance_url=BASE_URL, username="admin", password="secret")

    # Act
    params = connection._build_query_params()
    await connection.aclose()

    # Assert
    assert params["sysparm_exclude_reference_link"] == "true"


@pytest.mark.asyncio
async def test_the_async_connection_keeps_them_when_asked():
    # Arrange
    connection = AsyncSnowConnection(
        instance_url=BASE_URL,
        username="admin",
        password="secret",
        exclude_reference_link=False,
    )

    # Act
    params = connection._build_query_params()
    await connection.aclose()

    # Assert
    assert "sysparm_exclude_reference_link" not in params
