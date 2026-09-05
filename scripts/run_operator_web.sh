#!/usr/bin/env bash
set -euo pipefail

# The SSH management UI remains separate from local Compose and uses its tunnel.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}/web"

DOCREVIEW_API_UPSTREAM="http://${DOCREVIEW_LOCAL_HOST:-127.0.0.1}:${DOCREVIEW_TUNNEL_PORT:-18000}" \
NEXT_PUBLIC_API_BASE_URL="/docreview-rag-agent/api" \
NEXT_PUBLIC_ADMIN_MODE=live \
npm run dev -- --port "${APP_PORT:-8000}"
