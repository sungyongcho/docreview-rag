#!/usr/bin/env bash
# Bootstrap the Python runner without requiring a pre-existing virtual environment.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    printf '%s\n' 'Usage: rag-quickstart' \
        'Prepare a new local DEV checkout without deleting existing data.' \
        'Requires uv, Docker Engine, and Docker Compose 2.24.4+.' \
        'Creates .env only when absent; never displays credentials.' \
        'Downloads Python dependencies and builds local containers.' \
        'Does not download filings, generate embeddings, or ask a model.'
    exit 0
fi
if [[ $# -ne 0 ]]; then printf '%s\n' 'Usage: rag-quickstart [--help]' >&2; exit 2; fi
for tool in uv docker; do
    command -v "$tool" >/dev/null || { printf 'Install %s, then rerun rag-quickstart.\n' "$tool" >&2; exit 1; }
done
cd "$root"
docker info >/dev/null
docker compose version --short >/dev/null
uv sync --locked
exec .venv/bin/python -m scripts.quickstart
