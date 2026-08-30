#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Refresh the values the dashboard is not allowed to compute on a tick.
#
# The dashboard reads these from a cache directory and never blocks on them.
# Run this by hand after a change, or from a watch loop, or as a git hook.
#
#   dashboard-refresh.sh              run every declared job
#   dashboard-refresh.sh suite lint   run only the named jobs
#   dashboard-refresh.sh --list       show what is declared and how old it is
# ---------------------------------------------------------------------------
set -uo pipefail

ENGINE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || ROOT=$(cd "$ENGINE_DIR/.." && pwd)
cd "$ROOT" || exit 1

PANEL=""
for candidate in \
    "$ROOT/scripts/dashboard.panel.sh" \
    "$ROOT/.dashboard/panel.sh" \
    "$ENGINE_DIR/panel.sh"
do
    [ -f "$candidate" ] && { PANEL=$candidate; break; }
done
[ -n "$PANEL" ] || { printf 'dashboard-refresh: no panel file found\n' >&2; exit 1; }

SLOW_JOBS=()
declare -A SECTION_TITLES=()
SECTIONS=()
CACHE_DIR=".dashboard-cache"
JOB_TIMEOUT=${DASH_JOB_TIMEOUT:-900}
# The panel is sourced only for its declarations; it must not do work at load.
# shellcheck disable=SC1090
. "$PANEL"
case $CACHE_DIR in /*) ;; *) CACHE_DIR="$ROOT/$CACHE_DIR" ;; esac
mkdir -p "$CACHE_DIR"

if [ "${1:-}" = "--list" ]; then
    printf '%-16s %-10s %s\n' JOB AGE COMMAND
    for job in "${SLOW_JOBS[@]}"; do
        name=${job%%|*}; cmd=${job#*|}
        if [ -f "$CACHE_DIR/$name" ]; then
            age=$(( $(date +%s) - $(stat -c %Y "$CACHE_DIR/$name" 2>/dev/null || echo 0) ))
            age="${age}s"
        else
            age="never"
        fi
        printf '%-16s %-10s %s\n' "$name" "$age" "$cmd"
    done
    exit 0
fi

wanted=("$@")
ran=0
for job in "${SLOW_JOBS[@]}"; do
    name=${job%%|*}; cmd=${job#*|}
    if [ ${#wanted[@]} -gt 0 ]; then
        match=0
        for w in "${wanted[@]}"; do [ "$w" = "$name" ] && match=1; done
        [ "$match" = 1 ] || continue
    fi
    printf '→ %s\n' "$name"
    tmp="$CACHE_DIR/.$name.$$"
    if command -v timeout >/dev/null 2>&1; then
        timeout "$JOB_TIMEOUT" bash -c "$cmd" >"$tmp" 2>&1
    else
        bash -c "$cmd" >"$tmp" 2>&1
    fi
    # Written whole, then moved into place, so the dashboard never reads a
    # half-finished value on the tick that lands mid-run.
    mv -f "$tmp" "$CACHE_DIR/$name"
    sed 's/^/  /' "$CACHE_DIR/$name" | tail -3
    ran=$((ran + 1))
done

[ "$ran" -gt 0 ] || printf 'dashboard-refresh: nothing matched\n' >&2
