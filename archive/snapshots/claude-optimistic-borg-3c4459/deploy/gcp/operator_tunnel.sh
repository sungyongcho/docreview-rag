#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
vm_name="${DOCREVIEW_VM_NAME:-docreview-rag-agent}"
zone="${DOCREVIEW_GCP_ZONE:-europe-west1-b}"
local_host="${DOCREVIEW_LOCAL_HOST:-127.0.0.1}"
local_port="${DOCREVIEW_TUNNEL_PORT:-18000}"
origin_port="${DOCREVIEW_ORIGIN_PORT:-8000}"

gcloud compute ssh "${vm_name}" \
  --project "${GCP_PROJECT_ID}" \
  --zone "${zone}" \
  -- -N -L "${local_host}:${local_port}:127.0.0.1:${origin_port}"
