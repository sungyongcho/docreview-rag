#!/usr/bin/env bash
# Bootstrap the Python runner without requiring a pre-existing virtual environment.
set -euo pipefail
export NO_COLOR=1 PYTHON_COLORS=0
unset FORCE_COLOR
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    printf '%s\n' 'Usage: rag-quickstart' \
        'Prepare a new local DEV checkout without deleting existing data.' \
        'Requires uv, Docker Engine, and Docker Compose 2.24.4+.' \
        'Order: prerequisites -> local .env -> Compose state/start -> schema -> server readiness.' \
        'Creates .env only when absent; edit the named settings locally and rerun this command.' \
        'Reports stopped, starting, unhealthy and already-running services for this checkout.' \
        'Prints application/tutorial URLs and the next data-preparation step after readiness.' \
        'Downloads Python dependencies and builds local containers.' \
        'Does not download filings, generate embeddings, or ask a model.'
    exit 0
fi
if [[ $# -ne 0 ]]; then printf '%s\n' 'Usage: rag-quickstart [--help]' >&2; exit 2; fi
printf '%s\n' '+-- [BOOTSTRAP] Tools and Python --+' \
    'Requires uv and Docker; prepares locked local dependencies without starting a model.'
for tool in uv docker; do
    command -v "$tool" >/dev/null || { printf 'Install %s, then rerun rag-quickstart.\n' "$tool" >&2; exit 1; }
done
cd "$root"
printf '%s\n' 'Checking prerequisites: uv, Docker Engine, Docker Compose.'
docker info >/dev/null 2>&1 || { printf '%s\n' 'Docker Engine is unavailable. Start Docker/check access, then rerun rag-quickstart.' >&2; exit 1; }
docker compose version --short >/dev/null
printf '%s\n' '+-- [PYTHON] Prepare the local runner --+' 'Install locked dependencies; configuration is checked next. No model request is made.'
uv sync --locked
exec .venv/bin/python -m scripts.stack.quickstart
