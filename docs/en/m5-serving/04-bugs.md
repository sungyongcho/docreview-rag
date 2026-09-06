# M5 Bugs

## B1 — FastAPI tests passed but emitted a TestClient deprecation warning

- **Symptom:** the initial 14 runtime tests passed with a Starlette warning recommending `httpx2`.
- **Root cause:** unconstrained resolution selected Starlette 1.6.0, whose plain HTTPX compatibility path was already deprecated.
- **Fix:** constrain `starlette<1`; the lock selects Starlette 0.52.1 with FastAPI 0.141.1 and HTTPX 0.28.1.
- **Regression:** focused API tests must run with no TestClient warning.

## B2 — The module application had routes but no production services

- **Symptom:** `/health` and OpenAPI worked, but every domain resource returned `service_unavailable` unless a test injected `FakeApiServices`.
- **Root cause:** `create_app()` delegated to the M5.1 factory without installing a real `ApiServices` implementation.
- **Fix:** construct `RuntimeApiServices` by default and retain explicit injection for tests.
- **Regression:** M5.3 observes real M2/M4 call seams through the runtime adapter.

## B3 — CLI leaked a retrieval-internal field

- **Symptom:** HTTP returned `EvidenceHit`, while CLI serialized the complete `ChunkHit`, including `index_text`.
- **Root cause:** two output paths independently called different Pydantic serializers.
- **Fix:** both surfaces use `EvidenceHit.from_chunk_hit()`.
- **Regression:** compare the complete public objects and assert `index_text` is absent.

## B4 — Import-safe health was confused with database readiness

- **Symptom:** making health perform `SELECT 1` would mark the application unhealthy during database startup or maintenance, even though ASGI and error handling worked.
- **Root cause:** one endpoint attempted to answer both process liveness and dependency readiness.
- **Fix:** `/health` is liveness only; domain calls return typed dependency failures. Compose independently waits for database health.
- **Regression:** health passes with no database, while an unconfigured review returns a typed `503`.

## B5 — Ambient credentials could have become accidental authorization

- **Symptom:** a naive default OpenAI provider would make `/review` live whenever a shell or container inherited a key.
- **Root cause:** configuration availability was treated as human consent and budget approval.
- **Fix:** require injected LLM provider and injected provider budget together.
- **Regression:** the default runtime refuses review without making a provider request.

## B6 — The installed console script was unavailable in a no-install-project environment

- **Symptom:** `uv run docreview --help` could not spawn after dependency-only sync.
- **Root cause:** this source-tree project is intentionally not installed as a package in the container layer.
- **Fix:** use the deterministic module entrypoint `uv run python -m app.cli` everywhere.
- **Regression:** subprocess tests execute `python -m app.cli --help` and inspect all three commands.
