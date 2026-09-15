#!/usr/bin/env bash
# Build the application image on the Oracle instance and stage an explicit
# first installation, update only the existing application image, or roll back.
# Counterpart of deploy/gcp/deploy_backend.sh with plain ssh/rsync and no registry.
set -euo pipefail

mode="${1:-}"
case "${mode}" in
  first-install|update|rollback) ;;
  *) echo "Usage: $0 {first-install|update|rollback}" >&2; exit 2 ;;
esac
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh"

note() { ui_log "$*"; }
ok() { ui_ok "$*"; }

for cmd in ssh scp rsync python3; do
  command -v "${cmd}" >/dev/null 2>&1 || { echo "Missing required command: ${cmd}" >&2; exit 1; }
done

DO_BUILD="${DO_BUILD:-true}"
[[ "${mode}" != rollback ]] || { DOCREVIEW_IMAGE=""; DO_BUILD=false; }
if [[ "${mode}" != rollback && ! "${DOCREVIEW_IMAGE}" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/:@-]*$ ]]; then
  echo "Invalid application image reference." >&2
  exit 1
fi

if [[ "${mode}" == first-install ]]; then
  : "${POSTGRES_PASSWORD:?DEPLOY_POSTGRES_PASSWORD is required in .env}"
  [[ -d "${ARTIFACT_DIR}" ]] || { echo "Deployment artifact directory not found: ${ARTIFACT_DIR}" >&2; exit 1; }
  # A validated allowlist never includes database.private.dump or local metadata.
  artifact_list="$(python3 "${GCP_DIR}/verify_artifacts.py" "${ARTIFACT_DIR}" --list-files)"
fi

# ---------------------------------------------------------------------------
# 1. Build the image on the instance (aarch64). The Dockerfile and uv.lock already
#    carry linux/aarch64 wheels (torch +cpu, tokenizers, lxml, asyncpg, numpy).
# ---------------------------------------------------------------------------
if [[ "${DO_BUILD}" == true ]]; then
  note "Syncing source tree to ${ORACLE_SSH_TARGET}:${ORACLE_BUILD_DIR}"
  oracle_ssh "install -d -m 0755 '${ORACLE_BUILD_DIR}'"
  # Mirror .dockerignore plus local-only state; the remote build context must not
  # receive secrets, private dumps, local corpora or an x86_64 virtualenv.
  oracle_rsync \
    --exclude '.git/' --exclude '.venv/' --exclude '.env' --exclude '.env.*' \
    --exclude '.dashboard/' --exclude '.dashboard-cache/' --exclude '.claude/' \
    --exclude 'tests/' --exclude 'tmp/' --exclude '.pytest_cache/' --exclude '.ruff_cache/' \
    --exclude '__pycache__/' --exclude '*.pyc' \
    --exclude 'web/node_modules/' --exclude 'web/.next/' --exclude 'web/out/' \
    --exclude 'data/eval_runs/' --exclude 'data/corpus/' --exclude 'data/runtime/' \
    --exclude 'data/local-prod/' --exclude 'data/local-settings/' \
    --exclude 'deploy/firebase/public/' --exclude 'deploy/firebase/.firebase/' \
    "${REPO_ROOT}/" "${ORACLE_SSH_TARGET}:${ORACLE_BUILD_DIR}/"
  ok "source synced"

  note "Building ${DOCREVIEW_IMAGE} on the instance (first build: Next.js + uv sync, 10-20 min on 2 cores)"
  oracle_ssh "cd '${ORACLE_BUILD_DIR}' && sudo docker build --file docker/Dockerfile --tag '${DOCREVIEW_IMAGE}' ."
  ok "image ${DOCREVIEW_IMAGE} built"
fi

# ---------------------------------------------------------------------------
# 2. Stage credentials and artifacts in one private remote directory.
# ---------------------------------------------------------------------------
note "Staging ${mode} on ${ORACLE_HOST}"
remote_stage="$(oracle_ssh 'umask 077; mktemp -d /tmp/docreview-deploy.XXXXXXXX')"
[[ "${remote_stage}" =~ ^/tmp/docreview-deploy\.[a-zA-Z0-9]+$ ]] \
  || { echo "Unexpected remote staging path." >&2; exit 1; }
oracle_scp "${SCRIPT_DIR}/apply_backend.sh" "${ORACLE_SSH_TARGET}:${remote_stage}/"

if [[ "${mode}" == first-install ]]; then
  local_stage="$(mktemp -d /tmp/docreview-deploy.XXXXXXXX)"
  trap 'rm -rf "${local_stage}"' EXIT
  # Export only the VM configuration, including the key inherited from the root dotenv.
  DOCREVIEW_ORIGIN_PORT="${ORIGIN_PORT}" python3 - "${local_stage}/backend.env" <<'PY'
import os
from pathlib import Path
import shlex
import sys

values = {name: os.environ[name] for name in (
    "DOCREVIEW_IMAGE", "POSTGRES_PASSWORD", "OPENAI_API_KEY_PROD"
)}
values["POSTGRES_PASSWORD_FILE"] = "/var/lib/docreview/secrets/postgres_password"
values["DOCREVIEW_ORIGIN_PORT"] = os.environ.get("DOCREVIEW_ORIGIN_PORT", "8880")
target = Path(sys.argv[1])
target.write_text("".join(f"{name}={shlex.quote(value)}\n" for name, value in values.items()))
target.chmod(0o600)
PY
  # Compose file, Caddyfile and verifiers are shared with the GCP path on purpose:
  # the runtime layout on the instance is identical.
  oracle_scp \
    "${GCP_DIR}/docker-compose.deploy.yml" "${REPO_ROOT}/deploy/Caddyfile" \
    "${GCP_DIR}/verify_artifacts.py" "${GCP_DIR}/verify_restore.sql" \
    "${local_stage}/backend.env" "${ORACLE_SSH_TARGET}:${remote_stage}/"
  oracle_ssh "install -d -m 0700 '${remote_stage}/artifacts/eval_runs'"
  while IFS= read -r name; do
    destination="${remote_stage}/artifacts/$(dirname "${name}")/"
    oracle_scp "${ARTIFACT_DIR}/${name}" "${ORACLE_SSH_TARGET}:${destination}"
  done <<< "${artifact_list}"
  ok "artifacts staged"
fi

# ---------------------------------------------------------------------------
# 3. Apply as root; the staging directory is removed afterwards.
# ---------------------------------------------------------------------------
oracle_ssh -t "sudo bash '${remote_stage}/apply_backend.sh' '${mode}' '${remote_stage}' '${DOCREVIEW_IMAGE}'; status=\$?; sudo rm -rf '${remote_stage}'; exit \${status}"
ok "Backend ${mode} finished on ${ORACLE_HOST}"

note "Health from the instance:"
oracle_ssh "curl -fsS 'http://127.0.0.1:${ORIGIN_PORT}/health' && echo"
ui_dim "Next: bash ${SCRIPT_DIR}/print_origin.sh (values for the gomoku .env), then gomoku/deploy/03_deploy_cloudflare.sh."
