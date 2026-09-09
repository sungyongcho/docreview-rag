#!/usr/bin/env bash
# Forward the app's loopback-only operator port (bypasses Caddy, so /admin/* works)
# to this machine. Pair with scripts/stack/operator_web.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh"

local_host="${DOCREVIEW_LOCAL_HOST:-127.0.0.1}"
local_port="${DOCREVIEW_TUNNEL_PORT:-18000}"
operator_port="${DOCREVIEW_OPERATOR_PORT:-8001}"

gcloud compute ssh "${VM_NAME}" \
  --project "${PROJECT_ID}" \
  --zone "${ZONE}" \
  -- -N -L "${local_host}:${local_port}:127.0.0.1:${operator_port}"
