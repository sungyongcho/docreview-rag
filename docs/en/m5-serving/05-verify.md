# M5 Verification

Run the gates in dependency order and stop at the first failure. The reference path is offline-safe and never enables a provider from ambient credentials.

## 1. Dependency and lock gate

```bash
uv lock --check
uv run python -c "from importlib.metadata import version; print({name: version(name) for name in ('fastapi', 'starlette', 'httpx', 'uvicorn')})"
```

Expected locked versions for this acceptance: FastAPI 0.141.1, Starlette 0.52.1, HTTPX 0.28.1, and Uvicorn 0.52.1.

## 2. M5.1 HTTP contract

```bash
uv run pytest -o addopts="" tests/api/test_01_schemas.py tests/api/test_02_errors.py tests/api/test_03_resources.py tests/api/test_04_operations.py tests/api/test_05_routes.py -q
```

Expected result: `23 passed`.

## 3. M5.2 CLI and runtime contract

```bash
uv run pytest -o addopts="" tests/api/test_06_cli.py tests/api/test_07_runtime.py -q
uv run python -m app.cli --help
docker compose config --quiet
docker compose build app
```

Expected result: `14 passed`; help lists `retrieve`, `ingest`, and `serve`; Compose parses without Redis or worker services, and the locked non-root application image builds.

## 4. M5.3 integration contract

```bash
uv run pytest -o addopts="" tests/api/test_08_integration.py -q
uv run pytest -o addopts="" tests/api -q
```

Expected result: `3 passed`, then `40 passed`. The integration layer proves M2 retrieval, M4 review, run persistence, shared CLI/HTTP evidence, fail-closed review, liveness, and OpenAPI without database or provider I/O.

## 5. Local HTTP smoke

Start the runtime in one terminal:

```bash
EMBEDDING_PROVIDER=deterministic uv run python -m app.cli serve --host 127.0.0.1 --port 8000 --log-level warning
```

Probe it from another terminal:

```bash
curl --fail --silent --show-error http://127.0.0.1:8000/health
curl --fail --silent --show-error http://127.0.0.1:8000/openapi.json > /tmp/m5-openapi.json
uv run python -c "import json; data=json.load(open('/tmp/m5-openapi.json')); assert {'/health','/retrieve','/review'} <= set(data['paths'])"
```

Expected result: health returns `{"status":"ok"}` and OpenAPI contains the three asserted paths. This uses only a loopback socket and performs no provider or database request.

## 6. Optional local database smoke

This gate requires the existing populated corpus and is not part of provider acceptance:

```bash
docker compose up -d db
EMBEDDING_PROVIDER=deterministic uv run python -m app.cli retrieve --query "NVDA 2024 R&D" -k 3
curl --fail --silent --show-error -X POST http://127.0.0.1:8000/retrieve -H "Content-Type: application/json" -d '{"query":"NVDA 2024 R&D","k":3}'
```

Skip honestly when loopback PostgreSQL is unavailable or the corpus/schema is not current. Never interpret a skipped local database check as a passing retrieval smoke.

## 7. Full repository gate

```bash
uv run pytest -o addopts="" -q
uv run ruff check .
uv run ruff format --check app/api app/cli.py app/main.py tests/api
uv run python scripts/check_doc_code.py docs/en/m5-serving docs/ko/m5-serving
docker compose config --quiet
docker compose build app
git diff --check
```

Expected result: `691 passed, 1 skipped`, then clean static, documentation, configuration, and diff checks. The skip is `tests/workflow/test_06_openai_live.py`; its opt-in provider gate remained closed.

## 8. Canonical API gate

```bash
uv run pytest -o addopts="" tests/api -q
```

Tests import `app.api` directly. Missing symbols may skip during stepwise implementation; acceptance requires the complete focused suite.

## Failure triage

| Symptom | First boundary to inspect |
|---|---|
| CLI and HTTP evidence differ | `EvidenceHit.from_chunk_hit()` and `cli._evidence_payload()` |
| Domain routes always return 503 | default `RuntimeApiServices` injection in `create_app()` |
| Review calls a provider unexpectedly | runtime provider/budget constructor pair |
| Retrieval leaks a database URL | typed SQLAlchemy exception translation |
| Health fails without PostgreSQL | liveness route must not call services |
| Compose loses existing corpus | `pg_data` volume and `db` service |
| TestClient warning returns | Starlette constraint and lock resolution |
| Documentation source drifts | `scripts/check_doc_code.py` output |
