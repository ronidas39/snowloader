"""Tests for what happens when a 200 response carries a body that is not an object.

Some ServiceNow front ends, and shared WAF layers in front of them, answer a
perfectly ordinary request with HTTP 200 and a body of ``null`` under load.
Parsed, that is a valid JSON document, so nothing about the response looks
wrong until something calls ``.get("result")`` on None.

The async path has refused those since 0.2.3. The sync paths did not, and the
consequences were worse there: the sequential reader raised an AttributeError
that no ``except SnowConnectionError`` would catch, and the threaded reader
turned every affected page into an empty list and reported success.

Author: Roni Das
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import responses

from snowloader.connection import SnowConnection
from snowloader.exceptions import SnowConnectionError, SweepIncompleteError

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"
STATS_API = f"{BASE_URL}/api/now/stats"
INCIDENT = re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$")


def _conn(**overrides: Any) -> SnowConnection:
    kwargs: dict[str, Any] = {
        "instance_url": BASE_URL,
        "username": "admin",
        "password": "secret",
        "page_size": 10,
        "max_retries": 1,
        "retry_backoff": 0.0,
    }
    kwargs.update(overrides)
    return SnowConnection(**kwargs)


def _rows(start: int, count: int) -> list[dict[str, str]]:
    return [{"sys_id": f"{i:032x}"} for i in range(start, start + count)]


@pytest.mark.parametrize("body", ["null", "[]", '"a string"', "42"])
def test_sequential_refuses_a_non_object_body(body: str) -> None:
    """Anything that is not a JSON object is refused as a connection error.

    Before this was fixed, ``null`` produced an AttributeError from deep
    inside the pagination loop, which is not catchable by the exception the
    library documents.
    """
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(responses.GET, INCIDENT, body=body, status=200, content_type="application/json")
        conn = _conn()
        try:
            with pytest.raises(SnowConnectionError, match="non-object JSON"):
                list(conn.get_records("incident"))
        finally:
            conn.close()


def test_threaded_refuses_a_non_object_body_rather_than_dropping_the_page() -> None:
    """The threaded reader used to turn a null body into an empty page.

    That is the exact failure mode this release exists to remove: 250 records
    expected, zero returned, and not one error raised anywhere.
    """
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "250"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, body="null", status=200, content_type="application/json")
        conn = _conn()
        try:
            with pytest.raises(SnowConnectionError, match="non-object JSON"):
                list(conn.concurrent_get_records("incident", max_workers=2))
        finally:
            conn.close()


def test_a_non_object_body_is_retried_before_it_is_refused() -> None:
    """It is a transient condition, so a retry should recover it."""
    calls = {"n": 0}

    def flaky(request: Any) -> tuple[int, dict[str, str], str]:
        import json as _json

        calls["n"] += 1
        if calls["n"] == 1:
            return (200, {"Content-Type": "application/json"}, "null")
        return (200, {"Content-Type": "application/json"}, _json.dumps({"result": _rows(0, 3)}))

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_callback(responses.GET, INCIDENT, callback=flaky, content_type="application/json")
        conn = _conn(max_retries=3)
        try:
            records = list(conn.get_records("incident"))
        finally:
            conn.close()

    assert len(records) == 3
    assert calls["n"] == 2


def test_verification_still_catches_it_when_pages_are_skipped() -> None:
    """on_error='skip' plus verify=True must report the loss, not hide it."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "30"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, body="null", status=200, content_type="application/json")
        conn = _conn()
        try:
            with pytest.raises(SweepIncompleteError) as excinfo:
                list(
                    conn.concurrent_get_records(
                        "incident", max_workers=2, on_error="skip", verify=True
                    )
                )
        finally:
            conn.close()

    assert excinfo.value.report.missing == 30
    assert excinfo.value.report.failed_pages > 0
