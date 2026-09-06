# M5 Findings

These findings describe the offline acceptance environment on 2026-08-12. No paid or live provider request was executed.

## F1 — The HTTP boundary must project evidence, not serialize domain internals

M2 `ChunkHit` contains `index_text` because search needs context plus evidence. The public HTTP evidence resource intentionally exposes body, context header, score, citation, chunk ID, source span, and source hash, but not the redundant internal index string.

Decision: `EvidenceHit.from_chunk_hit()` owns the public projection. The CLI uses the same projection, so CLI and HTTP cannot drift into different evidence contracts.

Regression: `test_cli_and_http_use_the_same_public_evidence_shape` compares the complete objects and proves `index_text` is absent.

## F2 — A router is not production composition

The first API lane correctly used dependency injection, but the module-level application had no database-backed services. Every domain route therefore returned a typed `503`; only tests with a fake service could succeed.

Decision: `RuntimeApiServices` implements the same protocol over a request-owned `AsyncSession`. Retrieval delegates to M2 with deterministic embeddings unless a provider is explicitly injected, review delegates to M4 and persists the resulting run, while reads map database rows back into strict API resources.

Regression: the M5.3 integration test observes the M2 retrieval call both directly and inside M4, the injected providers, one session per request, and run persistence.

## F3 — Review must not infer paid-call authorization from ambient credentials

An application process can inherit `OPENAI_API_KEY` for unrelated commands. Treating its presence as authorization would make `/review` capable of spending money unexpectedly.

Decision: production review requires both an injected `LLMProvider` and injected `ProviderBudget`. The default runtime returns a typed `provider_unavailable` `503`; health, OpenAPI, retrieval, documents, ingest, runs, traces, and eval remain wired.

Regression: `test_default_runtime_is_live_but_review_is_fail_closed_without_provider` proves liveness and refusal in the same process.

## F4 — Liveness and dependency readiness are different questions

The container needs a health probe that can succeed before the corpus is populated and without a provider call. A database query in `/health` would conflate process liveness with application readiness and cause restart loops during database maintenance.

Decision: `/health` proves that the ASGI process can answer HTTP. Domain endpoints expose typed `database_unavailable` or `provider_unavailable` failures when dependencies are not ready. Compose separately waits for PostgreSQL health before starting the application.

## F5 — The compatible TestClient stack required an explicit Starlette ceiling

Initial resolution selected FastAPI 0.141.1, Starlette 1.6.0, and HTTPX 0.28.1. Tests passed, but Starlette warned that plain HTTPX TestClient support was deprecated in favor of `httpx2`.

Decision: retain FastAPI 0.141.1 and HTTPX 0.28.1 while pinning `starlette<1`; the lock selects Starlette 0.52.1, inside FastAPI's declared compatibility range, without warning.

## F6 — Offline acceptance is complete; the local DB-backed retrieval curl is conditional

Measured verification produced `40 passed` for `tests/api` and `691 passed, 1 skipped` for the complete suite. Ruff, owned-file formatting, Compose parsing, the application image build, documentation sync, and the local Uvicorn health/OpenAPI curl smoke all passed.

The database-backed `/retrieve` smoke requires a running, schema-current, populated local PostgreSQL corpus. It is documented as a separate live-local gate and must not be reported as a provider or network acceptance test.
