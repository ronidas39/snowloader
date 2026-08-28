#!/usr/bin/env python3
"""Fire the handoff workflow when the context window is nearly exhausted.

The problem this solves: auto-compaction summarises the conversation and
carries on, which keeps the session usable but writes nothing to the memory
directory. So a session that compacts loses the durable record even though the
conversation survives. This session compacted once on 2026-08-28 and no handoff
file was written for the work before it.

The sequence is handoff, then compact, then resume:

    Stop            measure the context. Under the threshold, block the stop
                    and instruct the model to run /handoff. The model writes
                    the real narrative record while it still has the context
                    to write it from.
    PreCompact      backstop. If compaction is about to happen and no handoff
                    ran this session, capture at least the mechanical state.
    SessionStart    after compaction, point the model at what was written so
                    work resumes instead of restarting.

On avoiding false positives, which is the whole design constraint:

    - It reads real token counts out of the transcript. It does not estimate
      from file size or message count.
    - It requires a usage record to exist. No record means no decision, not a
      guessed one.
    - The comparison is strict, against a threshold that defaults to 5 percent
      remaining.
    - It fires at most once per session, tracked by a sentinel keyed on the
      session id, so blocking a stop cannot loop.
    - Every decision it makes, including every decision not to fire, is
      appended to a log so the behaviour can be audited rather than trusted.

Environment overrides, both intended for testing rather than daily use:

    SNOWLOADER_CONTEXT_LIMIT      total context window in tokens
    SNOWLOADER_CONTEXT_THRESHOLD  fire below this fraction remaining, 0.05

Author: Roni Das
Created: 2026-08-28
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# claude-opus-5 in its 1M configuration. Overridable because the same hook
# would otherwise misjudge a session running a smaller window, and misjudging
# it high would fire early, which is the false positive being designed out.
DEFAULT_CONTEXT_LIMIT = 1_000_000
DEFAULT_THRESHOLD = 0.05

def _repo_root() -> Path:
    """Where the project lives.

    Claude Code sets CLAUDE_PROJECT_DIR for hooks. Falling back to the
    directory two levels up from this file keeps it working when it is run by
    hand, which is how the validation script drives it.
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


REPO = _repo_root()

# Claude Code names a project's memory directory after its path, with the
# separators replaced by hyphens. Deriving it rather than writing it out keeps
# this file portable, and keeps a local username out of a public repository.
_PROJECT_KEY = str(REPO).replace("/", "-")
MEMORY_DIR = Path.home() / ".claude/projects" / _PROJECT_KEY / "memory"
STATE_DIR = MEMORY_DIR / "state"
RUNTIME_DIR = Path.home() / ".claude/run/snowloader-context-guard"
LOG_PATH = RUNTIME_DIR / "decisions.log"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message: str) -> None:
    """Append one decision line. Never raises; a broken log must not break a turn."""
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as handle:
            handle.write(f"{_now()} {message}\n")
    except OSError:
        pass


def context_limit() -> int:
    raw = os.environ.get("SNOWLOADER_CONTEXT_LIMIT")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_CONTEXT_LIMIT


def threshold() -> float:
    raw = os.environ.get("SNOWLOADER_CONTEXT_THRESHOLD")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_THRESHOLD


def tokens_in_use(transcript: Path) -> int | None:
    """Read the most recent real context size out of the transcript.

    The context an assistant turn actually carried is the sum of the tokens it
    read fresh, the tokens it wrote to cache and the tokens it read from cache.
    Output tokens are not part of it, because they are not resident context.

    Returns:
        Token count, or None when the transcript holds no usage record, in
        which case the caller must not guess.
    """
    if not transcript.is_file():
        return None

    latest: int | None = None
    try:
        with transcript.open(errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or '"usage"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    continue
                usage = (record.get("message") or {}).get("usage")
                if not isinstance(usage, dict):
                    continue
                total = (
                    int(usage.get("input_tokens") or 0)
                    + int(usage.get("cache_creation_input_tokens") or 0)
                    + int(usage.get("cache_read_input_tokens") or 0)
                )
                if total > 0:
                    latest = total
    except OSError:
        return None
    return latest


def fraction_remaining(transcript: Path) -> tuple[float, int] | None:
    used = tokens_in_use(transcript)
    if used is None:
        return None
    limit = context_limit()
    if limit <= 0:
        return None
    return max(0.0, (limit - used) / limit), used


def sentinel_for(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "unknown"
    return RUNTIME_DIR / f"{safe}.fired"


def capture_state(session_id: str) -> Path | None:
    """Write the mechanical facts a handoff needs, without the model.

    A shell command cannot write the part of a handoff that matters most,
    which is why a decision was taken. It can write the part that is pure fact
    and is exactly what goes stale: where the repo stands against what is
    published.
    """
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    def run(*args: str) -> str:
        try:
            done = subprocess.run(
                args, cwd=REPO, capture_output=True, text=True, timeout=30
            )
            return done.stdout.strip() or "(no output)"
        except (OSError, subprocess.SubprocessError):
            return "(could not be read)"

    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out = STATE_DIR / f"{stamp}-auto-context-snapshot.txt"
    body = [
        "Automatic snapshot, written because the context window fell below the",
        "threshold. Mechanical facts only. The narrative belongs in the session",
        "handoff written by the model.",
        "",
        f"Captured: {_now()}",
        f"Session:  {session_id}",
        "",
        "== git log -5 ==",
        run("git", "log", "--oneline", "-5"),
        "",
        "== git status --short ==",
        run("git", "status", "--short"),
        "",
        "== version in pyproject.toml ==",
        run("grep", "-m1", "^version", "pyproject.toml"),
        "",
        "== unpushed commits ==",
        run("git", "log", "--oneline", "origin/main..HEAD"),
    ]
    try:
        out.write_text("\n".join(body) + "\n")
    except OSError:
        return None
    return out


HANDOFF_INSTRUCTION = """\
The context window has fallen below {pct:.1f} percent remaining ({used:,} of \
{limit:,} tokens used), so compaction is imminent and the durable record has \
to be written now, while the detail is still in context.

Run the /handoff command and complete it fully before finishing this turn. \
A mechanical state snapshot has already been written to {snapshot}; it holds \
git state and versions only, so the handoff still needs the part a script \
cannot produce: what was done, what was decided and why, what was validated \
against a live instance as opposed to reasoned about, and what the next \
session should do first.

Do not summarise this instruction back. Just run it. This fires once per \
session, so nothing will interrupt again.\
"""

RESUME_CONTEXT = """\
This session resumed after automatic compaction. Before the compaction a \
handoff was written to persistent memory, because the context window had \
fallen below the configured threshold.

Read these before continuing, newest first, and pick the work up from them \
rather than reconstructing it:

  {memory}/MEMORY.md
  {memory}/project_status.md
  the newest {memory}/session_handoff_*.md
  the newest {state}/*-auto-context-snapshot.txt

The snapshot holds the git and version state at the moment of compaction, so \
it is the fastest way to see whether the working tree still matches what the \
handoff describes.\
"""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, TypeError):
        return 0

    event = payload.get("hook_event_name", "")
    session_id = str(payload.get("session_id", "unknown"))
    transcript = Path(payload.get("transcript_path", "") or "")

    # After compaction: point the model at what was captured, so it resumes.
    if event == "SessionStart":
        if payload.get("source") != "compact":
            return 0
        log(f"SessionStart source=compact session={session_id} injecting resume context")
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": RESUME_CONTEXT.format(
                            memory=MEMORY_DIR, state=STATE_DIR
                        ),
                    }
                }
            )
        )
        return 0

    if event not in ("Stop", "PreCompact"):
        return 0

    measured = fraction_remaining(transcript)
    if measured is None:
        # No usage record means no measurement. Do nothing rather than guess,
        # because a guess here is exactly the false positive being avoided.
        log(f"{event} session={session_id} no usage record, taking no action")
        return 0

    remaining, used = measured
    limit = context_limit()
    cutoff = threshold()

    if remaining >= cutoff:
        log(
            f"{event} session={session_id} remaining={remaining:.4f} "
            f"({used:,}/{limit:,}) above cutoff={cutoff:.4f}, no action"
        )
        return 0

    sentinel = sentinel_for(session_id)
    if sentinel.exists():
        log(
            f"{event} session={session_id} remaining={remaining:.4f} "
            f"below cutoff but already fired, no action"
        )
        return 0

    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        sentinel.write_text(f"{_now()} {event} remaining={remaining:.4f}\n")
    except OSError:
        pass

    snapshot = capture_state(session_id)
    log(
        f"{event} session={session_id} remaining={remaining:.4f} "
        f"({used:,}/{limit:,}) BELOW cutoff={cutoff:.4f}, firing. "
        f"snapshot={snapshot}"
    )

    if event == "Stop":
        # Blocking the stop is what puts the instruction in front of the model.
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": HANDOFF_INSTRUCTION.format(
                        pct=cutoff * 100,
                        used=used,
                        limit=limit,
                        snapshot=snapshot or "(snapshot could not be written)",
                    ),
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
