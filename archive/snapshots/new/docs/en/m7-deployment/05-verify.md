# M7 Verification

Run these gates in order and stop at the first failure. All acceptance is offline with respect to model providers and external deployment accounts.

## 1. Release policy and integration

```bash
unset OPENAI_API_KEY DOCREVIEW_OPENAI_API_KEY RUN_LIVE_OPENAI_TEST
uv sync --locked --extra demo
uv run pytest -o addopts="" tests/release tests/demo tests/api -q
```

Measured focused result: `67 passed`. This includes 21 release tests, six demo tests, and 40 API tests. No database or provider network call is required.

## 2. Ruff and owned formatting

```bash
uv run ruff check --no-fix app tests scripts
uv run ruff format --check app/release app/demo.py tests/release
```

Expected result: lint passes globally and all M7-owned Python files are formatted.

## 3. Lock and Compose

```bash
uv lock --check
uv sync --locked --extra demo --dry-run
docker compose config --quiet
```

Expected result: the lock is current, sync would make no changes, and Compose resolves without rendering a provider key.

## 4. Local release app smoke

```bash
DOCREVIEW_MODE=canned uv run --extra demo uvicorn app.release.space:app --host 127.0.0.1 --port 7860 --workers 1 --log-level warning
```

From another terminal:

```bash
curl --fail --silent --show-error http://127.0.0.1:7860/health
curl --fail --silent --show-error http://127.0.0.1:7860/release
curl --fail --silent --show-error http://127.0.0.1:7860/
```

Expected result: health reports canned mode, release metadata reports `openai_enabled=false`, and the landing page is Gradio. Stop the server with `Ctrl-C`.

## 5. Container builds and smoke

```bash
docker compose build app
docker build --file deploy/huggingface/Dockerfile --tag docreview-m7-space:local .
docker run --rm --publish 127.0.0.1:7860:7860 --name docreview-m7-space-local docreview-m7-space:local
```

From another terminal:

```bash
curl --fail --silent --show-error http://127.0.0.1:7860/health
curl --fail --silent --show-error http://127.0.0.1:7860/
```

Expected result: both images build and the Space image returns canned health and UI. This is a local image proof, not an external Hugging Face deployment.

## 6. Full populated-repository regression

```bash
unset OPENAI_API_KEY DOCREVIEW_OPENAI_API_KEY RUN_LIVE_OPENAI_TEST
uv run pytest -o addopts="" -q
```

Measured result: `718 passed, 1 skipped` in 111.31 seconds. The skip is the explicitly opt-in live OpenAI workflow test. The value must come from this complete run, not predecessor arithmetic.

## 7. Documentation and language

```bash
uv run python scripts/check_doc_code.py README.md docs deploy/huggingface/README.md
uv run pytest -o addopts="" tests/test_doc_sync.py -q
git diff --check
```

Expected result: source blocks, prose constants, and relative links synchronize; the doc-sync test passes; no whitespace errors remain.

## 8. Temporary clean archive

```bash
scripts/verify_clean_checkout.sh
```

The script copies Git-selected source into a generated temporary directory, excludes ignored credentials/corpus/cache state, creates a fresh virtual environment, runs the 67 focused release/demo/API tests, lint, owned format, docs, and Compose validation, builds both images, and smokes canned health/UI on a random loopback port. It removes only its own exact temporary artifacts.

## 9. Credential-required path not executed

For an explicitly authorized local runtime review, supply the key without writing it to a file:

```bash
read -rsp "OpenAI API key: " OPENAI_API_KEY
printf '\n'
export OPENAI_API_KEY
export DOCREVIEW_MODE=runtime
uv run --extra demo uvicorn app.release.space:app --host 127.0.0.1 --port 7860 --workers 1 --log-level warning
unset OPENAI_API_KEY
```

This command was not run for M7 acceptance. It also requires a configured local database and corpus. Before authorization, recheck model access and the dated price configuration.

## M7 sign-off record

| Gate | Result |
|---|---|
| Focused release/demo/API | 67 passed |
| Full offline regression | 718 passed, 1 skipped in 111.31 seconds |
| Ruff and owned format | global lint passed; 14 owned files formatted |
| Documentation sync | 90 source blocks, 14 prose constants, and 369 links synchronized across 66 documents; 1 sync test passed |
| Lock and Compose | lock current; 83 installed packages unchanged; Compose config passed |
| Compose application image | local build passed |
| Hugging Face image and canned smoke | local build passed; canned health and Gradio UI passed |
| Temporary clean archive | fresh locked sync, 67 focused tests, lint/format/docs, both builds, and loopback smoke passed |
| Live provider calls | not run; explicit credentials and authorization required |
| External publish/account mutation | not run |
| Next milestone | M8 cross-lingual retrieval |
