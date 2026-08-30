#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Send a signal into a running dashboard from another window -- typically from
# an agent session working on the same repository.
#
#   dash-send.sh note "running the gate on the worker's output"
#   dash-send.sh ask "refactor first?" "do it now" "finish B-05" "later"
#   dash-send.sh fold library commits
#   dash-send.sh open round
#   dash-send.sh clear
#
# The whole channel is two files in the dashboard's cache directory: this
# writes session.env, and the dashboard appends what the reader does to
# events.jsonl, which the sender tails. No daemon, no port, and neither file is
# tracked, so a signal never turns into a commit.
#
# The dashboard applies each send once, keyed on this file's mtime, so a fold
# does not snap shut again under the reader's fingers on the next tick.
# ---------------------------------------------------------------------------
set -uo pipefail

ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || ROOT=$(cd "$(dirname "$0")/.." && pwd)
CACHE=${DASH_CACHE_DIR:-"$ROOT/.dashboard-cache"}
mkdir -p "$CACHE" || exit 1
FILE="$CACHE/session.env"
TMP="$FILE.$$"

usage() { sed -n '4,10p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

# Single-quoted so the dashboard can source the file; the only thing that can
# break out of single quotes is a single quote, so that is the only escape.
esc() { printf '%s' "${1-}" | sed "s/'/'\\\\''/g"; }

cmd=${1:-}
[ -n "$cmd" ] || usage
shift

# Each field is carried over from the previous send unless this one replaces
# it, so asking a question does not silently wipe the note that explains why it
# is being asked. `clear` is the only thing that empties the file.
NOTE=""; QUESTION=""; OPTIONS=""; FOLD=""; OPEN=""
if [ -f "$FILE" ] && [ "$cmd" != clear ]; then
    # shellcheck disable=SC1090
    . "$FILE" 2>/dev/null
fi
# A fold is an instruction, not a state: carrying it forward would refold the
# section on the next unrelated send.
FOLD=""; OPEN=""

case $cmd in
    note)  NOTE=${1:-} ;;
    ask)
        QUESTION=${1:-}; shift 2>/dev/null || true
        [ -n "$QUESTION" ] && [ $# -gt 0 ] || usage
        OPTIONS=$(IFS='|'; echo "$*") ;;
    fold)  [ $# -gt 0 ] || usage; FOLD=$* ;;
    open)  [ $# -gt 0 ] || usage; OPEN=$* ;;
    clear) NOTE=""; QUESTION=""; OPTIONS="" ;;
    *)     usage ;;
esac

{
    printf "NOTE='%s'\n" "$(esc "$NOTE")"
    printf "QUESTION='%s'\n" "$(esc "$QUESTION")"
    printf "OPTIONS='%s'\n" "$(esc "$OPTIONS")"
    printf "FOLD='%s'\n" "$(esc "$FOLD")"
    printf "OPEN='%s'\n" "$(esc "$OPEN")"
} > "$TMP"

# Written whole, then moved into place: a tick landing mid-write must never
# read half a command, and the move is what the dashboard keys off.
mv -f "$TMP" "$FILE"
printf 'sent: %s %s\n' "$cmd" "$*"
