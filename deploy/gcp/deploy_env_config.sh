#!/usr/bin/env bash
# Shared configuration for the deploy/gcp scripts. Source it; do not execute it.
#
# Values come from one dotenv file:
#   - <repo>/.env (or DOTENV_PATH): GCP project, zone, VM name, machine type,
#     the production OpenAI key and the deployment secrets (DEPLOY_POSTGRES_PASSWORD,
#     optional DOCREVIEW_IMAGE). This is the same file the local stack reads;
#     see .env.example for the deploy variables.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export SCRIPT_DIR REPO_ROOT

if [ -f "${SCRIPT_DIR}/lib/ui.sh" ]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/lib/ui.sh"
fi
if ! declare -F ui_heading >/dev/null 2>&1; then
  ui_heading() { printf '%s\n' "$*"; }
  ui_row() { printf '  %-24s  %s\n' "$1" "$2"; }
  ui_dim() { printf '%s\n' "$*"; }
  ui_log() { printf '[%s] %s\n' "$(date +'%F %T')" "$*"; }
  ui_rule() { printf '%s\n' "------------------------------------------------------------"; }
fi

DOTENV_PATH="${DOTENV_PATH:-${REPO_ROOT}/.env}"
if [[ ! -f "${DOTENV_PATH}" ]]; then
  echo "env file not found. Set DOTENV_PATH or create ${REPO_ROOT}/.env" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${DOTENV_PATH}"
set +a

# ===== Required config (from .env) =====
export PROJECT_ID="${DEPLOY_GCP_PROJECT:?DEPLOY_GCP_PROJECT is required}"
export OPENAI_API_KEY_PROD="${OPENAI_API_KEY_PROD:?OPENAI_API_KEY_PROD is required}"

# ===== Single production origin: e2-medium, 4 GB RAM =====
export ZONE="${DEPLOY_GCP_ZONE:-us-central1-a}"
export REGION="${ZONE%-*}"
export VM_NAME="${DEPLOY_VM_NAME:-docreview-rag-agent}"
export MACHINE_TYPE="${DEPLOY_MACHINE_TYPE:-e2-medium}"
export BOOT_DISK_SIZE="${DEPLOY_BOOT_DISK_SIZE:-30GB}"
export NETWORK_TAG="docreview-origin"
export ORIGIN_PORT="${DEPLOY_ORIGIN_PORT:-8000}"

# ===== Artifact Registry and the deployment service account =====
export AR_REPO="${DEPLOY_AR_REPO:-docreview}"
export ARTIFACT_REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"
export SA_NAME="${DEPLOY_SA_NAME:-docreview-deploy}"
export SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# ===== VM-side values (from .env; validated only where they are consumed) =====
# build_image.sh pushes this reference; deploy_backend.sh passes it to the VM.
export DOCREVIEW_IMAGE="${DOCREVIEW_IMAGE:-${ARTIFACT_REGISTRY}/docreview:latest}"
# DEPLOY_POSTGRES_PASSWORD is the production database password; the legacy
# POSTGRES_PASSWORD name is still accepted for an existing .env.
export POSTGRES_PASSWORD="${DEPLOY_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-}}"

_mask_len() {
  local s="${1:-}"
  if [[ -z "${s}" ]]; then
    echo "unset"
  else
    echo "set(len=${#s})"
  fi
}

if [ "${DEPLOY_SUMMARY:-1}" = "1" ]; then
  ui_heading "Deployment configuration"
  ui_row "Project" "${PROJECT_ID}"
  ui_row "Region" "${REGION} (${ZONE})"
  ui_row "VM" "${VM_NAME} (${MACHINE_TYPE})"
  ui_row "Disk" "${BOOT_DISK_SIZE} pd-standard · ephemeral IP"
  ui_row "Origin port" "${ORIGIN_PORT} (tag ${NETWORK_TAG}, Cloudflare IPv4 only)"
  ui_row "Registry" "${ARTIFACT_REGISTRY}"
  ui_row "Service account" "${SA_EMAIL}"
  ui_row "Image" "${DOCREVIEW_IMAGE}"
  ui_row "Secrets" "postgres_password=$(_mask_len "${POSTGRES_PASSWORD}"), openai_api_key_prod=$(_mask_len "${OPENAI_API_KEY_PROD}")"
  ui_rule
fi
