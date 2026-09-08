"""Metadata timestamps must carry the stored half, which is UTC.

ServiceNow returns a datetime twice under ``sysparm_display_value=all``: the
``value`` half is what it stores, in UTC, and the ``display_value`` half is that
moment rendered in the timezone of whoever signed in. On a developer instance
those were measured seven hours apart.

Every loader read the display half into metadata, so anything joining a document
against a metric or a log was wrong by the account's offset, with nothing to see.
The page content still shows the local rendering, because that text is written to
be read. These tests pin the split.

Author: Roni Das
Created: 2026-09-08
"""

from __future__ import annotations

import pytest

from snowloader.connection import SnowConnection
from snowloader.loaders.attachments import AttachmentLoader
from snowloader.loaders.catalog import CatalogLoader
from snowloader.loaders.changes import ChangeLoader
from snowloader.loaders.cmdb import CMDBLoader
from snowloader.loaders.incidents import IncidentLoader
from snowloader.loaders.knowledge_base import KnowledgeBaseLoader
from snowloader.loaders.problems import ProblemLoader

BASE_URL = "https://test.service-now.com"

# The two halves of one moment, seven hours apart, as a developer instance returns
# them. STORED is the UTC one.
STORED = "2026-09-06 14:29:11"
SHOWN = "2026-09-06 07:29:11"


def _both_halves() -> dict[str, str]:
    return {"display_value": SHOWN, "value": STORED}


def _connection() -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret")


def _record(**extra: object) -> dict[str, object]:
    """A record carrying both halves of every timestamp a loader might read."""
    base: dict[str, object] = {
        "sys_id": "0" * 32,
        "number": "INC0010001",
        "short_description": "health check flapping",
        "sys_created_on": _both_halves(),
        "sys_updated_on": _both_halves(),
        "opened_at": _both_halves(),
        "resolved_at": _both_halves(),
        "closed_at": _both_halves(),
        "start_date": _both_halves(),
        "end_date": _both_halves(),
    }
    base.update(extra)
    return base


LOADERS_AND_FIELDS = [
    (IncidentLoader, ["sys_created_on", "sys_updated_on", "opened_at", "resolved_at", "closed_at"]),
    (ProblemLoader, ["sys_created_on", "sys_updated_on", "opened_at", "resolved_at"]),
    (ChangeLoader, ["sys_created_on", "sys_updated_on", "start_date", "end_date"]),
    (CMDBLoader, ["sys_created_on", "sys_updated_on"]),
    (CatalogLoader, ["sys_created_on", "sys_updated_on"]),
    (KnowledgeBaseLoader, ["sys_created_on", "sys_updated_on"]),
    (AttachmentLoader, ["sys_created_on", "sys_updated_on"]),
]


@pytest.mark.parametrize(
    "loader_class, fields",
    LOADERS_AND_FIELDS,
    ids=[c.__name__ for c, _ in LOADERS_AND_FIELDS],
)
def test_metadata_timestamps_use_the_stored_half(loader_class, fields):
    # Arrange
    loader = loader_class(_connection())

    # Act
    document = loader._record_to_document(_record())

    # Assert
    for field in fields:
        assert document.metadata[field] == STORED, (
            f"{loader_class.__name__} metadata[{field!r}] returned the displayed half. "
            f"Anything joining on it is wrong by the signed-in account's UTC offset."
        )


def test_page_content_keeps_the_readable_half():
    # Arrange
    loader = IncidentLoader(_connection())

    # Act
    document = loader._record_to_document(_record())

    # Assert
    assert SHOWN in document.page_content
    assert STORED not in document.page_content


def test_a_plain_string_timestamp_survives_unchanged():
    """display_value=false returns a bare string, and there is no half to choose."""
    # Arrange
    loader = IncidentLoader(_connection())

    # Act
    document = loader._record_to_document(_record(opened_at=STORED))

    # Assert
    assert document.metadata["opened_at"] == STORED


def test_a_missing_timestamp_stays_empty():
    # Arrange
    loader = IncidentLoader(_connection())

    # Act
    document = loader._record_to_document(_record(closed_at=""))

    # Assert
    assert document.metadata["closed_at"] == ""
