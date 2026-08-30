"""Tests for the command line interface.

The library already has correct ordering, verification, resume and a partial
failure policy. The reason for a command is that people were assembling those
by hand and getting it wrong quietly: of the five extraction scripts written
against this package before the CLI existed, two built their own query with a
non-unique sort and one validated by line count, which is the check that
cannot detect the resulting loss.

So the tests that matter here are less about argument parsing than about what
the command refuses to do, and about the safe thing being the default.

Author: Roni Das
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import responses

from snowloader.cli import build_parser, main

BASE_URL = "https://test.service-now.com"
TABLE_API = f"{BASE_URL}/api/now/table"
STATS_API = f"{BASE_URL}/api/now/stats"
INCIDENT = re.compile(rf"^{re.escape(TABLE_API)}/incident(\?.*)?$")

CREDS = ["--instance", BASE_URL, "--user", "admin", "--password", "secret"]


def _rows(start: int, count: int) -> list[dict[str, str]]:
    return [{"sys_id": f"{i:032x}", "number": f"INC{i:07d}"} for i in range(start, start + count)]


# ---------------------------------------------------------------------------
# Argument surface
# ---------------------------------------------------------------------------


def test_parser_requires_a_table() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["extract"])


def test_parser_defaults_to_verifying() -> None:
    """The whole reason this exists is that people forget to check."""
    args = build_parser().parse_args(["extract", "incident", "--out", "x.jsonl"])
    assert args.verify is True


def test_verification_can_be_turned_off_deliberately() -> None:
    args = build_parser().parse_args(["extract", "incident", "--out", "x.jsonl", "--no-verify"])
    assert args.verify is False


def test_fields_are_split_on_commas() -> None:
    args = build_parser().parse_args(
        ["extract", "incident", "--out", "x.jsonl", "--fields", "sys_id,number,state"]
    )
    assert args.fields == ["sys_id", "number", "state"]


# ---------------------------------------------------------------------------
# Extracting
# ---------------------------------------------------------------------------


def test_extract_writes_one_json_object_per_line(tmp_path: Path) -> None:
    out = tmp_path / "incidents.jsonl"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "3"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 3)}, status=200)
        code = main([*CREDS, "extract", "incident", "--out", str(out), "--page-size", "10"])

    assert code == 0
    lines = out.read_text().splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["number"] == "INC0000000"


def test_extract_reports_incomplete_and_fails(tmp_path: Path) -> None:
    """A sweep that lost records must not exit zero. A pipeline downstream has
    no other way to know."""
    out = tmp_path / "incidents.jsonl"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "99"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 3)}, status=200)
        code = main([*CREDS, "extract", "incident", "--out", str(out), "--page-size", "10"])

    assert code != 0


def test_extract_passes_the_query_through(tmp_path: Path) -> None:
    out = tmp_path / "x.jsonl"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "2"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 2)}, status=200)
        main(
            [
                *CREDS,
                "extract",
                "incident",
                "--out",
                str(out),
                "--query",
                "active=true",
                "--page-size",
                "10",
            ]
        )
        sent = [c.request.url for c in rsps.calls if "/api/now/table/" in c.request.url]

    assert "active%3Dtrue" in sent[0] or "active=true" in sent[0]


def test_extract_always_sorts_on_a_unique_key(tmp_path: Path) -> None:
    """The bug the hand-rolled scripts had. It must not be reachable from
    here, whatever the caller passes as a query."""
    from urllib.parse import parse_qs, urlparse

    out = tmp_path / "x.jsonl"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "2"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 2)}, status=200)
        main(
            [
                *CREDS,
                "extract",
                "incident",
                "--out",
                str(out),
                "--query",
                "active=true^ORDERBYsys_created_on",
                "--page-size",
                "10",
            ]
        )
        q = [
            parse_qs(urlparse(c.request.url).query)["sysparm_query"][0]
            for c in rsps.calls
            if "/api/now/table/" in c.request.url
        ][0]

    assert q.endswith("ORDERBYsys_id")


def test_extract_resumes_when_asked(tmp_path: Path) -> None:
    out = tmp_path / "x.jsonl"
    state = tmp_path / "x.jsonl.state.json"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "3"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 3)}, status=200)
        code = main(
            [*CREDS, "extract", "incident", "--out", str(out), "--page-size", "10", "--resume"]
        )

    assert code == 0
    # A finished run leaves nothing to resume from.
    assert not state.exists()


def test_extract_refuses_to_overwrite_without_being_told(tmp_path: Path) -> None:
    """Silently truncating a finished 1.7 GB corpus would be an expensive
    surprise."""
    out = tmp_path / "x.jsonl"
    out.write_text('{"already": "here"}\n')
    code = main([*CREDS, "extract", "incident", "--out", str(out)])
    assert code != 0
    assert out.read_text() == '{"already": "here"}\n'


def test_extract_overwrites_when_told(tmp_path: Path) -> None:
    out = tmp_path / "x.jsonl"
    out.write_text("stale\n")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "2"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 2)}, status=200)
        code = main(
            [*CREDS, "extract", "incident", "--out", str(out), "--page-size", "10", "--overwrite"]
        )

    assert code == 0
    assert "stale" not in out.read_text()


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def test_missing_credentials_are_reported_not_crashed(tmp_path: Path, monkeypatch: Any) -> None:
    for var in ("SNOW_INSTANCE", "SNOW_USER", "SNOW_PASS"):
        monkeypatch.delenv(var, raising=False)
    code = main(["extract", "incident", "--out", str(tmp_path / "x.jsonl")])
    assert code != 0


def test_credentials_come_from_the_environment(tmp_path: Path, monkeypatch: Any) -> None:
    """So a password never has to appear in a shell history or a process list."""
    monkeypatch.setenv("SNOW_INSTANCE", BASE_URL)
    monkeypatch.setenv("SNOW_USER", "admin")
    monkeypatch.setenv("SNOW_PASS", "secret")
    out = tmp_path / "x.jsonl"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "1"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 1)}, status=200)
        code = main(["extract", "incident", "--out", str(out), "--page-size", "10"])

    assert code == 0


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------


def test_count_prints_the_number(tmp_path: Path, capsys: Any) -> None:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "457247"}}},
            status=200,
        )
        code = main([*CREDS, "count", "incident"])

    assert code == 0
    assert "457247" in capsys.readouterr().out


def test_resume_on_a_finished_output_is_refused(tmp_path: Path) -> None:
    """A completed run deletes its own state file, so an output with no state
    beside it is finished. Appending to it would write the table in twice, and
    the file would look plausible while holding every record doubled."""
    out = tmp_path / "x.jsonl"
    out.write_text('{"sys_id": "a"}\n')
    code = main([*CREDS, "extract", "incident", "--out", str(out), "--resume"])
    assert code != 0
    assert out.read_text() == '{"sys_id": "a"}\n'


def test_resume_with_overwrite_starts_afresh(tmp_path: Path) -> None:
    out = tmp_path / "x.jsonl"
    out.write_text("stale\n")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "2"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 2)}, status=200)
        code = main(
            [
                *CREDS,
                "extract",
                "incident",
                "--out",
                str(out),
                "--page-size",
                "10",
                "--resume",
                "--overwrite",
            ]
        )

    assert code == 0
    assert "stale" not in out.read_text()
    assert len(out.read_text().splitlines()) == 2


def test_extract_accepts_a_limit(tmp_path: Path) -> None:
    """Sampling a big table without pulling all of it."""
    out = tmp_path / "sample.jsonl"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "5000"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 25)}, status=200)
        code = main([*CREDS, "extract", "incident", "--out", str(out), "--limit", "25"])

    assert code == 0
    assert len(out.read_text().splitlines()) == 25


def test_a_limited_extract_does_not_claim_to_be_verified(tmp_path: Path) -> None:
    """A capped sweep cannot be checked against the table count, so it must not
    exit non-zero for being short, nor report itself as complete."""
    out = tmp_path / "sample.jsonl"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "5000"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 10)}, status=200)
        code = main([*CREDS, "extract", "incident", "--out", str(out), "--limit", "10"])

    assert code == 0


def test_extract_writes_csv_when_asked(tmp_path: Path) -> None:
    out = tmp_path / "x.csv"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "3"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 3)}, status=200)
        rsps.add(responses.GET, INCIDENT, json={"result": []}, status=200)
        code = main([*CREDS, "extract", "incident", "--out", str(out), "--page-size", "10"])

    assert code == 0
    import csv as _csv

    rows = list(_csv.DictReader(out.open()))
    assert len(rows) == 3
    assert rows[0]["number"] == "INC0000000"


def test_the_format_follows_the_extension(tmp_path: Path) -> None:
    """Writing JSONL into a file called .csv is found much later, in a
    spreadsheet that will not open."""
    from snowloader.cli import _format_for

    assert _format_for(Path("a.csv")) == "csv"
    assert _format_for(Path("a.xlsx")) == "xlsx"
    assert _format_for(Path("a.jsonl")) == "jsonl"
    assert _format_for(Path("a")) == "jsonl"


def test_an_explicit_format_beats_the_extension(tmp_path: Path) -> None:
    out = tmp_path / "misnamed.txt"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{STATS_API}/incident",
            json={"result": {"stats": {"count": "2"}}},
            status=200,
        )
        rsps.add(responses.GET, INCIDENT, json={"result": _rows(0, 2)}, status=200)
        rsps.add(responses.GET, INCIDENT, json={"result": []}, status=200)
        code = main(
            [
                *CREDS,
                "extract",
                "incident",
                "--out",
                str(out),
                "--format",
                "csv",
                "--page-size",
                "10",
            ]
        )

    assert code == 0
    assert out.read_text().startswith("sys_id,number") or "number" in out.read_text().split("\n")[0]
