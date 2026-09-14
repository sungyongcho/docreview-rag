#!/usr/bin/env bash
# One-shot GCP deployment for the single e2-medium origin VM.
#
#   deploy_all.sh setup     Enable APIs, Artifact Registry repo and service account
#   deploy_all.sh vm        Create or verify the VM and firewall rules
#   deploy_all.sh image     Build and push the application image (docker buildx)
#   deploy_all.sh backend   Run the backend installer on the VM
#   deploy_all.sh origin    Print the Cloudflare/Firebase handoff values
#   deploy_all.sh all       setup -> vm -> image -> backend -> origin
#
# Options: --mode first-install|update|rollback (backend), --yes, --verbose
# Configuration comes from the repo .env via deploy_env_config.sh; see .env.example.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export REPO_ROOT
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/ui.sh"

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

stage="${1:-vm}"
case "${stage}" in
  setup|vm|image|backend|origin|all) ;;
  --help|-h|help) usage; exit 0 ;;
  *) ui_fail "Unknown stage: ${stage}"; usage; exit 2 ;;
esac
shift || true

mode="first-install"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode) mode="${2:?--mode needs first-install, update or rollback}"; shift 2 ;;
    --mode=*) mode="${1#*=}"; shift ;;
    --yes|-y) export DEPLOY_ASSUME_YES=1; shift ;;
    --verbose|-vv) export DEPLOY_VERBOSE=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) ui_fail "Unknown option: $1"; usage; exit 2 ;;
  esac
done
case "${mode}" in
  first-install|update|rollback) ;;
  *) ui_fail "Invalid mode: ${mode}"; exit 2 ;;
esac

# The one-shot prints the configuration summary once; child scripts stay quiet.
export DEPLOY_SUMMARY=0
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh"

preflight() {
  command -v gcloud >/dev/null 2>&1 || { ui_fail "gcloud CLI is required."; exit 1; }
  local account
  account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n 1)"
  if [ -z "${account}" ]; then
    ui_fail "No active gcloud account. Run first: gcloud auth login <account>"
    exit 1
  fi
  ui_ok "gcloud account: ${account}"
  if ! gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
    ui_fail "Cannot access GCP project: ${PROJECT_ID}"
    exit 1
  fi
  ui_ok "project: ${PROJECT_ID}"
  local enabled
  enabled="$(gcloud services list --enabled --project "${PROJECT_ID}" --format='value(config.name)' 2>/dev/null || true)"
  for api in compute.googleapis.com artifactregistry.googleapis.com iap.googleapis.com; do
    if printf '%s\n' "${enabled}" | grep -qx "${api}"; then ui_ok "API enabled: ${api}"; else ui_warn "API disabled: ${api} — the setup stage enables it"; fi
  done
}

require_vm() {
  if ! gcloud compute instances describe "${VM_NAME}" --project "${PROJECT_ID}" --zone "${ZONE}" >/dev/null 2>&1; then
    ui_fail "VM not found: ${VM_NAME} (${ZONE}) — run 'deploy_all.sh vm' first"
    exit 1
  fi
  ui_ok "VM: ${VM_NAME} (${ZONE})"
}

wait_for_ssh() {
  ui_log "Waiting for SSH… (first boot must finish installing Docker before the next stage)"
  local attempt
  for attempt in $(seq 1 30); do
    if gcloud compute ssh "${VM_NAME}" --project "${PROJECT_ID}" --zone "${ZONE}" \
      --tunnel-through-iap --command true >/dev/null 2>&1; then
      ui_ok "SSH ready (${attempt}/30)"
      return 0
    fi
    sleep 10
  done
  ui_fail "Timed out waiting for SSH — check the enabled IAP API, the docreview-ssh-iap firewall rule and the VM serial console log."
  return 1
}

stage_setup() {
  ui_step 1 5 "GCP project setup (APIs · Artifact Registry · service account)"
  ui_row "Registry" "${ARTIFACT_REGISTRY}"
  ui_row "Service account" "${SA_EMAIL}"
  ui_confirm "Proceed with project setup?" || { ui_warn "Cancelled."; exit 1; }
  ui_run "Project setup" bash "${SCRIPT_DIR}/setup.sh" || exit 1
}

stage_vm() {
  ui_step 2 5 "Prepare the e2-medium origin VM"
  ui_row "Machine" "${MACHINE_TYPE} · 4 GB RAM + 2 GB swap"
  ui_row "Disk" "${BOOT_DISK_SIZE} pd-standard · ${ZONE}"
  ui_confirm "Create or verify VM ${VM_NAME}?" || { ui_warn "Cancelled."; exit 1; }
  ui_run "Ensure VM ${VM_NAME}" bash "${SCRIPT_DIR}/create_vm.sh" || exit 1
  wait_for_ssh
}

stage_image() {
  ui_step 3 5 "Build and push the application image"
  command -v docker >/dev/null 2>&1 || { ui_fail "docker CLI is required."; exit 1; }
  ui_row "Image" "${DOCREVIEW_IMAGE}"
  ui_confirm "Build the image and push it to Artifact Registry?" || { ui_warn "Cancelled."; exit 1; }
  ui_run "Push ${DOCREVIEW_IMAGE}" bash "${SCRIPT_DIR}/build_image.sh" || exit 1
}

stage_backend() {
  require_vm
  if [ "${mode}" != rollback ] && [ -z "${DOCREVIEW_IMAGE}" ]; then
    ui_fail "DOCREVIEW_IMAGE is empty — set it in .env or use the Artifact Registry default."
    exit 1
  fi
  if [ "${mode}" = "first-install" ]; then
    if [ -z "${POSTGRES_PASSWORD}" ]; then
      ui_fail "DEPLOY_POSTGRES_PASSWORD is required — set it in .env (see .env.example)."
      exit 1
    fi
    local artifact_dir="${DEPLOY_ARTIFACT_DIR:-${HOME}/.local/share/docreview/prod-artifacts/20260909-portfolio18}"
    if [ ! -d "${artifact_dir}" ]; then
      ui_fail "Deployment artifact directory not found: ${artifact_dir}"
      exit 1
    fi
    ui_ok "artifacts: ${artifact_dir}"
  fi
  ui_step 4 5 "Backend ${mode}"
  ui_confirm "Run the backend ${mode} deployment on the VM?" || { ui_warn "Cancelled."; exit 1; }
  ui_run "Backend ${mode}" bash "${SCRIPT_DIR}/deploy_backend.sh" "${mode}" || exit 1
}

stage_origin() {
  require_vm
  ui_step 5 5 "Cloudflare / Firebase handoff"
  local output
  output="$(bash "${SCRIPT_DIR}/print_origin.sh")" || { ui_fail "print_origin.sh failed (check FIREBASE_SITE or deploy/firebase/.firebaserc)"; exit 1; }
  while IFS= read -r line; do
    ui_row "${line%%=*}" "${line#*=}"
  done <<< "${output}"
  ui_dim "Configure the site's routing Worker with these origins and deploy it through its own routing workflow."
  ui_dim "Build and deploy the static site with scripts/deploy/firebase.sh."
}

ui_banner
ui_heading "Deployment configuration"
ui_row "Stage" "${stage}"
ui_row "Project" "${PROJECT_ID}"
ui_row "Region" "${REGION} (${ZONE})"
ui_row "VM" "${VM_NAME} (${MACHINE_TYPE})"
ui_row "Registry" "${AR_REPO} → ${ARTIFACT_REGISTRY}"
ui_row "Origin port" "${ORIGIN_PORT} (tag ${NETWORK_TAG})"
ui_row "Image" "${DOCREVIEW_IMAGE}"
ui_rule

case "${stage}" in
  setup) preflight; stage_setup ;;
  vm) preflight; stage_vm ;;
  image) preflight; stage_image ;;
  backend) preflight; stage_backend ;;
  origin) preflight; stage_origin ;;
  all) preflight; stage_setup; stage_vm; stage_image; stage_backend; stage_origin ;;
esac

printf '\n'
ui_ok "Done: ${stage}"
ui_dim "Next stages: setup → vm → image → backend → origin (or all)"
