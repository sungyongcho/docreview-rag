#!/usr/bin/env bash
# Create the single 4 GB origin VM and its firewall rules.
# Idempotent: every resource is described before it is created.
# This command creates GCP resources; review deploy_env_config.sh output first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh"

log() { if declare -F ui_log >/dev/null 2>&1; then ui_log "$*"; else echo "[$(date +'%F %T')] $*"; fi; }
warn() { if declare -F ui_warn >/dev/null 2>&1; then ui_warn "$*"; else echo "  ! $*" >&2; fi; }

# ----- VM: e2-medium, pd-standard 30 GB, ephemeral external IP (no --address) -----
if gcloud compute instances describe "${VM_NAME}" \
  --project "${PROJECT_ID}" --zone "${ZONE}" >/dev/null 2>&1; then
  log "VM exists: ${VM_NAME} (${ZONE})"
else
  # The dedicated service account (created by setup.sh) can pull deploy images.
  # Without it the VM falls back to the default compute identity; the cloud-platform
  # scope is required either way for Artifact Registry access.
  sa_args=()
  if gcloud iam service-accounts describe "${SA_EMAIL}" \
    --project "${PROJECT_ID}" >/dev/null 2>&1; then
    sa_args+=(--service-account "${SA_EMAIL}")
  else
    warn "service account ${SA_EMAIL} not found; run deploy/gcp/setup.sh first. Using the default compute identity."
  fi
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
    --scopes=https://www.googleapis.com/auth/cloud-platform \
    "${sa_args[@]}" \
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

# ----- Firewall: SSH only through IAP TCP forwarding -----
# 35.235.240.0/20 is Google's IAP range; port 22 stays closed to the public IP.
# The deploy scripts pass --tunnel-through-iap to gcloud compute ssh/scp.
SSH_RULE="docreview-ssh-iap"
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
    --source-ranges "35.235.240.0/20" \
    --target-tags "${NETWORK_TAG}" \
    --description "Allow SSH to DocReview VMs via IAP TCP forwarding only"
fi

log "Done. Next: build_image.sh pushes the image, then deploy_backend.sh, then print_origin.sh."
log "The external IP is ephemeral: it changes when the VM is stopped and started."
