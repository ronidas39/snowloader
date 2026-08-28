"""The counts quoted on the front pages must match reality.

The README is the GitHub page and the PyPI page, and the documentation landing
page repeats the same figures. All three claimed 413 unit tests when there were
418, because the number is written by hand in four places and adding a test
does not touch any of them.

This is the same drift that made ``__version__`` announce the wrong release.
Holding it with a test is cheaper than remembering.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _collected_unit_tests() -> int:
    """Ask pytest how many unit tests exist, rather than counting them here."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit", "-q", "--collect-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    match = re.search(r"(\d+) tests collected", out.stdout)
    assert match, f"could not read a count from pytest:\n{out.stdout[-500:]}"
    return int(match.group(1))


def _quoted_counts(path: pathlib.Path) -> list[int]:
    """Every test count the given page advertises."""
    text = path.read_text()
    return [
        int(n)
        for n in re.findall(r"tests-(\d+)%20passing", text)
        + re.findall(r"<b>(\d+)</b><br>\s*unit tests", text)
        + re.findall(r'snow-stat-value">(\d+)</span><span class="snow-stat-label">unit tests', text)
    ]


def test_readme_quotes_the_real_test_count() -> None:
    actual = _collected_unit_tests()
    quoted = _quoted_counts(ROOT / "README.md")
    assert quoted, "the README no longer quotes a test count anywhere"
    assert all(n == actual for n in quoted), f"README says {quoted}, pytest collects {actual}"


def test_docs_landing_page_quotes_the_real_test_count() -> None:
    actual = _collected_unit_tests()
    quoted = _quoted_counts(ROOT / "docs" / "index.rst")
    assert quoted, "the docs landing page no longer quotes a test count"
    assert all(n == actual for n in quoted), (
        f"docs/index.rst says {quoted}, pytest collects {actual}"
    )
