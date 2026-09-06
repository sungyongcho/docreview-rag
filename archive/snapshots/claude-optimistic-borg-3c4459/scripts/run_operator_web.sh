#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}/web"

NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://${DOCREVIEW_LOCAL_HOST:-127.0.0.1}:${DOCREVIEW_TUNNEL_PORT:-18000}}" \
NEXT_PUBLIC_ADMIN_MODE=live \
npm run dev -- --port "${DOCREVIEW_OPERATOR_WEB_PORT:-3000}"
