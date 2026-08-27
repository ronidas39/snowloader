"""CMDB relationship loader for snowloader.

:class:`snowloader.CMDBLoader` can traverse relationships, but it does so per
CI: two extra queries for every configuration item. Measured against a
developer instance that came to 2.4 seconds per CI, which projects to about
34 hours for a 50,000 CI estate. Sweeping ``cmdb_rel_ci`` directly returned
every edge on that instance in 7 seconds.

Every edge already carries both halves of parent, child and type, so the
result is loadable into a graph with no resolution step.

Author: Roni Das
Created: 2026-08-27
"""

from __future__ import annotations

import logging
from typing import Any

from snowloader.connection import SnowConnection
from snowloader.loaders._field_utils import display_value as _display_value
from snowloader.loaders._field_utils import raw_value as _raw_value
from snowloader.models import BaseSnowLoader, SnowDocument

logger = logging.getLogger(__name__)


class RelationshipLoader(BaseSnowLoader):
    """Loads CI relationships as one document per edge.

    Args:
        connection: An initialized SnowConnection instance.
        query: Optional encoded query, e.g. ``"parent=<sys_id>"`` to pull
            one CI's edges, or a type filter to pull one kind of edge.
        fields: Optional field list override.
        expand_references: Surface both halves of every field in metadata.
            Defaults to True.
        include_raw: Attach the untouched API record under ``"raw"``.

    Example:
        >>> for doc in RelationshipLoader(conn).lazy_load():
        ...     graph.add_edge(
        ...         doc.metadata["parent_sys_id"],
        ...         doc.metadata["child_sys_id"],
        ...         type=doc.metadata["type"],
        ...     )
    """

    table = "cmdb_rel_ci"
    content_fields = ["parent", "type", "child"]

    def __init__(
        self,
        connection: SnowConnection,
        query: str | None = None,
        fields: list[str] | None = None,
        expand_references: bool = True,
        include_raw: bool = False,
    ) -> None:
        super().__init__(
            connection=connection,
            query=query,
            fields=fields,
            include_journals=False,
            expand_references=expand_references,
            include_raw=include_raw,
        )

    def _record_to_document(self, record: dict[str, Any]) -> SnowDocument:
        """Build one document from one cmdb_rel_ci row.

        Args:
            record: Raw relationship record dict from the ServiceNow API.

        Returns:
            SnowDocument describing the edge, with both endpoints reachable
            as sys_ids in metadata.
        """
        parent = _display_value(record.get("parent"))
        child = _display_value(record.get("child"))
        rel_type = _display_value(record.get("type"))

        # ServiceNow names a relationship from both ends at once, as in
        # "Depends on::Used by". The arrow keeps the direction readable
        # without having to know that convention.
        page_content = f"{parent} -[{rel_type}]-> {child}"

        metadata: dict[str, Any] = {
            "sys_id": _raw_value(record.get("sys_id")),
            "table": self.table,
            "parent": parent,
            "parent_sys_id": _raw_value(record.get("parent")),
            "child": child,
            "child_sys_id": _raw_value(record.get("child")),
            "type": rel_type,
            "type_sys_id": _raw_value(record.get("type")),
        }

        return SnowDocument(
            page_content=page_content,
            metadata=self._build_metadata(record, metadata),
        )
