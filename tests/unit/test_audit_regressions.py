"""Regressions for the gaps a pre-release audit found in 0.3.0.

Each test here corresponds to something that was claimed in the README, the
changelog or a docstring, and was not true of the code.

Author: Roni Das
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import responses

from snowloader import (
    AttachmentLoader,
    CatalogLoader,
    ChangeLoader,
    CMDBLoader,
    IncidentLoader,
    KnowledgeBaseLoader,
    ProblemLoader,
    RelationshipLoader,
    SnowConnection,
    SweepReport,
    TableLoader,
)

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"

GROUP_ID = "d625dccec0a8016700a222a0f7900d06"
ATTACH_ID = "1f2e3d4c5b6a79880123456789abcdef"


def _conn(**overrides: Any) -> SnowConnection:
    kwargs: dict[str, Any] = {
        "instance_url": BASE_URL,
        "username": "admin",
        "password": "secret",
        "page_size": 10,
    }
    kwargs.update(overrides)
    return SnowConnection(**kwargs)


LOADERS = [
    IncidentLoader,
    KnowledgeBaseLoader,
    CMDBLoader,
    ChangeLoader,
    ProblemLoader,
    CatalogLoader,
    AttachmentLoader,
    RelationshipLoader,
]


@pytest.mark.parametrize("loader_class", LOADERS, ids=lambda c: c.__name__)
def test_every_loader_accepts_the_documented_escape_hatches(loader_class: Any) -> None:
    """The README tells upgraders to pass expand_references=False.

    On CMDBLoader and AttachmentLoader that used to raise TypeError, so the
    documented way out of the metadata change did not exist for the two
    loaders whose records are widest.
    """
    conn = _conn()
    try:
        loader_class(connection=conn, expand_references=False, include_raw=True)
    finally:
        conn.close()


def test_table_loader_accepts_them_too() -> None:
    conn = _conn()
    try:
        TableLoader(conn, table="sc_task", expand_references=False, include_raw=True)
    finally:
        conn.close()


def test_attachment_loader_expands_references_like_every_other_loader() -> None:
    """AttachmentLoader was the one loader that never called _build_metadata,
    so it got none of the reference expansion the changelog promised."""
    record = {
        "sys_id": ATTACH_ID,
        "file_name": "runbook.pdf",
        "content_type": "application/pdf",
        "size_bytes": "2048",
        "table_name": "kb_knowledge",
        "table_sys_id": ATTACH_ID,
        "sys_created_by": {"display_value": "David Loo", "value": GROUP_ID},
    }
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/sys_attachment(\?.*)?$"),
            json={"result": [record]},
            status=200,
        )
        conn = _conn()
        try:
            metadata = AttachmentLoader(connection=conn).load()[0].metadata
        finally:
            conn.close()

    assert metadata["sys_created_by"] == "David Loo"
    assert metadata["sys_created_by_sys_id"] == GROUP_ID


def test_attachment_loader_can_turn_expansion_off() -> None:
    record = {
        "sys_id": ATTACH_ID,
        "file_name": "a.pdf",
        "sys_created_by": {"display_value": "David Loo", "value": GROUP_ID},
    }
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            re.compile(rf"^{re.escape(TABLE_API)}/sys_attachment(\?.*)?$"),
            json={"result": [record]},
            status=200,
        )
        conn = _conn()
        try:
            metadata = AttachmentLoader(connection=conn, expand_references=False).load()[0].metadata
        finally:
            conn.close()

    assert "sys_created_by_sys_id" not in metadata


def test_a_sweep_that_skipped_a_page_is_not_reported_complete() -> None:
    """The totals can line up while a page was thrown away, if the table grew
    during the read. A sweep known to have dropped a page is not complete."""
    report = SweepReport(
        table="cmdb_ci",
        query=None,
        expected=1000,
        returned=1000,
        distinct=1000,
        failed_pages=3,
    )
    assert report.complete is False


def test_a_clean_sweep_is_still_complete() -> None:
    report = SweepReport(
        table="cmdb_ci",
        query=None,
        expected=10,
        returned=10,
        distinct=10,
    )
    assert report.complete is True
