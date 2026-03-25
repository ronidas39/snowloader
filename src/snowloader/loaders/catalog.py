"""Service catalog item loader for snowloader.

Fetches catalog items from the ServiceNow sc_cat_item table and formats
them into documents that describe what the item is, what it costs, and
which catalog it belongs to. Useful for LLM-powered service desk chatbots
that need to help users find and request the right services.

Author: Roni Das
"""

from __future__ import annotations

import logging
from typing import Any

from snowloader.loaders.incidents import _display_value
from snowloader.models import BaseSnowLoader, SnowDocument

logger = logging.getLogger(__name__)


class CatalogLoader(BaseSnowLoader):
    """Loads service catalog items from ServiceNow.

    Produces documents that describe catalog offerings with their name,
    description, category, price, and catalog association. The text layout
    is designed for retrieval systems that help end users find the right
    service to request.

    Args:
        connection: An initialized SnowConnection instance.
        query: Optional encoded query for filtering catalog items.
        fields: Optional field list override.

    Example:
        conn = SnowConnection(...)
        loader = CatalogLoader(conn, query="active=true")
        for doc in loader.lazy_load():
            print(doc.page_content[:200])
    """

    table = "sc_cat_item"
    content_fields = ["name", "short_description", "description"]

    def _record_to_document(self, record: dict[str, Any]) -> SnowDocument:
        """Build a catalog item document from a raw API record.

        Args:
            record: Raw sc_cat_item record dict from the API.

        Returns:
            SnowDocument with formatted catalog item content and metadata.
        """
        name = _display_value(record.get("name"))
        summary = _display_value(record.get("short_description"))
        description = _display_value(record.get("description"))
        category = _display_value(record.get("category"))
        catalog = _display_value(record.get("sc_catalogs"))
        price = _display_value(record.get("price"))
        active = _display_value(record.get("active"))

        lines = [
            f"Catalog Item: {name}",
        ]

        if summary:
            lines.append(f"Summary: {summary}")
        if description:
            lines.append(f"Description: {description}")
        if category:
            lines.append(f"Category: {category}")
        if catalog:
            lines.append(f"Catalog: {catalog}")
        if price:
            lines.append(f"Price: {price}")

        page_content = "\n".join(lines)

        sys_id = str(record.get("sys_id", ""))
        metadata: dict[str, Any] = {
            "sys_id": sys_id,
            "name": name,
            "table": self.table,
            "source": f"servicenow://sc_cat_item/{name}",
            "category": category,
            "catalog": catalog,
            "price": price,
            "active": str(active).lower() == "true" if active else False,
            "sys_created_on": _display_value(record.get("sys_created_on")),
            "sys_updated_on": _display_value(record.get("sys_updated_on")),
        }

        return SnowDocument(page_content=page_content, metadata=metadata)
