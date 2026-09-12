#!/usr/bin/env bash
# Build the production application image and push it to Artifact Registry.
# The 4 GB VM only pulls the result; the build happens on this machine.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh"

for cmd in gcloud docker; do
  command -v "${cmd}" >/dev/null 2>&1 || { echo "Missing required command: ${cmd}" >&2; exit 1; }
done

if declare -F ui_log >/dev/null 2>&1; then
  ui_log "Authenticating Docker to ${REGION}-docker.pkg.dev..."
else
  echo "[$(date +'%F %T')] Authenticating Docker to ${REGION}-docker.pkg.dev..."
fi
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

if declare -F ui_log >/dev/null 2>&1; then
  ui_log "Building and pushing ${DOCREVIEW_IMAGE} (linux/amd64)..."
else
  echo "[$(date +'%F %T')] Building and pushing ${DOCREVIEW_IMAGE} (linux/amd64)..."
fi
docker buildx build \
  --platform linux/amd64 \
  --output "type=image,compression=zstd,force-compression=true,push=true" \
  --tag "${DOCREVIEW_IMAGE}" \
  --file "${REPO_ROOT}/docker/Dockerfile" \
  "${REPO_ROOT}"

if declare -F ui_ok >/dev/null 2>&1; then
  ui_ok "pushed ${DOCREVIEW_IMAGE}"
else
  printf '  ✓ pushed %s\n' "${DOCREVIEW_IMAGE}"
fi
