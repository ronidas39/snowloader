"""Lightweight HTML-to-text converter for ServiceNow content.

ServiceNow stores Knowledge Base article bodies as HTML, which is not great
for feeding into language models or embedding pipelines. This module provides
a simple, dependency-free cleaner that strips HTML tags and converts common
constructs into readable plain text.

We intentionally avoid pulling in BeautifulSoup or lxml for this. The HTML
coming out of ServiceNow is relatively tame (mostly paragraphs, lists, basic
formatting) and a regex-based approach handles it well enough. The re module
from stdlib is all we need.

Author: Roni Das
"""

from __future__ import annotations

import html
import re


def clean_html(raw_html: str) -> str:
    """Convert an HTML string to clean plain text.

    Handles the common patterns found in ServiceNow KB articles:
        - <br> and <br/> tags become newlines
        - </p>, </div>, </li> tags become newlines for paragraph separation
        - All remaining HTML tags are stripped
        - HTML entities (&amp;, &lt;, &gt;, etc.) are decoded
        - Excess whitespace and blank lines are collapsed

    Args:
        raw_html: The HTML string to clean. Can be empty.

    Returns:
        Plain text with reasonable formatting preserved.
    """
    if not raw_html:
        return ""

    text = raw_html

    # Turn <br> variants into newlines before we strip tags
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # Block-level closing tags get newlines to preserve paragraph structure
    text = re.sub(r"</(?:p|div|li|tr|h[1-6])>", "\n", text, flags=re.IGNORECASE)

    # Strip all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Decode HTML entities (has to happen after tag removal)
    text = html.unescape(text)

    # Collapse runs of whitespace on each line, but keep newlines
    lines = text.split("\n")
    lines = [line.strip() for line in lines]

    # Remove excessive blank lines (keep at most one blank line between paragraphs)
    cleaned_lines: list[str] = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                cleaned_lines.append("")
            prev_blank = True
        else:
            cleaned_lines.append(line)
            prev_blank = False

    # Strip leading/trailing blank lines from the whole result
    result = "\n".join(cleaned_lines).strip()
    return result
