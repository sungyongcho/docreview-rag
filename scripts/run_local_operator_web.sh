#!/usr/bin/env bash
set -euo pipefail

# Retain the earlier entry point; the launcher now owns the detached host service.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "${repo_root}/scripts/run_local.sh" dev up "$@"
