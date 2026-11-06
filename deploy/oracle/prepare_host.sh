#!/usr/bin/env bash
# One-time preparation of the Oracle instance for DocReview. Safe to re-run; an
# application update does not need it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/deploy_env_config.sh"

remote_stage="$(oracle_ssh 'mktemp -d /tmp/docreview-host.XXXXXXXX')"
oracle_scp "${SCRIPT_DIR}/host_setup.sh" "${ORACLE_SSH_TARGET}:${remote_stage}/host_setup.sh"
oracle_ssh -t "sudo bash '${remote_stage}/host_setup.sh' '${ORACLE_SSH_USER}' '${ORIGIN_PORT}'; rm -rf '${remote_stage}'"
ui_ok "Host prepared. The VCN security list must allow tcp/${ORIGIN_PORT} from Cloudflare IPv4 ranges only."
