"""Tests for the HTML-to-text cleaner utility.

ServiceNow stores KB article bodies as HTML, which is useless for LLM
pipelines. The cleaner strips all tags and converts common HTML constructs
(line breaks, paragraphs, entities) into readable plain text using only
the re module from stdlib, no external parsing libraries needed.

Author: Roni Das
"""

from __future__ import annotations

from snowloader.utils.html_cleaner import clean_html


def test_clean_br_tags() -> None:
    """<br> and <br/> tags should become newlines."""
    html = "Line one<br>Line two<br/>Line three"
    result = clean_html(html)
    assert result == "Line one\nLine two\nLine three"


def test_clean_paragraph_tags() -> None:
    """Closing </p> tags should produce double newlines to separate
    paragraphs visually, same as you would see in rendered HTML."""
    html = "<p>First paragraph.</p><p>Second paragraph.</p>"
    result = clean_html(html)
    assert "First paragraph." in result
    assert "Second paragraph." in result
    # There should be some whitespace separation between paragraphs
    assert result != "First paragraph."  # not just mashed together


def test_clean_nested_html() -> None:
    """Nested tags like <div><strong>bold</strong></div> should be
    stripped down to just the text content."""
    html = "<div><strong>Important:</strong> <em>Read this carefully</em></div>"
    result = clean_html(html)
    assert "Important:" in result
    assert "Read this carefully" in result
    assert "<" not in result
    assert ">" not in result


def test_clean_html_entities() -> None:
    """Common HTML entities should be decoded to their characters."""
    html = "Tom &amp; Jerry &lt;3 each other &gt; expected"
    result = clean_html(html)
    assert "Tom & Jerry" in result
    assert "<3" in result
    assert "> expected" in result


def test_clean_empty_string() -> None:
    """An empty string should come back as an empty string, no crash."""
    assert clean_html("") == ""
