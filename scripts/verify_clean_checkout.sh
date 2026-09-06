#!/usr/bin/env bash
set -euo pipefail

M7_SOURCE_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
M7_TEMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/docreview-m7-clean.XXXXXX")
M7_ARCHIVE_ROOT="$M7_TEMP_ROOT/repository"
M7_FILE_LIST="$M7_TEMP_ROOT/files.list"
M7_PROJECT="docreview_m7_${$}"
M7_SPACE_IMAGE="docreview-m7-space:${$}"
M7_SPACE_CONTAINER="docreview-m7-space-${$}"

cleanup() {
    docker rm -f "$M7_SPACE_CONTAINER" >/dev/null 2>&1 || true
    if [[ -d "$M7_ARCHIVE_ROOT" ]]; then
        docker compose --project-directory "$M7_ARCHIVE_ROOT" \
            -p "$M7_PROJECT" down --volumes --remove-orphans --rmi local \
            >/dev/null 2>&1 || true
    fi
    docker image rm "$M7_SPACE_IMAGE" >/dev/null 2>&1 || true
    case "$M7_TEMP_ROOT" in
        "${TMPDIR:-/tmp}"/docreview-m7-clean.*) rm -rf -- "$M7_TEMP_ROOT" ;;
        *) printf 'Refusing to remove unexpected temporary path: %s\n' "$M7_TEMP_ROOT" >&2 ;;
    esac
}
trap cleanup EXIT INT TERM

mkdir -p "$M7_ARCHIVE_ROOT"
while IFS= read -r -d '' path; do
    if [[ -f "$M7_SOURCE_ROOT/$path" || -L "$M7_SOURCE_ROOT/$path" ]]; then
        printf '%s\0' "$path"
    fi
done < <(
    git -C "$M7_SOURCE_ROOT" ls-files --cached --others --exclude-standard -z
) > "$M7_FILE_LIST"

tar --null --create --file=- --directory="$M7_SOURCE_ROOT" \
    --files-from="$M7_FILE_LIST" | tar --extract --file=- --directory="$M7_ARCHIVE_ROOT"

cd "$M7_ARCHIVE_ROOT"
unset OPENAI_API_KEY DOCREVIEW_OPENAI_API_KEY
export DOCREVIEW_MODE=canned
export UV_PROJECT_ENVIRONMENT="$M7_ARCHIVE_ROOT/.venv"

printf 'Clean archive: fresh locked dependency sync\n'
uv sync --locked --extra demo

printf 'Clean archive: focused release, demo, and API tests\n'
uv run pytest -o addopts="" tests/release tests/demo tests/api -q

printf 'Clean archive: lint, owned format, and documentation format\n'
uv run ruff check --no-fix app tests scripts
uv run ruff format --check app/release app/demo.py tests/release
uv run pytest -o addopts="" tests/test_doc_format.py -q

printf 'Clean archive: Compose configuration and application image build\n'
docker compose -p "$M7_PROJECT" config --quiet
docker compose -p "$M7_PROJECT" build app

printf 'Clean archive: Hugging Face image build and canned local smoke\n'
docker build --file deploy/huggingface/Dockerfile --tag "$M7_SPACE_IMAGE" .
docker run --detach --name "$M7_SPACE_CONTAINER" \
    --publish 127.0.0.1::7860 "$M7_SPACE_IMAGE" >/dev/null

M7_PORT=$(docker port "$M7_SPACE_CONTAINER" 7860/tcp | tail -n 1 | sed 's/.*://')
for attempt in $(seq 1 45); do
    if M7_PORT="$M7_PORT" python - <<'PY'
import json
import os
import urllib.error
import urllib.request

port = os.environ["M7_PORT"]
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
        health = json.load(response)
except (OSError, TimeoutError, urllib.error.URLError):
    raise SystemExit(1) from None
if health != {"status": "ok", "mode": "canned"}:
    raise SystemExit(f"unexpected health response: {health}")
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
        body = response.read().decode("utf-8")
except (OSError, TimeoutError, urllib.error.URLError):
    raise SystemExit(1) from None
if "Document Review Evidence Demo" not in body:
    raise SystemExit("Gradio landing page marker is missing")
PY
    then
        printf 'Clean archive: canned health and Gradio smoke passed on port %s\n' "$M7_PORT"
        exit 0
    fi
    if [[ "$attempt" == "45" ]]; then
        docker logs "$M7_SPACE_CONTAINER" >&2 || true
        printf 'Container smoke timed out\n' >&2
        exit 1
    fi
    sleep 1
done
