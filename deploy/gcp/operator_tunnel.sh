#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
vm_name="${DOCREVIEW_VM_NAME:-docreview-rag-agent}"
zone="${DOCREVIEW_GCP_ZONE:-europe-west1-b}"

gcloud compute ssh "${vm_name}" \
  --project "${GCP_PROJECT_ID}" \
  --zone "${zone}" \
  -- -N -L 18000:127.0.0.1:8000
