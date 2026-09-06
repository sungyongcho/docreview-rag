# M6 Verification

Run gates in dependency order and stop at the first failure. All M6 acceptance is offline-safe; a screenshot is optional and cannot replace executable evidence.

## 1. Locked demo dependency

```bash
uv sync --locked --extra demo --dry-run
uv run --extra demo python -c "from importlib.metadata import version; print(version('gradio'))"
```

Expected result: locked resolution succeeds without changes and prints the installed Gradio version. Do not install an ad hoc package to make this gate pass.

## 2. M6.1 focused contract

```bash
uv run pytest -o addopts="" tests/demo -q
```

Measured M6.1 result: `6 passed`. The tests cover supported and unsupported canned behavior, safe rendering, injected services, runtime query delegation, filters, and typed fail-closed service errors.

## 3. M6.1 real loopback launch and close

```bash
uv run --extra demo python - <<'PY'
from app.demo import build_demo

demo = build_demo()
_, local_url, _ = demo.launch(
    server_name="127.0.0.1",
    server_port=7861,
    prevent_thread_lock=True,
    quiet=True,
)
print(local_url)
demo.close()
PY
```

Measured result: `http://127.0.0.1:7861/` was returned and the server closed cleanly. This proves local UI launch; the actual `RetrievalResult` regression separately proves the injected runtime adapter contract.

## 4. M6.2 documentation and links

```bash
make docs
git diff --check
```

Expected result: source-anchored blocks, prose constants, and relative links synchronize; `tests/test_doc_sync.py` reports `1 passed`; tracked diffs have no whitespace errors.

## 5. Canned-mode disclosure

```bash
rg -n "canned fixture|synthetic|not evidence|placeholder" README.md docs/en/m6-demo docs/ko/m6-demo docs/en/failure-analysis.md docs/ko/failure-analysis.md
```

Expected result: the root landing page and M6 documents explicitly separate synthetic Acme fixtures from the committed SEC corpus and label screenshot placeholders as non-evidence.

## 6. Real local corpus surfaces

This optional local gate requires Docker and may mutate only the local database:

```bash
docker compose up -d db
uv run python -m app.cli ingest --manifest data/corpus/manifest.json --create-schema
uv run python -m app.cli retrieve --query "NVDA 2024 R&D" --provider deterministic --embed-missing -k 3
EMBEDDING_PROVIDER=deterministic uv run python -m app.cli serve --host 127.0.0.1 --port 8000 --log-level warning
```

From another terminal:

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health
curl --fail --silent --show-error http://127.0.0.1:8000/openapi.json
```

Expected result: ingestion reports the manifest result, retrieval emits cited JSON evidence, health returns `{"status":"ok"}`, and OpenAPI is available. Skipping this gate is not a passing runtime/demo integration result.

## 7. M6.3 final repository gate

```bash
uv run pytest -o addopts="" tests/demo -q
uv run pytest -o addopts="" tests/demo tests/api/test_08_integration.py -q
uv run pytest -o addopts="" -q
uv run ruff check --no-fix app tests scripts
uv run python scripts/check_doc_code.py README.md docs deploy/huggingface/README.md
git diff --check
```

Measured result: the cross-surface integration reports `9 passed`, the full suite reports `697 passed, 1 skipped`, and every command passes. The live-provider test is the only skip. The full count was measured directly rather than derived from the M5.3 predecessor.

## 8. Canonical presentation gate

Use the focused presentation contract and tutorial synchronization as the direct progress gate:

```bash
uv run pytest -o addopts="" tests/demo -q
uv run python scripts/check_doc_code.py docs/en/m6-demo docs/ko/m6-demo
```

## 9. Screenshot release gate

Before replacing the text placeholder:

```bash
rg -n "canned fixture|local runtime retrieval|local runtime review" README.md docs/en/m6-demo docs/ko/m6-demo
uv run pytest -o addopts="" tests/demo -q
```

Expected result: the selected mode label is documented and the focused suite passes on the same revision. Inspect the capture manually for query, citation, source span, hash, chunk ID, trace/cost state, and absence of secrets.

## M6 sign-off record

| Gate | Result |
|---|---|
| Optional dependency and lock | present; locked dry run succeeds |
| Compose configuration | `docker compose config --quiet` passes |
| Focused M6.1 suite | 6 passed |
| Gradio build and loopback | built; launched and closed on `127.0.0.1:7861` |
| Runtime return-type join | actual `RetrievalResult.hits` regression; focused demo+API integration 9 passed |
| Portfolio documents | complete six-document set plus architecture/evaluation/failure reports |
| Documentation sync | 90 source blocks, 14 prose constants, and 353 links synchronized across 60 documents; doc-sync test 1 passed |
| Full regression | 697 passed, 1 skipped |
| Legacy cleanup | 22 tracked `old/` files removed; `old/.env` retained at M6, then removed during approved cleanup; `scripts/` preserved |
| Final screenshot | intentionally absent; placeholder is explicitly not evidence |
| Next milestone | M7 deployment-ready release |
