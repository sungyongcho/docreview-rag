#!/usr/bin/env bash
# Stage an explicit first installation or update only the existing application image.
set -euo pipefail

mode="${1:-}"
case "${mode}" in
  first-install|update|rollback) ;;
  *) echo "Usage: $0 {first-install|update|rollback}" >&2; exit 2 ;;
esac
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh"

note() { if declare -F ui_log >/dev/null 2>&1; then ui_log "$*"; else printf '[%s] %s\n' "$(date +'%F %T')" "$*"; fi; }
ok() { if declare -F ui_ok >/dev/null 2>&1; then ui_ok "$*"; else printf '  ✓ %s\n' "$*"; fi; }

[[ "${mode}" != rollback ]] || DOCREVIEW_IMAGE=""
[[ "${mode}" == rollback ]] || : "${DOCREVIEW_IMAGE:?DOCREVIEW_IMAGE is required in backend.env}"
if [[ ! "${DOCREVIEW_IMAGE}" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/:@-]*$ && "${mode}" != rollback ]]; then
  echo "Invalid application image reference." >&2
  exit 1
fi

artifact_dir="${DEPLOY_ARTIFACT_DIR:-/home/wwaya/.local/share/docreview/prod-artifacts/20260909-portfolio18}"
if [[ "${mode}" == first-install ]]; then
  [[ -f "${BACKEND_ENV_PATH}" ]] || { echo "backend env not found: ${BACKEND_ENV_PATH}" >&2; exit 1; }
  : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required in backend.env}"
  # A validated allowlist never includes database.private.dump or local metadata.
  artifact_list="$(python3 "${SCRIPT_DIR}/verify_artifacts.py" "${artifact_dir}" --list-files)"
fi

# Keep credentials and selected artifacts inside one private, unique staging directory.
note "Staging ${mode} on ${VM_NAME}"
remote_stage="$(gcloud compute ssh "${VM_NAME}" --project "${PROJECT_ID}" --zone "${ZONE}" \
  --command 'umask 077; mktemp -d /tmp/docreview-deploy.XXXXXXXX')"
[[ "${remote_stage}" =~ ^/tmp/docreview-deploy\.[a-zA-Z0-9]+$ ]] \
  || { echo "Unexpected remote staging path." >&2; exit 1; }
gcloud compute scp "${SCRIPT_DIR}/apply_backend.sh" "${VM_NAME}:${remote_stage}/" \
  --project "${PROJECT_ID}" --zone "${ZONE}"

if [[ "${mode}" == first-install ]]; then
  local_stage="$(mktemp -d /tmp/docreview-deploy.XXXXXXXX)"
  # Export only the VM configuration, including the key inherited from the root dotenv.
  python3 - "${local_stage}/backend.env" <<'PY'
import os
from pathlib import Path
import shlex
import sys

values = {name: os.environ[name] for name in (
    "DOCREVIEW_IMAGE", "POSTGRES_PASSWORD", "OPENAI_API_KEY_PROD"
)}
values["POSTGRES_PASSWORD_FILE"] = "/var/lib/docreview/secrets/postgres_password"
values["DOCREVIEW_ORIGIN_PORT"] = os.environ.get("DOCREVIEW_ORIGIN_PORT", "8000")
target = Path(sys.argv[1])
target.write_text("".join(f"{name}={shlex.quote(value)}\n" for name, value in values.items()))
target.chmod(0o600)
PY
  gcloud compute scp \
    "${SCRIPT_DIR}/docker-compose.deploy.yml" "${REPO_ROOT}/deploy/Caddyfile" \
    "${SCRIPT_DIR}/verify_artifacts.py" "${SCRIPT_DIR}/verify_restore.sql" \
    "${local_stage}/backend.env" "${VM_NAME}:${remote_stage}/" \
    --project "${PROJECT_ID}" --zone "${ZONE}"
  gcloud compute ssh "${VM_NAME}" --project "${PROJECT_ID}" --zone "${ZONE}" \
    --command "install -d -m 0700 '${remote_stage}/artifacts/eval_runs'"
  while IFS= read -r name; do
    destination="${remote_stage}/artifacts/$(dirname "${name}")/"
    gcloud compute scp "${artifact_dir}/${name}" "${VM_NAME}:${destination}" \
      --project "${PROJECT_ID}" --zone "${ZONE}"
  done <<< "${artifact_list}"
fi

gcloud compute ssh "${VM_NAME}" --project "${PROJECT_ID}" --zone "${ZONE}" \
  --command "sudo bash '${remote_stage}/apply_backend.sh' '${mode}' '${remote_stage}' '${DOCREVIEW_IMAGE}'"
ok "Backend ${mode} finished on ${VM_NAME}"
