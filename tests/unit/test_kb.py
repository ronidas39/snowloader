"""Tests for KnowledgeBaseLoader.

Covers table config, document assembly from KB articles, HTML cleaning
integration, metadata population, the wiki field fallback, and handling
of articles with empty bodies.

Author: Roni Das
"""

from __future__ import annotations

import responses

from snowloader.connection import SnowConnection
from snowloader.loaders.knowledge_base import KnowledgeBaseLoader

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"


def _make_connection() -> SnowConnection:
    return SnowConnection(instance_url=BASE_URL, username="admin", password="secret")


SAMPLE_KB_ARTICLE: dict = {
    "sys_id": "kb_001",
    "number": "KB0010001",
    "short_description": "How to reset your email password",
    "text": "<p>Follow these steps to reset your password:</p>"
    "<ol><li>Go to the portal</li><li>Click <strong>Forgot Password</strong></li>"
    "<li>Enter your email &amp; click submit</li></ol>",
    "wiki": "",
    "topic": "Email",
    "category": "How-To",
    "author": {"display_value": "Sarah Lee", "value": "user_sys_id_002"},
    "kb_knowledge_base": {"display_value": "IT Self-Service", "value": "kb_base_001"},
    "workflow_state": "published",
    "sys_created_on": "2024-03-10 08:00:00",
    "sys_updated_on": "2024-05-20 14:30:00",
}


def test_kb_loader_table_name() -> None:
    """KnowledgeBaseLoader should target the kb_knowledge table."""
    loader = KnowledgeBaseLoader(connection=_make_connection())
    assert loader.table == "kb_knowledge"


@responses.activate
def test_kb_to_document_basic() -> None:
    """A KB article should produce a document with the title and cleaned
    body text."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/kb_knowledge",
        json={"result": [SAMPLE_KB_ARTICLE]},
        status=200,
    )

    loader = KnowledgeBaseLoader(connection=_make_connection())
    docs = loader.load()

    assert len(docs) == 1
    content = docs[0].page_content
    assert "How to reset your email password" in content
    assert "Follow these steps" in content
    assert "Forgot Password" in content


@responses.activate
def test_kb_html_cleaning_strips_tags() -> None:
    """The HTML in the text field should be cleaned to plain text, no
    tags remaining in the document content."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/kb_knowledge",
        json={"result": [SAMPLE_KB_ARTICLE]},
        status=200,
    )

    loader = KnowledgeBaseLoader(connection=_make_connection())
    docs = loader.load()
    content = docs[0].page_content

    assert "<p>" not in content
    assert "<ol>" not in content
    assert "<li>" not in content
    assert "<strong>" not in content


@responses.activate
def test_kb_html_cleaning_preserves_line_breaks() -> None:
    """After cleaning, the text should still have some structure from
    the original HTML formatting."""
    article = {
        **SAMPLE_KB_ARTICLE,
        "text": "<p>Step one.</p><p>Step two.</p>",
    }
    responses.add(
        responses.GET,
        f"{TABLE_API}/kb_knowledge",
        json={"result": [article]},
        status=200,
    )

    loader = KnowledgeBaseLoader(connection=_make_connection())
    docs = loader.load()
    content = docs[0].page_content

    assert "Step one." in content
    assert "Step two." in content


@responses.activate
def test_kb_html_cleaning_handles_entities() -> None:
    """HTML entities like &amp; should be decoded in the final output."""
    article = {
        **SAMPLE_KB_ARTICLE,
        "text": "<p>Q &amp; A section</p>",
    }
    responses.add(
        responses.GET,
        f"{TABLE_API}/kb_knowledge",
        json={"result": [article]},
        status=200,
    )

    loader = KnowledgeBaseLoader(connection=_make_connection())
    docs = loader.load()
    content = docs[0].page_content

    assert "Q & A section" in content


@responses.activate
def test_kb_metadata_keys() -> None:
    """Metadata should include the essential keys for filtering and
    linking back to ServiceNow."""
    responses.add(
        responses.GET,
        f"{TABLE_API}/kb_knowledge",
        json={"result": [SAMPLE_KB_ARTICLE]},
        status=200,
    )

    loader = KnowledgeBaseLoader(connection=_make_connection())
    docs = loader.load()
    meta = docs[0].metadata

    assert meta["sys_id"] == "kb_001"
    assert meta["number"] == "KB0010001"
    assert meta["table"] == "kb_knowledge"
    assert "source" in meta


@responses.activate
def test_kb_with_wiki_field() -> None:
    """If the text field is empty but wiki has content, the loader should
    fall back to using the wiki field as the article body."""
    article = {
        **SAMPLE_KB_ARTICLE,
        "text": "",
        "wiki": "This is wiki-format content about password resets.",
    }
    responses.add(
        responses.GET,
        f"{TABLE_API}/kb_knowledge",
        json={"result": [article]},
        status=200,
    )

    loader = KnowledgeBaseLoader(connection=_make_connection())
    docs = loader.load()
    content = docs[0].page_content

    assert "wiki-format content about password resets" in content


@responses.activate
def test_kb_empty_body() -> None:
    """An article with no text and no wiki content should still produce
    a valid document (just with the title and metadata)."""
    article = {
        **SAMPLE_KB_ARTICLE,
        "text": "",
        "wiki": "",
    }
    responses.add(
        responses.GET,
        f"{TABLE_API}/kb_knowledge",
        json={"result": [article]},
        status=200,
    )

    loader = KnowledgeBaseLoader(connection=_make_connection())
    docs = loader.load()

    assert len(docs) == 1
    assert "How to reset your email password" in docs[0].page_content
