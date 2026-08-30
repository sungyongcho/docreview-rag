#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Shared cache-path resolution. Sourced by dashboard.sh, dash-send.sh and
# dashboard-refresh.sh so every script lands on the same cache directory no
# matter which worktree it is started from -- otherwise the two-way channel
# (session.env in, events.jsonl out) silently splits per worktree.
#
# Provides:
#   MAIN_ROOT           primary worktree root (linked worktrees resolve to it)
#   CACHE_HOME          $DASH_CACHE_DIR if set, else $MAIN_ROOT/.dashboard-cache
#   resolve_cache_home  map a configured CACHE_DIR to an absolute cache home
#   _ctx_slug           slug used for per-worktree cache subdirectories
#   ctx_cache_dir       $CACHE_HOME/ctx-<slug>
#   active_cache_dir    the directory a running dashboard currently reads
# ---------------------------------------------------------------------------

# The primary worktree owns the cache. --git-common-dir names the shared .git
# directory, whose parent is the primary root even when asked from a linked
# worktree; outside a repository fall back to this file's parent directory.
_dash_common=$(git rev-parse --git-common-dir 2>/dev/null)
if [ -n "$_dash_common" ] && [ -d "$_dash_common" ]; then
    _dash_common=$(cd "$_dash_common" && pwd)
    MAIN_ROOT=${_dash_common%/*}
else
    MAIN_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) \
        || MAIN_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fi
unset _dash_common

# DASH_CACHE_DIR (already honoured by dash-send.sh) overrides everything; a
# relative configured path is anchored at MAIN_ROOT, never at the caller's
# own worktree.
resolve_cache_home() {
    if [ -n "${DASH_CACHE_DIR:-}" ]; then
        printf '%s' "$DASH_CACHE_DIR"
    else
        case $1 in
            /*) printf '%s' "$1" ;;
            *)  printf '%s' "$MAIN_ROOT/$1" ;;
        esac
    fi
}
CACHE_HOME=$(resolve_cache_home ".dashboard-cache")

_ctx_slug() { printf '%s' "$1" | tr -c 'A-Za-z0-9' '_'; }
ctx_cache_dir() { printf '%s/ctx-%s' "$CACHE_HOME" "$(_ctx_slug "$1")"; }

_worktree_count() {
    git -C "$MAIN_ROOT" worktree list --porcelain 2>/dev/null | grep -c '^worktree '
}

# Where the running dashboard reads right now. On more than one worktree the
# dashboard works out of a per-context subdirectory and records its choice in
# $CACHE_HOME/.ctx (see ctx_set in dashboard.sh); mirror exactly that. On a
# single worktree, or before any dashboard has recorded a context, it is
# CACHE_HOME itself.
active_cache_dir() {
    local ctx=""
    [ -f "$CACHE_HOME/.ctx" ] && ctx=$(cat "$CACHE_HOME/.ctx" 2>/dev/null)
    if [ -n "$ctx" ] && [ "$(_worktree_count)" -gt 1 ]; then
        ctx_cache_dir "$ctx"
    else
        printf '%s' "$CACHE_HOME"
    fi
}
