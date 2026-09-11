#!/usr/bin/env bash
# Shared configuration for the deploy/gcp scripts. Source it; do not execute it.
#
# Values come from two dotenv files:
#   - <repo>/.env (or DOTENV_PATH): GCP project, zone, VM name, machine type and the
#     production OpenAI key. This is the same file the local stack reads.
#   - deploy/gcp/backend.env (or BACKEND_ENV_PATH): the VM-side values that
#     deploy_backend.sh copies to /opt/docreview/.env. Optional here; required by
#     deploy_backend.sh. Values in backend.env win over .env.
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

BACKEND_ENV_PATH="${BACKEND_ENV_PATH:-${SCRIPT_DIR}/backend.env}"
export BACKEND_ENV_PATH

set -a
# shellcheck disable=SC1090
source "${DOTENV_PATH}"
if [[ -f "${BACKEND_ENV_PATH}" ]]; then
  # shellcheck disable=SC1090
  source "${BACKEND_ENV_PATH}"
fi
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

# ===== VM-side config (from backend.env; validated only where it is consumed) =====
export DOCREVIEW_IMAGE="${DOCREVIEW_IMAGE:-}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"

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
  ui_row "Image" "${DOCREVIEW_IMAGE:-unset}"
  ui_row "Backend env" "${BACKEND_ENV_PATH} ($([[ -f "${BACKEND_ENV_PATH}" ]] && echo present || echo missing))"
  ui_row "Secrets" "postgres_password=$(_mask_len "${POSTGRES_PASSWORD}"), openai_api_key_prod=$(_mask_len "${OPENAI_API_KEY_PROD}")"
  ui_rule
fi
