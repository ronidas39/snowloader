"""Tests for CatalogLoader.

Covers table config, basic document assembly, price handling, and
metadata population for service catalog items.

Author: Roni Das
"""

from __future__ import annotations

import responses

from snowloader.connection import SnowConnection
from snowloader.loaders.catalog import CatalogLoader

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"


def _make_connection() -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret")


SAMPLE_CATALOG_ITEM: dict = {
    "sys_id": "cat_001",
    "name": "Request a New Laptop",
    "short_description": "Submit a request for a new laptop with standard configuration.",
    "description": "Use this form to request a new laptop. Standard config includes "
    "16GB RAM, 512GB SSD, and your choice of Windows 11 or macOS. "
    "Delivery takes 5-7 business days after approval.",
    "category": {"display_value": "Hardware", "value": "hw_cat_001"},
    "sc_catalogs": {"display_value": "Service Catalog", "value": "sc_001"},
    "price": "1200.00",
    "active": "true",
    "order": "100",
    "sys_created_on": "2023-08-01 10:00:00",
    "sys_updated_on": "2024-04-15 09:00:00",
}


def test_catalog_loader_table_name() -> None:
    """CatalogLoader should target the sc_cat_item table."""
    loader = CatalogLoader(connection=_make_connection())
    assert loader.table == "sc_cat_item"


@responses.activate
def test_catalog_to_document_basic() -> None:
    """A catalog item should produce a document with the item name,
    summary, and full description."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/sc_cat_item",
        json={"result": [SAMPLE_CATALOG_ITEM]},
        status=200,
    )

    loader = CatalogLoader(connection=_make_connection())
    docs = loader.load()

    assert len(docs) == 1
    content = docs[0].page_content
    assert "Request a New Laptop" in content
    assert "16GB RAM" in content


@responses.activate
def test_catalog_with_price() -> None:
    """Items with a price should show it in the document text."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/sc_cat_item",
        json={"result": [SAMPLE_CATALOG_ITEM]},
        status=200,
    )

    loader = CatalogLoader(connection=_make_connection())
    docs = loader.load()
    content = docs[0].page_content

    assert "1200" in content


@responses.activate
def test_catalog_metadata_keys() -> None:
    """Metadata should carry the item identification and catalog info."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/sc_cat_item",
        json={"result": [SAMPLE_CATALOG_ITEM]},
        status=200,
    )

    loader = CatalogLoader(connection=_make_connection())
    docs = loader.load()
    meta = docs[0].metadata

    assert meta["sys_id"] == "cat_001"
    assert meta["name"] == "Request a New Laptop"
    assert meta["table"] == "sc_cat_item"
    assert "source" in meta
