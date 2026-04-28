"""Utility functions shared across the snowloader package.

Houses the HTML cleaner used by KnowledgeBaseLoader and parsing helpers for
ServiceNow field values. Kept dependency-free on purpose so we do not need
BeautifulSoup or lxml just for these conveniences.
"""

from __future__ import annotations

from snowloader.utils.html_cleaner import clean_html
from snowloader.utils.parsing import parse_labelled_int

__all__ = [
    "clean_html",
    "parse_labelled_int",
]
