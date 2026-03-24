"""Utility functions shared across the snowloader package.

Currently houses the HTML cleaner used by KnowledgeBaseLoader to strip
ServiceNow's HTML markup down to plain text. Kept dependency-free on
purpose so we do not need BeautifulSoup or lxml just for this.
"""
