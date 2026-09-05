#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "${repo_root}/.venv/bin/python" ]]; then
  printf '%s\n' '[FAIL] Project Python is missing. Run uv sync in the repository first.' >&2
  exit 2
fi
cd "${repo_root}"
exec "${repo_root}/.venv/bin/python" -m scripts.diagnose_ollama "$@"
