#!/usr/bin/env bash
# One-shot GCP deployment for the single e2-medium origin VM.
#
#   deploy_all.sh vm        Create or verify the VM (default)
#   deploy_all.sh backend   Run the backend installer on the VM
#   deploy_all.sh origin    Print the Cloudflare/Firebase handoff values
#   deploy_all.sh all       vm -> backend -> origin
#
# Options: --mode first-install|update|rollback (backend), --yes, --verbose
# Configuration comes from the repo .env and deploy/gcp/backend.env via deploy_env_config.sh.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
export REPO_ROOT
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/ui.sh"

usage() {
  sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

stage="${1:-vm}"
case "${stage}" in
  vm|backend|origin|all) ;;
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
  command -v gcloud >/dev/null 2>&1 || { ui_fail "gcloud CLI가 필요합니다."; exit 1; }
  local account
  account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n 1)"
  if [ -z "${account}" ]; then
    ui_fail "활성 gcloud 계정이 없습니다. 먼저 실행: gcloud auth login <account>"
    exit 1
  fi
  ui_ok "gcloud account: ${account}"
  if ! gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
    ui_fail "GCP 프로젝트에 접근할 수 없습니다: ${PROJECT_ID}"
    exit 1
  fi
  ui_ok "project: ${PROJECT_ID}"
  local enabled
  enabled="$(gcloud services list --enabled --project "${PROJECT_ID}" --format='value(config.name)' 2>/dev/null || true)"
  for api in compute.googleapis.com artifactregistry.googleapis.com; do
    if printf '%s\n' "${enabled}" | grep -qx "${api}"; then ui_ok "API enabled: ${api}"; else ui_warn "API disabled: ${api}"; fi
  done
  if [ ! -f "${BACKEND_ENV_PATH}" ]; then
    ui_warn "backend.env 없음: ${BACKEND_ENV_PATH} (backend 단계 전에 deploy/gcp/backend.env.example 을 복사해 채우세요)"
  fi
}

require_vm() {
  if ! gcloud compute instances describe "${VM_NAME}" --project "${PROJECT_ID}" --zone "${ZONE}" >/dev/null 2>&1; then
    ui_fail "VM이 없습니다: ${VM_NAME} (${ZONE}) — 먼저 'deploy_all.sh vm' 실행"
    exit 1
  fi
  ui_ok "VM: ${VM_NAME} (${ZONE})"
}

wait_for_ssh() {
  ui_log "SSH 준비 대기 중… (첫 부팅에서 Docker 설치가 끝나야 다음 단계가 가능합니다)"
  local attempt
  for attempt in $(seq 1 30); do
    if gcloud compute ssh "${VM_NAME}" --project "${PROJECT_ID}" --zone "${ZONE}" --command true >/dev/null 2>&1; then
      ui_ok "SSH ready (${attempt}/30)"
      return 0
    fi
    sleep 10
  done
  ui_fail "SSH 연결 대기 시간 초과 — GCP 콘솔의 직렬 콘솔 로그와 방화벽 SSH 규칙을 확인하세요."
  return 1
}

stage_vm() {
  ui_step 1 3 "e2-medium 원본 VM 준비"
  ui_row "Machine" "${MACHINE_TYPE} · 4 GB RAM + 2 GB swap"
  ui_row "Disk" "${BOOT_DISK_SIZE} pd-standard · ${ZONE}"
  ui_confirm "VM ${VM_NAME} 생성/확인을 진행할까요?" || { ui_warn "취소했습니다."; exit 1; }
  ui_run "Ensure VM ${VM_NAME}" bash "${SCRIPT_DIR}/create_vm.sh" || exit 1
  wait_for_ssh
}

stage_backend() {
  require_vm
  [ -f "${BACKEND_ENV_PATH}" ] || { ui_fail "backend.env가 필요합니다: ${BACKEND_ENV_PATH}"; exit 1; }
  if [ "${mode}" = "first-install" ]; then
    local artifact_dir="${DEPLOY_ARTIFACT_DIR:-${HOME}/.local/share/docreview/prod-artifacts/20260909-portfolio18}"
    if [ ! -d "${artifact_dir}" ]; then
      ui_fail "배포 아티팩트 디렉터리가 없습니다: ${artifact_dir}"
      exit 1
    fi
    ui_ok "artifacts: ${artifact_dir}"
  fi
  ui_step 2 3 "Backend ${mode}"
  ui_confirm "VM에서 backend ${mode} 배포를 실행할까요?" || { ui_warn "취소했습니다."; exit 1; }
  ui_run "Backend ${mode}" bash "${SCRIPT_DIR}/deploy_backend.sh" "${mode}" || exit 1
}

stage_origin() {
  require_vm
  ui_step 3 3 "Cloudflare / Firebase handoff"
  local output
  output="$(bash "${SCRIPT_DIR}/print_origin.sh")" || { ui_fail "print_origin.sh 실패 (Firebase site 설정을 확인하세요)"; exit 1; }
  while IFS= read -r line; do
    ui_row "${line%%=*}" "${line#*=}"
  done <<< "${output}"
  ui_dim "위 값을 ~/Documents/gomoku/.env 에 추가하고 그쪽 03_deploy_cloudflare.sh 를 실행하세요."
  ui_dim "정적 사이트는 scripts/deploy/firebase.sh 로 빌드·배포합니다."
}

ui_banner
ui_heading "Deployment configuration"
ui_row "Stage" "${stage}"
ui_row "Project" "${PROJECT_ID}"
ui_row "Region" "${REGION} (${ZONE})"
ui_row "VM" "${VM_NAME} (${MACHINE_TYPE})"
ui_row "Origin port" "${ORIGIN_PORT} (tag ${NETWORK_TAG})"
ui_row "Backend env" "${BACKEND_ENV_PATH}"
ui_rule

case "${stage}" in
  vm) preflight; stage_vm ;;
  backend) preflight; stage_backend ;;
  origin) preflight; stage_origin ;;
  all) preflight; stage_vm; stage_backend; stage_origin ;;
esac

printf '\n'
ui_ok "완료: ${stage}"
ui_dim "다음: VM만 확인했다면 deploy_all.sh backend, 그다음 origin · all"
