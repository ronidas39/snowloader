"""The reported version must match the version actually published.

``__version__`` was maintained by hand and drifted. 0.5.1 and 0.6.0 both
shipped reporting 0.5.0, so ``snowloader --version`` and any user code reading
``snowloader.__version__`` gave the wrong answer, and a bug report would name a
release that was not the one running.

Reading it from the installed metadata makes the drift impossible rather than
merely fixed, and this test holds that.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import pathlib
import re

import snowloader


def _pyproject_version() -> str:
    root = pathlib.Path(__file__).resolve().parents[2]
    text = (root / "pyproject.toml").read_text()
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match, "no version in pyproject.toml"
    return match.group(1)


def test_dunder_version_matches_pyproject() -> None:
    assert snowloader.__version__ == _pyproject_version()


def test_version_is_not_a_placeholder() -> None:
    """An uninstalled package falls back to a marker. It must never ship."""
    assert "unknown" not in snowloader.__version__


def test_cli_reports_the_same_version() -> None:
    """snowloader --version reads __version__, so it drifts with it."""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "snowloader.cli", "--version"],
        capture_output=True, text=True, timeout=60,
    )
    assert _pyproject_version() in (out.stdout + out.stderr)
