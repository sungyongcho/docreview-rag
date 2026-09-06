# M7.3 Tutorial 4 — Filtering out "it works on my machine"

Every test so far has passed. But it passed **in my working tree.**

A developer machine quietly hides a great deal.

| What hides | What happens to someone else |
|---|---|
| files never committed to Git | the clone lacks them and imports fail |
| local packages diverging from the lock file | dependency resolution differs |
| secrets in a `.gitignore`d `.env` | configuration is empty and startup fails |
| an already-running DB container | starting from scratch, the ordering does not hold |
| cached build artifacts | a clean build fails |

Those surface **only in CI.** And for a portfolio, they surface even earlier — on the machine of whoever received the link.

M7.3's method is simple and reliable. **Copy only Git-tracked files plus intentional untracked ones** into a temporary archive and rerun every release gate in a fresh virtual environment. Provider credentials are explicitly unset.

A failure here is a real problem. A pass earns the right to say "clone it and it runs."

**Prerequisite:** Tutorial 3's `uv run pytest tests/release/test_05_assets.py -q` passes.

### What this script does *not* prove

There is an important limitation. File collection runs like this.

```text
git ls-files --cached --others --exclude-standard
```

`--others` is present, so **untracked non-ignored files are included too.** Despite the name, this is not a true clean-checkout verification built from the current commit alone.

If `app/config.py` and `app/db/` are untracked right now, they enter the archive as well. So a passing run **is not proof that the HEAD commit itself is complete.** Claiming commit completeness requires separately confirming that the working tree is clean.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| File collection | **Review the design decision** | What is included and what is not |
| Credential unsetting | **Implement** the isolation yourself | Confirming it runs without secrets |
| Gate execution | **Define the structure, then inspect call order** | Running the cheap checks first |
| `trap` cleanup | **Implement** the cleanup scope yourself | Removing only what this run created |

### 1. The clean-source verifier

#### Create `scripts/verify_clean_checkout.sh` — clean-checkout verification

**Learning action — define the structure, then inspect call order:** decide the gate order yourself. Then note what the `trap` removes and what it leaves alone.

<!-- file: scripts/verify_clean_checkout.sh -->
```bash
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

printf 'Clean archive: lint, owned format, and documentation sync\n'
uv run ruff check --no-fix app tests scripts
uv run ruff format --check app/release app/demo.py tests/release
uv run python scripts/check_doc_code.py README.md docs deploy/huggingface/README.md
uv run python scripts/check_doc_parity.py inventory
uv run python scripts/check_doc_parity.py parity
uv run python scripts/check_doc_parity.py language
uv run pytest -o addopts="" tests/test_doc_sync.py tests/test_doc_parity.py -q

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
```

**What to look for in the code**

- `set -euo pipefail` is the first line. A failure slipping by silently would make the verification itself meaningless.
- Credentials are `unset`. The purpose is verifying it **runs without secrets**, so a key present in your shell must not leak in.
- Gates run cheapest first — dependency setup, ruff, tests, then image builds. A Docker build is the most expensive, so it comes last.
- The `trap` removes **only what this run created**: the named container and images, and the temporary archive. Pre-existing containers are untouched.
- The smoke test connects on loopback only. Nothing is exposed externally.

### Focused tests and the contracts they protect

This script is not a documentation check. It changes Docker and temporary-file state.

```bash
uv run pytest tests/release -q
```

| Value the test breaks | Contract being protected |
|---|---|
| An uncommitted source file | Whoever clones receives the same thing. |
| A dependency diverging from the lock file | Dependency resolution reproduces. |
| An API key left in the shell | It starts without secrets. |
| A container left by a previous run | Cleanup stays scoped to this run. |

### What you should be able to explain now

- **What are the five failures a developer machine hides?**
  - **Answer:** It can hide uncommitted files, packages that differ from the lock file, secrets from an ignored `.env`, an already-running database, and cached build artifacts. A fresh environment removes all five accidental supports.
- **What does `--others` keep this script from proving?**
  - **Answer:** It includes non-ignored untracked files in the archive. A pass therefore does not prove that the HEAD commit alone is complete; that requires a separate clean-working-tree check.
- **Why are credentials `unset`?**
  - **Answer:** It prevents inherited shell state from contaminating the check and proves that canned-mode startup does not depend on secrets. Canned mode is forced separately, so removing credentials is not what selects that mode.
- **Why do the gates run cheapest first?**
  - **Answer:** Fast dependency, lint, and test failures should stop the run before expensive image builds begin. This preserves the same result while shortening the feedback loop and avoiding wasted work.
- **Why must the `trap`'s removal scope be limited?**
  - **Answer:** Cleanup runs automatically on success, failure, and interruption, so a broad target could delete containers, images, or directories that predated the check. It must remove only the explicitly named resources and validated temporary path created by this run.

---

[← Previous: Container](03-container.md) · [Module overview](../03-build.md)
