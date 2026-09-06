# M5 Spec

This document is normative. Code, tests, CLI output, OpenAPI, and container behavior must preserve these contracts.

## 1. Serving boundaries

M5 provides one synchronous request path through three entrypoints:

```text
CLI or HTTP -> strict input -> M2 retrieval -> optional M4 workflow -> typed output
```

No worker queue or Redis service belongs to R1. The API awaits each operation and returns the terminal resource or typed failure.

## 2. HTTP resources

The application exposes:

| Method | Path | Resource |
|---|---|---|
| `GET` | `/health` | process liveness |
| `POST` | `/retrieve` | ranked cited evidence |
| `GET` | `/documents` | ingested filing collection |
| `POST` | `/ingest` | synchronous manifest ingestion |
| `POST` | `/review` | guarded M4 workflow run |
| `GET` | `/runs/{run_id}` | persisted run |
| `GET` | `/runs/{run_id}/traces` | ordered provider traces |
| `GET` | `/eval` | persisted evaluation resources |

Every request body is strict and forbids unknown fields. Validation uses a stable error envelope and never returns a traceback or submitted secret.

## 3. Evidence contract

Every CLI or HTTP retrieval hit exposes exactly these public fields:

```text
chunk_id, doc_id, item, kind, citation, start_char, end_char,
source_sha256, body, context_header, score
```

Spans are nonempty half-open intervals. Source hashes are lowercase hexadecimal SHA-256. `index_text` and component-native retrieval scores remain internal.

## 4. Runtime composition

`RuntimeApiServices` opens one `AsyncSession` per API request. Direct retrieval calls the M2 service with that session and defaults to deterministic embeddings unless a provider is explicitly injected. Review closes an M2 retriever over the same session, calls M4, ends any retrieval read transaction, then persists the run and traces atomically.

Ingest prepares and validates the entire local corpus before database work, bootstraps missing tables explicitly, then delegates to the M1 idempotent atomic upsert. It never changes the configured corpus implicitly at process start.

## 5. Provider and cost safety

CLI retrieval defaults to deterministic embeddings. Compose sets `EMBEDDING_PROVIDER=deterministic`. OpenAI embeddings require the explicit CLI provider option or external runtime configuration.

HTTP review requires an injected LLM provider and an explicit `ProviderBudget`. The default application refuses review with `503 provider_unavailable`; an ambient API key alone never enables spending.

## 6. Typed failures

| Failure | HTTP or CLI behavior |
|---|---|
| Blank query, zero `k`, malformed request | typed input failure |
| Missing or broken manifest | typed file/client failure |
| Database unavailable | `database_unavailable` without connection details |
| Provider unavailable | `provider_unavailable` without credentials |
| Unexpected route exception | non-leaking `internal_error` |
| Workflow budget exhaustion | structured run response with HTTP 429 |
| Workflow schema rejection | structured run response with HTTP 502 |

## 7. Runtime and container contract

`create_app()` performs no database query or provider call. `/health` is a process-liveness probe. Compose preserves the named PostgreSQL corpus volume, waits for PostgreSQL health, contains no Redis or worker service, and runs the application as a non-root user.

## 8. Acceptance contract

Canonical acceptance is deterministic and offline except for the loopback Uvicorn socket:

```bash
uv run pytest -o addopts="" tests/api -q
docker compose config --quiet
uv run python scripts/check_doc_code.py docs/en/m5-serving docs/ko/m5-serving
```

The full repository gate includes the existing optional live OpenAI skip. No M5 command may silently turn that skip into a live call.
