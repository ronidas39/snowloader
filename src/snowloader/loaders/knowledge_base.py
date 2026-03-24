"""Knowledge Base article loader for snowloader.

Fetches articles from the ServiceNow kb_knowledge table and converts them
into SnowDocuments with clean plain text content. The HTML body that
ServiceNow stores is run through our built-in cleaner so downstream
systems get readable text instead of raw markup.

Some KB articles use a wiki-format field instead of the HTML text field.
The loader checks both and falls back to wiki content when text is empty.

Author: Roni Das
"""

from __future__ import annotations

import logging
from typing import Any

from snowloader.loaders.incidents import _display_value
from snowloader.models import BaseSnowLoader, SnowDocument
from snowloader.utils.html_cleaner import clean_html

logger = logging.getLogger(__name__)


class KnowledgeBaseLoader(BaseSnowLoader):
    """Loads Knowledge Base articles from ServiceNow.

    Produces documents where page_content contains the article title
    followed by the cleaned body text. HTML from the text field is
    automatically stripped and converted to plain text. If the text
    field is empty, the loader falls back to the wiki field.

    Metadata includes the article number, knowledge base name, topic,
    category, author, workflow state, and timestamps.

    Args:
        connection: An initialized SnowConnection instance.
        query: Optional encoded query for filtering articles.
        fields: Optional field list override.
        include_journals: Whether to append journal entries.

    Example:
        conn = SnowConnection(...)
        loader = KnowledgeBaseLoader(conn, query="workflow_state=published")
        for doc in loader.lazy_load():
            print(doc.page_content[:200])
    """

    table = "kb_knowledge"
    content_fields = ["short_description", "text"]

    def _record_to_document(self, record: dict[str, Any]) -> SnowDocument:
        """Build a KB article document from a raw API record.

        Cleans the HTML body and assembles a readable document with
        the article title up front. Falls back to the wiki field
        when the text field is empty.

        Args:
            record: Raw kb_knowledge record dict from the API.

        Returns:
            SnowDocument with cleaned article content and metadata.
        """
        number = _display_value(record.get("number"))
        title = _display_value(record.get("short_description"))
        raw_text = _display_value(record.get("text"))
        wiki_text = _display_value(record.get("wiki"))

        # Clean the HTML body, or fall back to wiki content
        if raw_text:
            body = clean_html(raw_text)
        elif wiki_text:
            body = wiki_text
        else:
            body = ""

        # Put the title first, then the body
        lines = [f"Article: {number}", f"Title: {title}"]
        if body:
            lines.append("")
            lines.append(body)

        page_content = "\n".join(lines)

        sys_id = str(record.get("sys_id", ""))
        metadata: dict[str, Any] = {
            "sys_id": sys_id,
            "number": number,
            "table": self.table,
            "source": f"servicenow://kb_knowledge/{number}",
            "title": title,
            "topic": _display_value(record.get("topic")),
            "category": _display_value(record.get("category")),
            "author": _display_value(record.get("author")),
            "kb_knowledge_base": _display_value(record.get("kb_knowledge_base")),
            "workflow_state": _display_value(record.get("workflow_state")),
            "sys_created_on": _display_value(record.get("sys_created_on")),
            "sys_updated_on": _display_value(record.get("sys_updated_on")),
        }

        return SnowDocument(page_content=page_content, metadata=metadata)
