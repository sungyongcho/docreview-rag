#!/usr/bin/env bash
# One-shot GCP project setup for the single e2-medium origin.
# Idempotent: enables the required APIs, creates the Artifact Registry
# repository and the deployment service account with minimal roles.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh"

log() { if declare -F ui_log >/dev/null 2>&1; then ui_log "$*"; else echo "[$(date +'%F %T')] $*"; fi; }
ok() { if declare -F ui_ok >/dev/null 2>&1; then ui_ok "$*"; else printf '  ✓ %s\n' "$*"; fi; }

command -v gcloud >/dev/null 2>&1 || { echo "Missing required command: gcloud" >&2; exit 1; }

account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n 1)"
[[ -n "${account}" ]] || { echo "No active gcloud account. Run: gcloud auth login <account>" >&2; exit 1; }

# ----- APIs -----
log "Enabling required services on ${PROJECT_ID}..."
gcloud services enable \
  compute.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iap.googleapis.com \
  --project "${PROJECT_ID}"
ok "APIs enabled"

# ----- Artifact Registry repository -----
if gcloud artifacts repositories describe "${AR_REPO}" \
  --location "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  log "Repository exists: ${AR_REPO} (${REGION})"
else
  log "Creating Artifact Registry repository ${AR_REPO} (${REGION})..."
  gcloud artifacts repositories create "${AR_REPO}" \
    --repository-format docker \
    --location "${REGION}" \
    --description "DocReview deploy images" \
    --project "${PROJECT_ID}"
fi
ok "registry: ${ARTIFACT_REGISTRY}"

# ----- Deployment service account (the VM pulls images as this identity) -----
if gcloud iam service-accounts describe "${SA_EMAIL}" \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  log "Service account exists: ${SA_EMAIL}"
else
  log "Creating service account ${SA_NAME}..."
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name "DocReview deploy" \
    --project "${PROJECT_ID}"
  sleep 10
fi

for role in roles/artifactregistry.reader roles/logging.logWriter roles/monitoring.metricWriter; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${SA_EMAIL}" \
    --role "${role}" >/dev/null
  log "Granted ${role}"
done

# The deploying account must be allowed to attach the service account to the VM.
gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --member "user:${account}" \
  --role "roles/iam.serviceAccountUser" \
  --project "${PROJECT_ID}" >/dev/null
ok "service account: ${SA_EMAIL} (usable by ${account})"

log "Done. Next: create_vm.sh, then build_image.sh to push ${DOCREVIEW_IMAGE}."
