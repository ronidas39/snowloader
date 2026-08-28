#!/bin/bash
# Validation for the context guard hook.
#
# The guard blocks a stop and interrupts the session, so a false positive is
# expensive and a silent failure is worse. Re-run this after any change to
# context_guard.py.
#
# It works against a frozen copy of the transcript. The live one grows between
# calls, which moved the measurement mid-test the first time these were written
# and produced a boundary failure that was the harness rather than the guard.
#
# Author: Roni Das
# Created: 2026-08-28

set -u
GUARD="$(dirname "$0")/context_guard.py"
PY=${GUARD_PYTHON:-python3}
# Derive the project key the same way the guard does, so neither file carries
# a local username.
REPO=$(cd "$(dirname "$0")/../.." && pwd)
KEY=$(printf '%s' "$REPO" | tr '/' '-')
PROJECT_DIR="$HOME/.claude/projects/$KEY"
LIVE=$(ls -t "$PROJECT_DIR"/*.jsonl 2>/dev/null | head -1)
if [ -z "${LIVE:-}" ]; then echo "no transcript found under $PROJECT_DIR"; exit 1; fi
FROZEN=$(mktemp /tmp/guard-transcript.XXXXXX.jsonl)
cp "$LIVE" "$FROZEN"

pass=0; fail=0
check() {  # name, expected_bytes_condition, actual
  if [ "$3" = "$2" ]; then printf '  ok      %s\n' "$1"; pass=$((pass+1))
  else printf '  FAILED  %s (expected %s, got %s)\n' "$1" "$2" "$3"; fail=$((fail+1)); fi
}

emit() {  # event, session, limit -> byte count of stdout
  printf '{"hook_event_name":"%s","session_id":"%s","transcript_path":"%s","source":"%s","trigger":"auto"}' \
    "$1" "$2" "$FROZEN" "${4:-none}" \
    | SNOWLOADER_CONTEXT_LIMIT="$3" $PY "$GUARD" | wc -c | tr -d ' '
}

USED=$($PY - "$FROZEN" <<'PY'
import json, sys
last = 0
for line in open(sys.argv[1], errors="replace"):
    if '"usage"' not in line:
        continue
    try:
        d = json.loads(line)
    except Exception:
        continue
    u = (d.get("message") or {}).get("usage")
    if isinstance(u, dict):
        t = (int(u.get("input_tokens") or 0)
             + int(u.get("cache_creation_input_tokens") or 0)
             + int(u.get("cache_read_input_tokens") or 0))
        if t > 0:
            last = t
print(last)
PY
)
echo "frozen transcript reports $USED tokens in use"

ABOVE=$($PY -c "print(int($USED/0.9499))")   # leaves 5.01 percent
BELOW=$($PY -c "print(int($USED/0.9501))")   # leaves 4.99 percent
HUGE=$($PY -c "print($USED*40)")             # leaves ~97 percent

echo "no false positives:"
check "silent with plenty of context"        0   "$(emit Stop v-plenty   "$HUGE")"
check "silent at 5.01 percent remaining"     0   "$(emit Stop v-above    "$ABOVE")"
check "silent on a normal session start"     0   "$(printf '{"hook_event_name":"SessionStart","session_id":"v-ss","source":"startup"}' | $PY "$GUARD" | wc -c | tr -d ' ')"
check "silent with no usage record"          0   "$(printf '{"hook_event_name":"Stop","session_id":"v-nu","transcript_path":"/dev/null"}' | $PY "$GUARD" | wc -c | tr -d ' ')"
check "silent with a missing transcript"     0   "$(printf '{"hook_event_name":"Stop","session_id":"v-mt","transcript_path":"/tmp/nope.jsonl"}' | $PY "$GUARD" | wc -c | tr -d ' ')"
check "silent on an unrelated event"         0   "$(emit PreToolUse v-evt "$BELOW")"

echo "fires when it should:"
[ "$(emit Stop v-below "$BELOW")" -gt 0 ] \
  && { echo "  ok      blocks the stop at 4.99 percent remaining"; pass=$((pass+1)); } \
  || { echo "  FAILED  did not block at 4.99 percent"; fail=$((fail+1)); }
check "fires only once per session"          0   "$(emit Stop v-below "$BELOW")"
check "PreCompact prints no decision"        0   "$(emit PreCompact v-pc "$BELOW")"
[ "$(printf '{"hook_event_name":"SessionStart","session_id":"v-sc","source":"compact"}' | $PY "$GUARD" | wc -c | tr -d ' ')" -gt 0 ] \
  && { echo "  ok      injects resume context after compaction"; pass=$((pass+1)); } \
  || { echo "  FAILED  no resume context after compaction"; fail=$((fail+1)); }

echo "output is well formed:"
if printf '{"hook_event_name":"Stop","session_id":"v-json","transcript_path":"%s"}' "$FROZEN" \
   | SNOWLOADER_CONTEXT_LIMIT="$BELOW" $PY "$GUARD" \
   | $PY -c "import json,sys; d=json.load(sys.stdin); assert d['decision']=='block'; assert '/handoff' in d['reason']" 2>/dev/null
then echo "  ok      Stop emits valid block JSON naming /handoff"; pass=$((pass+1))
else echo "  FAILED  Stop JSON is wrong"; fail=$((fail+1)); fi

rm -f "$FROZEN"
rm -f "$HOME"/.claude/run/snowloader-context-guard/v-*.fired
rm -f "$PROJECT_DIR"/memory/state/*auto-context-snapshot*
echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
