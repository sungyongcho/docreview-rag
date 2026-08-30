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

case $cmd in
    note)  printf "NOTE='%s'\n" "$(esc "${1:-}")" > "$TMP" ;;
    ask)
        q=${1:-}; shift 2>/dev/null || true
        [ -n "$q" ] && [ $# -gt 0 ] || usage
        { printf "QUESTION='%s'\n" "$(esc "$q")"
          printf "OPTIONS='%s'\n" "$(esc "$(IFS='|'; echo "$*")")"; } > "$TMP" ;;
    fold)  [ $# -gt 0 ] || usage; printf "FOLD='%s'\n" "$(esc "$*")" > "$TMP" ;;
    open)  [ $# -gt 0 ] || usage; printf "OPEN='%s'\n" "$(esc "$*")" > "$TMP" ;;
    clear) : > "$TMP" ;;
    *)     usage ;;
esac

# Written whole, then moved into place: a tick landing mid-write must never
# read half a command, and the move is what the dashboard keys off.
mv -f "$TMP" "$FILE"
printf 'sent: %s %s\n' "$cmd" "$*"
