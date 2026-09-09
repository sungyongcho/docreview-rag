#!/usr/bin/env bash
# Copy the compose file, Caddyfile and backend.env to the VM and (re)start the stack.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh"

if [[ ! -f "${BACKEND_ENV_PATH}" ]]; then
  echo "backend env not found: ${BACKEND_ENV_PATH} (copy backend.env.example)" >&2
  exit 1
fi
: "${DOCREVIEW_IMAGE:?DOCREVIEW_IMAGE is required in backend.env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required in backend.env}"

gcloud compute scp \
  "${REPO_ROOT}/deploy/gcp/docker-compose.deploy.yml" \
  "${REPO_ROOT}/deploy/Caddyfile" \
  "${BACKEND_ENV_PATH}" \
  "${VM_NAME}:/tmp/" \
  --project "${PROJECT_ID}" \
  --zone "${ZONE}"

# backend.env lands as /opt/docreview/.env, which docker compose reads for
# ${VAR} substitution. The Postgres password file is written from the same value
# so the db service secret and the app DATABASE_URL never drift apart.
remote_cmd='set -e
sudo install -d -m 0755 /opt/docreview /opt/docreview/deploy
sudo install -d -m 0700 /var/lib/docreview/secrets
sudo install -m 0644 /tmp/docker-compose.deploy.yml /opt/docreview/docker-compose.yml
sudo install -m 0644 /tmp/Caddyfile /opt/docreview/deploy/Caddyfile
sudo install -m 0600 /tmp/backend.env /opt/docreview/.env
sudo rm -f /tmp/backend.env
sudo sh -c "set -a; . /opt/docreview/.env; set +a; printf %s \"\$POSTGRES_PASSWORD\" > /var/lib/docreview/secrets/postgres_password"
sudo chmod 0600 /var/lib/docreview/secrets/postgres_password
cd /opt/docreview
sudo docker compose pull
sudo docker compose up -d
sudo docker compose ps'

gcloud compute ssh "${VM_NAME}" \
  --project "${PROJECT_ID}" \
  --zone "${ZONE}" \
  --command "${remote_cmd}"
