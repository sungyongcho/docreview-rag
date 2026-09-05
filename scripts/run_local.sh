#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"
mode=dev
if [[ "${1:-}" == dev || "${1:-}" == prod ]]; then
    mode="$1"
    shift
fi
exec .venv/bin/python -m scripts.local_stack "${mode}" "$@"
