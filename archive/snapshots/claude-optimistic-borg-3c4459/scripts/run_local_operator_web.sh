#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export HOST_GID="${HOST_GID:-$(id -g)}"
local_host="${DOCREVIEW_LOCAL_HOST:-127.0.0.1}"
web_port="${DOCREVIEW_OPERATOR_WEB_PORT:-3000}"
operator_origin="http://${local_host}:${web_port}"
operator_port="${DOCREVIEW_OPERATOR_PORT:-18001}"
db_port="${DB_PORT:-5432}"
operator_token="$(
    "${repo_root}/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))'
)"

cleanup() {
    if [ -n "${web_pid:-}" ]; then
        kill -- "-${web_pid}" 2>/dev/null || true
        wait "${web_pid}" 2>/dev/null || true
    fi
    if [ -n "${operator_pid:-}" ]; then
        kill -- "-${operator_pid}" 2>/dev/null || true
        wait "${operator_pid}" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

cd "${repo_root}"
DOCREVIEW_OPERATOR_TOKEN="${operator_token}" \
DOCREVIEW_OPERATOR_ORIGIN="${operator_origin}" \
DOCREVIEW_OPERATOR_PORT="${operator_port}" \
    setsid .venv/bin/python -m app.operator &
operator_pid=$!

cd "${repo_root}/web"
NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://${local_host}:${APP_PORT:-8000}}" \
NEXT_PUBLIC_ADMIN_MODE=live \
NEXT_PUBLIC_OPERATOR_BASE_URL="http://${local_host}:${operator_port}" \
NEXT_PUBLIC_DB_ENDPOINT="${local_host}:${db_port}" \
NEXT_PUBLIC_OPERATOR_TOKEN="${operator_token}" \
    setsid npm run dev -- --port "${web_port}" &
web_pid=$!
wait "${web_pid}"
