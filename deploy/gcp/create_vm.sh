#!/usr/bin/env bash
# Create the single Always Free origin VM and its Cloudflare-only firewall rule.
# Idempotent: every resource is described before it is created.
# This command creates GCP resources; review deploy_env_config.sh output first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh"

log() { echo "[$(date +'%F %T')] $*"; }

# ----- VM: e2-micro, pd-standard 30 GB, ephemeral external IP (no --address) -----
if gcloud compute instances describe "${VM_NAME}" \
  --project "${PROJECT_ID}" --zone "${ZONE}" >/dev/null 2>&1; then
  log "VM exists: ${VM_NAME} (${ZONE})"
else
  log "Creating VM ${VM_NAME} in ${ZONE}..."
  gcloud compute instances create "${VM_NAME}" \
    --project "${PROJECT_ID}" \
    --zone "${ZONE}" \
    --machine-type "${MACHINE_TYPE}" \
    --boot-disk-size "${BOOT_DISK_SIZE}" \
    --boot-disk-type pd-standard \
    --image-family ubuntu-2404-lts-amd64 \
    --image-project ubuntu-os-cloud \
    --tags "${NETWORK_TAG}" \
    --metadata-from-file startup-script="${SCRIPT_DIR}/startup.sh"
fi

# ----- Firewall: origin port reachable only from Cloudflare IPv4 ranges -----
# Cloudflare publishes the canonical list at https://www.cloudflare.com/ips-v4.
# The Worker in the gomoku repo is the only client that should reach the origin.
CF_IPV4_RANGES="$(curl -fsSL https://www.cloudflare.com/ips-v4 | tr '\n' ',' | sed 's/,$//')"
if [[ -z "${CF_IPV4_RANGES}" ]]; then
  echo "Failed to fetch Cloudflare IPv4 ranges." >&2
  exit 1
fi

ORIGIN_RULE="docreview-allow-cloudflare-${ORIGIN_PORT}"
if gcloud compute firewall-rules describe "${ORIGIN_RULE}" \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  log "Firewall rule exists: ${ORIGIN_RULE}"
else
  log "Creating firewall rule ${ORIGIN_RULE}..."
  gcloud compute firewall-rules create "${ORIGIN_RULE}" \
    --project "${PROJECT_ID}" \
    --direction INGRESS \
    --priority 1000 \
    --network default \
    --action ALLOW \
    --rules "tcp:${ORIGIN_PORT}" \
    --source-ranges "${CF_IPV4_RANGES}" \
    --target-tags "${NETWORK_TAG}" \
    --description "Allow DocReview API traffic from Cloudflare to port ${ORIGIN_PORT}"
fi

# ----- SSH through Identity-Aware Proxy (gcloud compute ssh --tunnel-through-iap) -----
# The default network usually ships with default-allow-ssh; this rule keeps SSH
# working if that rule was removed, without opening port 22 to the internet.
SSH_RULE="docreview-allow-ssh-iap"
if gcloud compute firewall-rules describe "${SSH_RULE}" \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  log "Firewall rule exists: ${SSH_RULE}"
else
  log "Creating firewall rule ${SSH_RULE}..."
  gcloud compute firewall-rules create "${SSH_RULE}" \
    --project "${PROJECT_ID}" \
    --direction INGRESS \
    --priority 1000 \
    --network default \
    --action ALLOW \
    --rules tcp:22 \
    --source-ranges 35.235.240.0/20 \
    --target-tags "${NETWORK_TAG}" \
    --description "Allow SSH to DocReview origin through IAP"
fi

log "Done. Next: deploy_backend.sh, then print_origin.sh for the Worker variables."
log "The external IP is ephemeral: it changes when the VM is stopped and started."
