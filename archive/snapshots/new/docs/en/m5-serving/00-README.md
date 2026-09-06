# M5 Overview — typed serving

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

M5 turns the M2 retrieval service and M4 guarded workflow into three executable boundaries: strict HTTP resources, a deterministic CLI, and a container runtime. The default path is offline-safe: deterministic embeddings are the CLI and Compose default, and HTTP review refuses with a typed `503` until an LLM provider and explicit budget are injected.

## What M5 includes

| Step | Responsibility | Reference implementation |
|---|---|---|
| M5.1 | Strict request, response, error, and resource routes | `app/api/schemas.py`, `app/api/routes/` |
| M5.2 | Explicit CLI, import-safe application factory, container topology | `app/cli.py`, `app/main.py`, `Dockerfile`, `docker-compose.yml` |
| M5.3 | Database-backed M2/M4 composition and cross-surface proof | `app/api/runtime.py`, `tests/api/test_08_integration.py` |

## Reading order

1. [Measured findings](01-findings.md) explains the integration decisions. 2. [Normative specification](02-spec.md) freezes the serving contracts. 3. [Sortable build guide](03-build.md) proceeds from M5.1 to M5.3 with cumulative gates. 4. [Bugs and traps](04-bugs.md) records the failures that shaped the final code. 5. [Verification](05-verify.md) contains the exact offline acceptance sequence.

## Offline quick start

```bash
uv sync --group dev
docker compose up -d db
EMBEDDING_PROVIDER=deterministic uv run python -m app.cli retrieve --query "NVDA 2024 R&D" -k 3
uv run python -m app.cli serve --host 127.0.0.1 --port 8000
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/openapi.json
```

The retrieval command requires the existing populated loopback PostgreSQL corpus. It does not seed, mutate, or call a paid provider unless explicit options request that behavior.

## Completion checkpoint

```bash
uv run pytest -o addopts="" tests/api -q
uv run pytest -o addopts="" -q
```

Expected result for this source revision: `40 passed` for M5 and `691 passed, 1 skipped` for the repository. The skip is the explicitly opt-in live OpenAI workflow test; this M5 acceptance executed no paid or live provider call.
