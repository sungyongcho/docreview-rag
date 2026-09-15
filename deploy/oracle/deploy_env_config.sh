#!/usr/bin/env bash
# Shared configuration for the deploy/oracle scripts. Source it; do not execute it.
#
# Single Oracle Cloud Always Free A1 instance (2 OCPU / 12 GB, aarch64) shared with
# the gomoku minimax engine. The application image is built on the instance itself,
# so there is no registry and no cross-compilation. Values come from the repo .env
# (or DOTENV_PATH); see .env.example.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
GCP_DIR="${REPO_ROOT}/deploy/gcp"
export SCRIPT_DIR REPO_ROOT GCP_DIR

if [ -f "${GCP_DIR}/lib/ui.sh" ]; then
  # shellcheck disable=SC1091
  source "${GCP_DIR}/lib/ui.sh"
fi
if ! declare -F ui_heading >/dev/null 2>&1; then
  ui_heading() { printf '%s\n' "$*"; }
  ui_row() { printf '  %-24s  %s\n' "$1" "$2"; }
  ui_dim() { printf '%s\n' "$*"; }
  ui_log() { printf '[%s] %s\n' "$(date +'%F %T')" "$*"; }
  ui_ok() { printf '  ✓ %s\n' "$*"; }
  ui_warn() { printf '  ! %s\n' "$*" >&2; }
  ui_fail() { printf '  ✗ %s\n' "$*" >&2; }
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
export ORACLE_HOST="${DEPLOY_ORACLE_HOST:?DEPLOY_ORACLE_HOST is required (public IPv4 of the A1 instance)}"
export OPENAI_API_KEY_PROD="${OPENAI_API_KEY_PROD:?OPENAI_API_KEY_PROD is required}"

# ===== SSH =====
export ORACLE_SSH_USER="${DEPLOY_ORACLE_SSH_USER:-ubuntu}"
export ORACLE_SSH_KEY="${DEPLOY_ORACLE_SSH_KEY:-}"
if [[ ! "${ORACLE_HOST}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "DEPLOY_ORACLE_HOST must be a plain IPv4 address, got: ${ORACLE_HOST}" >&2
  exit 1
fi
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30)
[[ -z "${ORACLE_SSH_KEY}" ]] || SSH_OPTS+=(-i "${ORACLE_SSH_KEY}")
export ORACLE_SSH_TARGET="${ORACLE_SSH_USER}@${ORACLE_HOST}"
oracle_ssh() { ssh "${SSH_OPTS[@]}" "${ORACLE_SSH_TARGET}" "$@"; }
oracle_scp() { scp "${SSH_OPTS[@]}" "$@"; }
oracle_rsync() { rsync -az --delete -e "ssh ${SSH_OPTS[*]}" "$@"; }

# ===== Origin: Caddy publishes this host port; minimax already uses 8080 =====
# Must be a port Cloudflare Workers may fetch (80, 443, 2052, 2053, 2082, 2083,
# 2086, 2087, 2095, 2096, 8080, 8443, 8880).
export ORIGIN_PORT="${DEPLOY_ORACLE_ORIGIN_PORT:-8880}"

# ===== Image built on the instance (tag = git revision) =====
git_sha="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
export DOCREVIEW_IMAGE="${DEPLOY_ORACLE_IMAGE:-docreview-rag:${git_sha}}"
# Source tree synced for the remote build; owned by the SSH user, no root needed.
export ORACLE_BUILD_DIR="${DEPLOY_ORACLE_BUILD_DIR:-/home/${ORACLE_SSH_USER}/build/docreview-rag}"

# ===== Secrets and artifacts (same names as deploy/gcp) =====
export POSTGRES_PASSWORD="${DEPLOY_POSTGRES_PASSWORD:-${POSTGRES_PASSWORD:-}}"
export ARTIFACT_DIR="${DEPLOY_ARTIFACT_DIR:-${HOME}/.local/share/docreview/prod-artifacts/20260909-portfolio18}"

_mask_len() {
  local s="${1:-}"
  if [[ -z "${s}" ]]; then echo "unset"; else echo "set(len=${#s})"; fi
}

if [ "${DEPLOY_SUMMARY:-1}" = "1" ]; then
  ui_heading "Oracle deployment configuration"
  ui_row "Host" "${ORACLE_SSH_TARGET}$( [[ -n "${ORACLE_SSH_KEY}" ]] && echo " (key ${ORACLE_SSH_KEY})")"
  ui_row "Origin port" "${ORIGIN_PORT} (VCN security list: Cloudflare IPv4 only)"
  ui_row "Image" "${DOCREVIEW_IMAGE} (built on the instance)"
  ui_row "Build dir" "${ORACLE_BUILD_DIR}"
  ui_row "Artifacts" "${ARTIFACT_DIR}"
  ui_row "Secrets" "postgres_password=$(_mask_len "${POSTGRES_PASSWORD}"), openai_api_key_prod=$(_mask_len "${OPENAI_API_KEY_PROD}")"
  ui_rule
fi
