#!/usr/bin/env bash
# Bootstrap the Python runner without requiring a pre-existing virtual environment.
set -euo pipefail
if [[ ! -t 1 || ${NO_COLOR+x} || ${TERM:-} == dumb ]]; then
    export NO_COLOR=1 PYTHON_COLORS=0
else
    export PYTHON_COLORS=1
fi
unset FORCE_COLOR
args=()
for arg in "$@"; do
    case "$arg" in --verbose|-vv) export DOCREVIEW_VERBOSE=1 ;; *) args+=("$arg") ;; esac
done
set -- "${args[@]}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    printf '%s\n' 'Usage: rag-start-quick [--verbose|-vv|--status]' \
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
if [[ "${1:-}" == --status && $# -eq 1 ]]; then
    cd "$root"
    status_python="$(uv python find --no-python-downloads 3.14)" || { printf '%s\n' 'Python 3.14 is required to read receipts; run uv python install 3.14.' >&2; exit 2; }
    exec "$status_python" -c 'from pathlib import Path; from scripts.stack.fresh import status; raise SystemExit(status(Path.cwd(), "start-quick"))'
fi
if [[ $# -ne 0 ]]; then printf '%s\n' 'Usage: rag-start-quick [--help]' >&2; exit 2; fi
printf '%s\n' '+-- [BOOTSTRAP] Tools and Python --+' \
    'Requires uv and Docker; prepares locked local dependencies without starting a model.'
for tool in uv docker; do
    command -v "$tool" >/dev/null || { printf 'Install %s, then rerun rag-start-quick.\n' "$tool" >&2; exit 1; }
done
cd "$root"
printf '%s\n' 'Checking prerequisites: uv, Docker Engine, Docker Compose.'
docker info >/dev/null 2>&1 || { printf '%s\n' 'Docker Engine is unavailable. Start Docker/check access, then rerun rag-start-quick.' >&2; exit 1; }
docker compose version --short >/dev/null
printf '%s\n' '+-- [PYTHON] Prepare the local runner --+' 'Install locked dependencies; configuration is checked next. No model request is made.'
uv run --quiet --no-project --isolated --python 3.14 -- python -m scripts.stack.terminal "Install Python dependencies" -- uv sync --locked
exec .venv/bin/python -m scripts.stack.quickstart
