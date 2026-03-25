"""CMDB Configuration Item loader for snowloader.

Fetches CIs from any CMDB class table (cmdb_ci, cmdb_ci_server,
cmdb_ci_service, etc.) and optionally traverses the relationship graph
via cmdb_rel_ci. This relationship traversal is the main thing that sets
snowloader apart from other ServiceNow data loaders: you get a complete
picture of how CIs connect to each other, formatted for LLM consumption.

Relationships are split into outbound (this CI is the parent) and inbound
(this CI is the child), each shown with directional arrows in the document
text and stored as structured dicts in metadata.

Author: Roni Das
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from snowloader.connection import SnowConnection
from snowloader.loaders._field_utils import display_value as _display_value
from snowloader.loaders._field_utils import raw_value as _raw_value
from snowloader.models import BaseSnowLoader, SnowDocument

logger = logging.getLogger(__name__)


class CMDBLoader(BaseSnowLoader):
    """Loads CMDB Configuration Items with optional relationship traversal.

    By default targets the base cmdb_ci table, but you can point it at any
    CMDB class (cmdb_ci_server, cmdb_ci_service, etc.) with the ci_class
    parameter. When include_relationships is True, the loader makes
    additional queries to cmdb_rel_ci for each CI to map out the
    dependency and containment graph.

    The resulting documents include the CI's identity (name, class, status),
    technical details (IP, FQDN, OS when available), assignment info, and
    a relationship section showing connected CIs with direction arrows.

    Args:
        connection: An initialized SnowConnection instance.
        ci_class: CMDB class table name. Defaults to "cmdb_ci" which
            covers all CI types. Use "cmdb_ci_server" etc. for specific classes.
        query: Optional encoded query for filtering CIs.
        fields: Optional field list override.
        include_relationships: If True, fetches relationship data from
            cmdb_rel_ci for each CI. This adds 2 API calls per CI so
            it is off by default.

    Example:
        conn = SnowConnection(...)
        loader = CMDBLoader(
            conn,
            ci_class="cmdb_ci_server",
            query="operational_status=1",
            include_relationships=True,
        )
        for doc in loader.lazy_load():
            print(doc.page_content[:300])
    """

    table = "cmdb_ci"
    content_fields = ["name", "short_description"]

    def __init__(
        self,
        connection: SnowConnection,
        ci_class: str | None = None,
        query: str | None = None,
        fields: list[str] | None = None,
        include_relationships: bool = False,
        max_relationship_workers: int = 2,
    ) -> None:
        super().__init__(connection=connection, query=query, fields=fields)
        if ci_class:
            self.table = ci_class
        self._include_relationships = include_relationships
        self._max_relationship_workers = max_relationship_workers

    def _record_to_document(self, record: dict[str, Any]) -> SnowDocument:
        """Build a CI document with optional relationship graph.

        Args:
            record: Raw CMDB record dict from the ServiceNow API.

        Returns:
            SnowDocument with CI details and relationship mapping.
        """
        sys_id = str(record.get("sys_id", ""))
        name = _display_value(record.get("name"))
        ci_class = _display_value(record.get("sys_class_name"))
        description = _display_value(record.get("short_description"))
        status = _display_value(record.get("operational_status"))
        environment = _display_value(record.get("environment"))
        ip_address = _display_value(record.get("ip_address"))
        fqdn = _display_value(record.get("fqdn"))
        os_name = _display_value(record.get("os"))
        os_version = _display_value(record.get("os_version"))
        category = _display_value(record.get("category"))
        assigned_to = _display_value(record.get("assigned_to"))
        support_group = _display_value(record.get("support_group"))

        lines = [
            f"Configuration Item: {name}",
            f"Class: {ci_class}",
        ]

        if description:
            lines.append(f"Description: {description}")

        lines.append(f"Status: {status}")

        if environment:
            lines.append(f"Environment: {environment}")
        if category:
            lines.append(f"Category: {category}")

        # Network details (servers, network gear, etc.)
        if ip_address:
            lines.append(f"IP Address: {ip_address}")
        if fqdn:
            lines.append(f"FQDN: {fqdn}")

        # OS info (servers, workstations)
        if os_name:
            os_str = os_name
            if os_version:
                os_str = f"{os_name} {os_version}"
            lines.append(f"OS: {os_str}")

        if assigned_to:
            lines.append(f"Assigned To: {assigned_to}")
        if support_group:
            lines.append(f"Support Group: {support_group}")

        # Fetch and format relationships if requested
        relationship_list: list[dict[str, str]] = []
        if self._include_relationships and sys_id:
            outbound, inbound = self._fetch_relationships(sys_id)
            relationship_list = outbound + inbound

            if outbound or inbound:
                lines.append("")
                lines.append("Relationships:")
                for rel in outbound:
                    lines.append(f"  -> {rel['target']} ({rel['type']})")
                for rel in inbound:
                    lines.append(f"  <- {rel['target']} ({rel['type']})")

        page_content = "\n".join(lines)

        metadata: dict[str, Any] = {
            "sys_id": sys_id,
            "name": name,
            "table": self.table,
            "source": f"servicenow://{self.table}/{name}",
            "sys_class_name": ci_class,
            "operational_status": status,
            "environment": environment,
            "category": category,
            "ip_address": ip_address,
            "fqdn": fqdn,
            "assigned_to": assigned_to,
            "support_group": support_group,
            "sys_created_on": _display_value(record.get("sys_created_on")),
            "sys_updated_on": _display_value(record.get("sys_updated_on")),
        }

        if self._include_relationships:
            metadata["relationships"] = relationship_list

        return SnowDocument(page_content=page_content, metadata=metadata)

    def _fetch_relationships(
        self, sys_id: str
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        """Query cmdb_rel_ci for both outbound and inbound relationships.

        Outbound means this CI is the parent (it depends on or contains
        the child). Inbound means this CI is the child (something else
        depends on or contains it).

        Uses concurrent threads to fetch both directions in parallel,
        roughly halving the wall-clock time per CI. Resilient: if the
        relationship table is inaccessible, logs a warning and returns
        empty lists.

        Args:
            sys_id: The sys_id of the CI to look up relationships for.

        Returns:
            Tuple of (outbound_list, inbound_list), where each entry is
            a dict with "target", "target_sys_id", "type", and "direction".
        """
        from snowloader.connection import SnowConnectionError

        outbound: list[dict[str, str]] = []
        inbound: list[dict[str, str]] = []

        with ThreadPoolExecutor(max_workers=self._max_relationship_workers) as executor:
            future_out = executor.submit(self._fetch_relationship_direction, sys_id, "outbound")
            future_in = executor.submit(self._fetch_relationship_direction, sys_id, "inbound")

            # Extract results individually — a failure in one direction
            # should not discard the other direction's data.
            try:
                outbound = future_out.result()
            except SnowConnectionError:
                logger.warning(
                    "Failed to fetch outbound relationships for CI %s.",
                    sys_id,
                    exc_info=True,
                )

            try:
                inbound = future_in.result()
            except SnowConnectionError:
                logger.warning(
                    "Failed to fetch inbound relationships for CI %s.",
                    sys_id,
                    exc_info=True,
                )

        return outbound, inbound

    def _fetch_relationship_direction(self, sys_id: str, direction: str) -> list[dict[str, str]]:
        """Fetch relationships for one direction (outbound or inbound).

        Args:
            sys_id: CI sys_id.
            direction: Either "outbound" (parent=sys_id, read child)
                or "inbound" (child=sys_id, read parent).

        Returns:
            List of relationship dicts.
        """
        if direction == "outbound":
            query = f"parent={sys_id}"
            target_field = "child"
        else:
            query = f"child={sys_id}"
            target_field = "parent"

        records = self._connection.get_records(
            table="cmdb_rel_ci",
            query=query,
            fields=[target_field, "type"],
        )

        results: list[dict[str, str]] = []
        for record in records:
            target = _display_value(record.get(target_field))
            target_sys_id = _raw_value(record.get(target_field))
            rel_type = _display_value(record.get("type"))

            results.append(
                {
                    "target": target,
                    "target_sys_id": target_sys_id,
                    "type": rel_type,
                    "direction": direction,
                }
            )

        return results
