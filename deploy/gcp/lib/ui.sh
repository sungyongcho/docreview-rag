#!/usr/bin/env bash
# Shared terminal output for the GCP deployment scripts. Source it; do not execute it.
# Colors, collapsed command output and the branding banner follow rag-alias.sh.
# Redirected or NO_COLOR output stays plain, so CI logs remain readable.

_ui_color() {
  [ -t 1 ] && [ -z "${NO_COLOR+x}" ] && [ "${TERM:-}" != dumb ]
}

ui_heading() {
  if _ui_color; then printf '\033[36;1m%s\033[0m\n' "$*"; else printf '%s\n' "$*"; fi
}

ui_dim() {
  if _ui_color; then printf '\033[2m%s\033[0m\n' "$*"; else printf '%s\n' "$*"; fi
}

ui_ok() {
  if _ui_color; then printf '\033[32;1m  ✓\033[0m %s\n' "$*"; else printf '  ✓ %s\n' "$*"; fi
}

ui_warn() {
  if _ui_color; then printf '\033[33;1m  !\033[0m %s\n' "$*"; else printf '  ! %s\n' "$*"; fi
}

ui_fail() {
  if _ui_color; then printf '\033[31;1m  ✗\033[0m %s\n' "$*" >&2; else printf '  ✗ %s\n' "$*" >&2; fi
}

ui_log() {
  if _ui_color; then printf '\033[2m[%s]\033[0m %s\n' "$(date +'%F %T')" "$*"; else printf '[%s] %s\n' "$(date +'%F %T')" "$*"; fi
}

ui_row() {
  if _ui_color; then printf '  \033[1m%-24s\033[0m  %s\n' "$1" "$2"; else printf '  %-24s  %s\n' "$1" "$2"; fi
}

ui_rule() {
  if _ui_color; then printf '\033[2m%s\033[0m\n' "────────────────────────────────────────────────────────────"; else printf '%s\n' "------------------------------------------------------------"; fi
}

ui_step() {
  local current="$1" total="$2" title="$3"
  printf '\n'
  if _ui_color; then printf '\033[36;1m▶ Step %s/%s\033[0m  \033[1m%s\033[0m\n' "${current}" "${total}" "${title}"; else printf '▶ Step %s/%s  %s\n' "${current}" "${total}" "${title}"; fi
}

# Confirm before a cloud-changing action; --yes skips the prompt.
ui_confirm() {
  local prompt="$1"
  if [ "${DEPLOY_ASSUME_YES:-0}" = "1" ]; then ui_dim "  (auto-confirmed) ${prompt}"; return 0; fi
  local answer
  if _ui_color; then printf '\033[1m%s [y/N] \033[0m' "${prompt}"; else printf '%s [y/N] ' "${prompt}"; fi
  read -r answer || answer=""
  case "${answer}" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# Run one command with collapsed output: summary on success, tail on failure.
ui_run() {
  local label="$1"; shift
  local log_file code
  log_file="$(mktemp)"
  if "$@" >"${log_file}" 2>&1; then
    code=0
  else
    code=$?
  fi
  if [ "${DEPLOY_VERBOSE:-0}" = "1" ]; then
    sed 's/^/    /' "${log_file}"
  fi
  if [ "${code}" -eq 0 ]; then
    ui_ok "${label}"
  else
    ui_fail "${label} (exit ${code})"
    if [ "${DEPLOY_VERBOSE:-0}" != "1" ] && [ -s "${log_file}" ]; then
      tail -n 15 "${log_file}" | sed 's/^/      /' >&2
    fi
  fi
  rm -f "${log_file}"
  return "${code}"
}

# Branding banner: reuse the shared wordmark/monogram assets at a readable width.
ui_banner() {
  local columns="${COLUMNS:-80}" asset='' root="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
  case "${columns}" in ''|*[!0-9]*) columns=80 ;; esac
  if [ "${columns}" -ge 78 ]; then asset="${root}/web/branding/wordmark.txt"
  elif [ "${columns}" -ge 18 ]; then asset="${root}/web/branding/monogram.txt"; fi
  printf '\n'
  if [ -n "${asset}" ] && [ -r "${asset}" ]; then cat -- "${asset}"; printf '\n'; fi
  if _ui_color; then printf '\033[1mDocReview RAG v2\033[0m · GCP deployment\n'; else printf 'DocReview RAG v2 · GCP deployment\n'; fi
  ui_dim 'Single e2-medium origin · 2 shared vCPU · 4 GB RAM + 2 GB swap · 30 GB pd-standard'
}
