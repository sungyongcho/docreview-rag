# M9 Verification

## Offline gates

```bash
uv run pytest -o addopts="" tests/agent -q
uv run ruff check app/agent tests/agent
uv run ruff format --check app/agent tests/agent
```

Expected: `32 passed`, both ruff commands clean. The whole suite is deterministic — no network, no database, no API key.

## What the suite pins

- Contract exclusivity: answers, observations, and results cannot hold contradictory states (`test_01`).
- One schema, three consumers: registry specs are strict and closed, and the MCP tool list equals `registry.specs()` schema for schema (`test_02`, `test_07`).
- Provider neutrality: the deterministic queue and the OpenAI adapter produce the same turn shape with usage attached (`test_03`).
- Loop discipline: explicit observations for every failure class, evidence-gated citations with rejection-and-retry, fail-closed iteration and token budgets, typed provider failures (`test_04`).
- Tool thinness: built-in tools translate arguments to M2 filters and payloads to evidence ids, nothing more (`test_05`).
- Decomposition honesty: provider failure falls back to the single query, fusion is deterministic, and category slices exclude unscored absent cases (`test_06`).

## Live checks (optional)

```bash
docker compose up -d db
uv run python -m app.agent --question "How did NVIDIA's revenue change?" --provider deterministic
uv run python -m app.agent --question "How did NVIDIA's revenue change?" --provider openai --model gpt-5-mini
```

The deterministic run proves the loop against the real corpus without a key: one hybrid search executes and the final answer is an honest `NOT_IN_DOCS`. The OpenAI run requires `OPENAI_API_KEY` and returns a cited `SUPPORTED` answer or a typed failure; either way the printed JSON carries every step with tokens and latency.

A skipped or missing live check is an unverified environment, not a pass.
