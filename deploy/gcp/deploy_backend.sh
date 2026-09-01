#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
vm_name="${DOCREVIEW_VM_NAME:-docreview-rag-agent}"
zone="${DOCREVIEW_GCP_ZONE:-europe-west1-b}"

gcloud compute scp \
  "${repo_root}/docker-compose.prod.yml" \
  "${repo_root}/deploy/Caddyfile" \
  "${vm_name}:/tmp/" \
  --project "${GCP_PROJECT_ID}" \
  --zone "${zone}"

gcloud compute ssh "${vm_name}" \
  --project "${GCP_PROJECT_ID}" \
  --zone "${zone}" \
  --command 'sudo install -d -m 0755 /opt/docreview/deploy && sudo install -m 0644 /tmp/docker-compose.prod.yml /opt/docreview/docker-compose.yml && sudo install -m 0644 /tmp/Caddyfile /opt/docreview/deploy/Caddyfile && cd /opt/docreview && sudo docker compose pull && sudo docker compose up -d && sudo docker compose ps'
