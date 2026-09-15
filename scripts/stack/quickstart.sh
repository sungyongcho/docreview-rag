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
mode="${1:-dev}"
case "$mode" in
    dev|prod) if [[ $# -gt 0 ]]; then shift; fi ;;
    --help|-h) mode=dev ;;
    *) printf '%s\n' 'Expected dev or prod.' >&2; exit 2 ;;
esac
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
    printf '%s\n' "Usage: rag-${mode} start [--local] [--timeout SECONDS] [--verbose|-vv]" \
        'Prepare the selected local mode without deleting existing data.' \
        'Requires uv, Docker Engine, and Docker Compose 2.24.4+.' \
        'Order: prerequisites -> local .env -> Compose state/start -> schema -> server readiness.' \
        'Creates .env only when absent; edit the named settings locally and rerun this command.' \
        'Reports stopped, starting, unhealthy and already-running services for this checkout.' \
        'Prints application/tutorial URLs and the next data-preparation step after readiness.' \
        'Downloads Python dependencies and builds local containers.' \
        'Does not download filings, generate embeddings, or ask a model.'
    exit 0
fi
start_args=("$@")
while [[ $# -gt 0 ]]; do
    case "$1" in
        --local|--ready) shift ;;
        --artifacts)
            [[ $# -ge 2 && -n "$2" ]] || { printf '%s\n' 'Expected an artifact directory.' >&2; exit 2; }
            shift 2 ;;
        --timeout)
            [[ $# -ge 2 && "$2" =~ ^[0-9]+([.][0-9]+)?$ ]] || { printf '%s\n' 'Expected a positive timeout.' >&2; exit 2; }
            shift 2 ;;
        *) printf 'Unknown start option: %s\n' "$1" >&2; exit 2 ;;
    esac
done
printf '%s\n' '+-- [BOOTSTRAP] Tools and Python --+' \
    'Requires uv and Docker; prepares locked local dependencies without starting a model.'
for tool in uv docker; do
    command -v "$tool" >/dev/null || { printf 'Install %s, then rerun rag-%s start.\n' "$tool" "$mode" >&2; exit 1; }
done
cd "$root"
printf '%s\n' 'Checking prerequisites: uv, Docker Engine, Docker Compose.'
docker info >/dev/null 2>&1 || { printf 'Docker Engine is unavailable. Check access, then rerun rag-%s start.\n' "$mode" >&2; exit 1; }
docker compose version --short >/dev/null
printf '%s\n' '+-- [PYTHON] Prepare the local runner --+' 'Install locked dependencies; configuration is checked next. No model request is made.'
uv run --quiet --no-project --isolated --python 3.14 -- python -m scripts.stack.terminal "Install Python dependencies" -- uv sync --locked
exec .venv/bin/python -m scripts.stack.cli "$mode" start "${start_args[@]}"
