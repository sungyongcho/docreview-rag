#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
vm_name="${DOCREVIEW_VM_NAME:-docreview-rag-agent}"
zone="${DOCREVIEW_GCP_ZONE:-europe-west1-b}"
region="${zone%-*}"
address_name="${DOCREVIEW_ADDRESS_NAME:-docreview-rag-agent-ip}"

if ! gcloud compute addresses describe "${address_name}" --project "${GCP_PROJECT_ID}" --region "${region}" >/dev/null 2>&1; then
  gcloud compute addresses create "${address_name}" \
    --project "${GCP_PROJECT_ID}" \
    --region "${region}"
fi
external_ip="$(gcloud compute addresses describe "${address_name}" --project "${GCP_PROJECT_ID}" --region "${region}" --format='value(address)')"

gcloud compute instances create "${vm_name}" \
  --project "${GCP_PROJECT_ID}" \
  --zone "${zone}" \
  --machine-type e2-small \
  --boot-disk-size 30GB \
  --boot-disk-type pd-standard \
  --image-family ubuntu-2404-lts-amd64 \
  --image-project ubuntu-os-cloud \
  --address "${external_ip}" \
  --tags docreview-http,docreview-https \
  --metadata-from-file startup-script="$(dirname "$0")/startup.sh"

for port in "${DOCREVIEW_HTTP_PORT:-80}" "${DOCREVIEW_HTTPS_PORT:-443}"; do
  rule="docreview-allow-${port}"
  if ! gcloud compute firewall-rules describe "${rule}" --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
    gcloud compute firewall-rules create "${rule}" \
      --project "${GCP_PROJECT_ID}" \
      --direction INGRESS \
      --action ALLOW \
      --rules "tcp:${port}" \
      --target-tags "docreview-http,docreview-https"
  fi
done

echo "Created ${vm_name} in ${zone} at ${external_ip}. This command creates billable GCP resources."
