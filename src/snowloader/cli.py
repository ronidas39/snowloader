"""Command line interface for extracting a ServiceNow table.

The library has had correct ordering, verification, resume and a partial
failure policy for a while. This exists because people were still assembling
those by hand, and getting it wrong quietly. Of the extraction scripts written
against this package before it existed, two built their own encoded query with
a non-unique sort, so they never picked up the ordering fix at all, and one
validated itself by comparing a line count against the record count, which is
the single check that cannot detect the loss that causes.

So the defaults here are the careful ones. Ordering always ends on a unique
key and cannot be talked out of it. Verification is on unless it is switched
off on purpose. An incomplete sweep exits non-zero, because a pipeline
downstream has no other way to find out.

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from snowloader import __version__
from snowloader.checkpoints import FileCheckpoint
from snowloader.connection import SnowConnection
from snowloader.exceptions import SnowConnectionError, SweepIncompleteError
from snowloader.export import FORMATS, write_records

logger = logging.getLogger("snowloader")

_EPILOG = """\
examples:
  snowloader count incident --query "active=true"

  snowloader extract incident --out incidents.jsonl \\
      --query "stateIN6,7^close_notesISNOTEMPTY" \\
      --fields sys_id,number,close_notes --display-value all

  snowloader extract cmdb_ci --out cmdb.jsonl --resume --workers 16

credentials:
  Read from SNOW_INSTANCE, SNOW_USER and SNOW_PASS when the matching option is
  not given, so a password need not appear in a shell history or a process
  list.
"""


def _format_for(path: Path) -> str:
    """Guess the output format from the file name.

    Writing JSONL into something called ``.csv`` because no flag was passed
    is the kind of surprise that is found much later, in a spreadsheet that
    will not open.
    """
    suffix = path.suffix.lower().lstrip(".")
    if suffix in ("xlsx", "xls"):
        return "xlsx"
    if suffix == "csv":
        return "csv"
    return "jsonl"


def build_parser() -> argparse.ArgumentParser:
    """Assemble the argument parser.

    Returns:
        The parser, with the ``extract`` and ``count`` subcommands on it.
    """
    parser = argparse.ArgumentParser(
        prog="snowloader",
        description="Extract a ServiceNow table without quietly losing rows.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"snowloader {__version__}")
    parser.add_argument("--instance", help="Instance URL. Defaults to SNOW_INSTANCE.")
    parser.add_argument("--user", help="Username. Defaults to SNOW_USER.")
    parser.add_argument("--password", help="Password. Defaults to SNOW_PASS.")
    parser.add_argument("--quiet", action="store_true", help="Only report warnings and errors.")

    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("table", help="Table to read, for example incident or cmdb_ci.")
    common.add_argument("--query", default=None, help="Encoded query, without the ordering.")

    count = sub.add_parser(
        "count", parents=[common], help="Print how many records match, and stop."
    )
    count.set_defaults(func=_cmd_count)

    extract = sub.add_parser(
        "extract", parents=[common], help="Write matching records to a JSONL file."
    )
    extract.add_argument("--out", required=True, help="Output path.")
    extract.add_argument(
        "--format",
        dest="fmt",
        choices=FORMATS,
        default=None,
        help="Output format. Inferred from the file extension when not given.",
    )
    extract.add_argument(
        "--fields",
        type=lambda s: [f.strip() for f in s.split(",") if f.strip()],
        default=None,
        help="Comma separated field list. Every field by default.",
    )
    extract.add_argument(
        "--display-value",
        choices=("true", "false", "all"),
        default="true",
        help="sysparm_display_value. Use all to keep both halves of every field.",
    )
    extract.add_argument("--page-size", type=int, default=100, help="Records per request.")
    extract.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after this many records. Useful for sampling a large table.",
    )
    extract.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Fetch pages in parallel with this many threads. Sequential by default.",
    )
    extract.add_argument(
        "--resume",
        action="store_true",
        help="Continue a previous run, and record progress so this one can be continued.",
    )
    extract.add_argument(
        "--no-verify",
        dest="verify",
        action="store_false",
        help="Skip the completeness check. On by default, and worth keeping.",
    )
    extract.add_argument(
        "--skip-failed-pages",
        action="store_true",
        help="Carry on past a page that cannot be fetched, and report the gap at the end.",
    )
    extract.add_argument(
        "--overwrite", action="store_true", help="Replace the output file if it exists."
    )
    extract.set_defaults(verify=True, func=_cmd_extract)

    common_since = argparse.ArgumentParser(add_help=False)
    common_since.add_argument(
        "--since",
        required=True,
        help="Cutoff as YYYY-MM-DD or 'YYYY-MM-DD HH:MM:SS'. Read as UTC.",
    )

    deleted = sub.add_parser(
        "deleted",
        parents=[common, common_since],
        help="List records deleted from a table since a point in time.",
    )
    deleted.add_argument("--out", default=None, help="Write to a file instead of stdout.")
    deleted.add_argument(
        "--no-subclasses",
        dest="subclasses",
        action="store_false",
        help="Do not resolve descendant tables. Deletions are audited against "
        "the real class, so a base table finds none without this.",
    )
    deleted.set_defaults(subclasses=True, func=_cmd_deleted)

    recon = sub.add_parser(
        "reconcile",
        parents=[common, common_since],
        help="Report what was added, updated and deleted since a point in time.",
    )
    recon.add_argument("--out", default=None, help="Write the report as JSON to a file.")
    recon.set_defaults(func=_cmd_reconcile)
    return parser


def _connect(args: argparse.Namespace, **overrides: Any) -> SnowConnection:
    """Build a connection from the arguments and the environment.

    Raises:
        SnowConnectionError: If any credential is missing.
    """
    instance = args.instance or os.environ.get("SNOW_INSTANCE", "")
    user = args.user or os.environ.get("SNOW_USER", "")
    password = args.password or os.environ.get("SNOW_PASS", "")
    missing = [
        name
        for name, value in (
            ("--instance or SNOW_INSTANCE", instance),
            ("--user or SNOW_USER", user),
            ("--password or SNOW_PASS", password),
        )
        if not value
    ]
    if missing:
        raise SnowConnectionError(
            "Missing credentials: " + ", ".join(missing),
            detail="Pass them as options, or set the environment variables.",
        )
    return SnowConnection(instance_url=instance, username=user, password=password, **overrides)


def _cmd_count(args: argparse.Namespace) -> int:
    """Print the number of matching records."""
    with _connect(args) as conn:
        print(conn.get_count(args.table, query=args.query))
    return 0


def _parse_since(text: str) -> datetime:
    """Read a cutoff from the command line, as UTC."""
    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, shape).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise SnowConnectionError(
        f"Could not read '{text}' as a date.",
        detail="Use YYYY-MM-DD or 'YYYY-MM-DD HH:MM:SS'.",
    )


def _cmd_deleted(args: argparse.Namespace) -> int:
    """List what was deleted, which no delta sync can tell you."""
    since = _parse_since(args.since)
    with _connect(args) as conn:
        horizon = conn.get_deletion_horizon()
        if horizon is not None and since < horizon:
            logger.warning(
                "The audit only reaches back to %s, so deletions before that "
                "are gone rather than absent.",
                horizon.strftime("%Y-%m-%d %H:%M:%S"),
            )
        rows = list(
            conn.get_deleted_records(args.table, since=since, include_subclasses=args.subclasses)
        )
    if args.out:
        written = write_records(rows, Path(args.out), fmt=_format_for(Path(args.out)))
        logger.info("Wrote %d deletions to %s", written, args.out)
    else:
        for row in rows:
            print(f"{row['sys_id']}\t{row['table']}\t{row['deleted_at']}")
    return 0


def _cmd_reconcile(args: argparse.Namespace) -> int:
    """Added, updated and deleted, which is what a sync actually needs."""
    since = _parse_since(args.since)
    with _connect(args) as conn:
        report = conn.reconcile(args.table, since=since, query=args.query)

    logger.info("%s", report)
    if not report.is_complete:
        logger.warning(
            "Deletions before %s are past the audit horizon, so the deleted "
            "list is a floor rather than the whole truth.",
            report.horizon.strftime("%Y-%m-%d %H:%M:%S") if report.horizon else "?",
        )
    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "table": report.table,
                    "since": report.since.strftime("%Y-%m-%d %H:%M:%S"),
                    "complete": report.is_complete,
                    "added": report.added,
                    "updated": report.updated,
                    "deleted": report.deleted,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        logger.info("Wrote the report to %s", args.out)
    else:
        print(
            f"added={len(report.added)} updated={len(report.updated)} "
            f"deleted={len(report.deleted)} complete={report.is_complete}"
        )
    return 0 if report.is_complete else 1


def _cmd_extract(args: argparse.Namespace) -> int:
    """Sweep a table into a JSONL file."""
    out = Path(args.out)
    if out.exists() and not args.overwrite and not args.resume:
        logger.error(
            "%s already exists. Pass --overwrite to replace it, or --resume to continue it.",
            out,
        )
        return 2

    state_path = out.with_suffix(out.suffix + ".state.json")
    if args.resume and out.exists() and not state_path.exists() and not args.overwrite:
        # A finished run deletes its own state. So an output file with no
        # state beside it is a completed extraction, and appending to it
        # would write the whole table in a second time.
        logger.error(
            "%s exists and there is no %s beside it, so the previous run finished.",
            out,
            state_path.name,
        )
        logger.error(
            "Resuming would append the whole table again. Pass --overwrite to "
            "start it afresh, or move the file aside."
        )
        return 2

    if args.limit is not None and args.limit < 0:
        logger.error("--limit must not be negative.")
        return 2

    verify = args.verify
    if verify and args.limit is not None:
        # Verification compares what came back against the table count, so a
        # deliberately capped run would always look short.
        logger.info("Not verifying, because --limit caps the sweep on purpose.")
        verify = False

    checkpoint = FileCheckpoint(state_path) if args.resume else None
    threaded = args.workers > 0

    with _connect(args, page_size=args.page_size, display_value=args.display_value) as conn:
        total = conn.get_count(args.table, query=args.query)
        logger.info("%s: %d records match", args.table, total)

        shared: dict[str, Any] = {
            "table": args.table,
            "query": args.query,
            "fields": args.fields,
            "verify": verify,
            "on_error": "skip" if args.skip_failed_pages else "raise",
        }
        if threaded:
            if args.limit is not None:
                logger.info("Fetching sequentially, because --limit caps the run.")
                stream = conn.get_records(
                    keyset=bool(checkpoint), checkpoint=checkpoint, limit=args.limit, **shared
                )
            else:
                stream = conn.concurrent_get_records(
                    max_workers=args.workers, checkpoint=checkpoint, **shared
                )
        else:
            # Keyset is what makes a sequential run resumable, and it costs
            # nothing when it is not.
            stream = conn.get_records(
                keyset=bool(checkpoint), checkpoint=checkpoint, limit=args.limit, **shared
            )

        append = bool(args.resume and out.exists() and not args.overwrite)
        fmt = args.fmt or _format_for(out)
        written = 0

        def counted() -> Any:
            nonlocal written
            for record in stream:
                written += 1
                if written % 10000 == 0:
                    logger.info("  %d of %d written", written, total)
                yield record

        try:
            written = write_records(counted(), out, fmt=fmt, append=append)
        except SweepIncompleteError as exc:
            logger.error("Sweep did not return every record: %s", exc.report)
            logger.error(
                "Wrote %d records to %s. Do not treat this file as complete.", written, out
            )
            return 1

    logger.info("Wrote %d records to %s", written, out)
    if args.limit is not None:
        logger.info("Capped at %d by --limit, so this is a sample not a full extract.", args.limit)
    elif verify:
        logger.info("Verified: every record present exactly once.")
    else:
        logger.warning(
            "Completeness was not checked, because --no-verify was passed. "
            "A count matching the API does not by itself mean nothing was lost."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments to parse. ``sys.argv[1:]`` when omitted.

    Returns:
        Process exit status. 0 on success, 1 on an incomplete or failed
        extraction, 2 on a usage problem.
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    try:
        result: int = args.func(args)
        return result
    except SnowConnectionError as exc:
        logger.error("%s", exc)
        if exc.detail:
            logger.error("%s", exc.detail)
        return 2
    except KeyboardInterrupt:
        logger.warning("Interrupted. Re-run with --resume to continue from here.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
