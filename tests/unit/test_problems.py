"""Tests for ProblemLoader.

Covers table config, basic document assembly, root cause analysis,
known error flagging, and metadata population for problem records.

Author: Roni Das
"""

from __future__ import annotations

import responses

from snowloader.connection import SnowConnection
from snowloader.loaders.problems import ProblemLoader

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"


def _make_connection() -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret")


SAMPLE_PROBLEM: dict = {
    "sys_id": "prb_001",
    "number": "PRB0070001",
    "short_description": "Recurring email delivery failures every Monday morning",
    "description": "Multiple incidents reported each Monday between 8-9am where "
    "outbound email gets stuck in the queue for 30-60 minutes.",
    "state": {"display_value": "Root Cause Analysis", "value": "2"},
    "priority": {"display_value": "2 - High", "value": "2"},
    "category": "email",
    "assigned_to": {"display_value": "Sarah Lee", "value": "user_002"},
    "assignment_group": {"display_value": "Email Support", "value": "group_002"},
    "cmdb_ci": {"display_value": "EXCH-PROD-01", "value": "ci_001"},
    "cause_notes": "Antivirus scan kicks off at 8am and saturates disk I/O on the "
    "Exchange server, causing the transport service to back up.",
    "known_error": "true",
    "fix_notes": "Reschedule the AV scan to 3am when email volume is low.",
    "opened_at": "2024-06-10 09:00:00",
    "resolved_at": "",
    "closed_at": "",
    "sys_created_on": "2024-06-10 09:00:00",
    "sys_updated_on": "2024-06-20 16:00:00",
}


def test_problem_loader_table_name() -> None:
    """ProblemLoader should target the problem table."""
    loader = ProblemLoader(connection=_make_connection())
    assert loader.table == "problem"


@responses.activate
def test_problem_to_document_basic() -> None:
    """A problem record should produce a document with number, summary,
    and description."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/problem",
        json={"result": [SAMPLE_PROBLEM]},
        status=200,
    )

    loader = ProblemLoader(connection=_make_connection())
    docs = loader.load()

    assert len(docs) == 1
    content = docs[0].page_content
    assert "PRB0070001" in content
    assert "Recurring email delivery failures" in content


@responses.activate
def test_problem_with_root_cause() -> None:
    """When cause_notes are present, they should be included in the
    document so the LLM has the root cause analysis available."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/problem",
        json={"result": [SAMPLE_PROBLEM]},
        status=200,
    )

    loader = ProblemLoader(connection=_make_connection())
    docs = loader.load()
    content = docs[0].page_content

    assert "Antivirus scan" in content
    assert "saturates disk I/O" in content


@responses.activate
def test_problem_known_error_flag() -> None:
    """Known errors should be flagged in the document text and the
    fix notes should be included when available."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/problem",
        json={"result": [SAMPLE_PROBLEM]},
        status=200,
    )

    loader = ProblemLoader(connection=_make_connection())
    docs = loader.load()
    content = docs[0].page_content

    assert "Known Error" in content
    assert "Reschedule the AV scan" in content


@responses.activate
def test_problem_metadata_keys() -> None:
    """Metadata should carry the standard identification fields."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/problem",
        json={"result": [SAMPLE_PROBLEM]},
        status=200,
    )

    loader = ProblemLoader(connection=_make_connection())
    docs = loader.load()
    meta = docs[0].metadata

    assert meta["sys_id"] == "prb_001"
    assert meta["number"] == "PRB0070001"
    assert meta["table"] == "problem"
    assert "source" in meta
