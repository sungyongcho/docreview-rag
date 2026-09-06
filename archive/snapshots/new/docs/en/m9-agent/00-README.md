# M9 — Tool-Calling Agent

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

Until M8 the system decides the route: retrieval runs, the fixed workflow grades and checks, and the caller gets one report. M9 hands the route to the model — under contracts. The agent chooses which tool to call, reads explicit observations, and may only finish with an answer that cites evidence its own run retrieved.

| Layer | Goal | Key files | Stop condition |
|---|---|---|---|
| M9.1 | Strict contracts and one tool registry | `types.py`, `tools.py`, `registry.py` | One schema feeds the LLM, MCP, and the prompt |
| M9.2 | Provider turns with usage accounting | `provider.py` | Every turn carries tokens, latency, and retries |
| M9.3 | Hand-rolled agent loop | `loop.py` | Uncited answers cannot leave the loop |
| M9.4 | Built-in filing tools | `builtin_tools.py` | Tools stay thin wrappers over M2 |
| M9.5 | Query decomposition and its measurement | `decompose.py`, `eval.py` | The claim is a category-sliced comparison, not prose |
| M9.6 | MCP server and CLI | `mcp_server.py`, `__main__.py` | External clients see the registry's exact schemas |

## Sortable checkpoint route

### M9.1 — Contracts and registry

- Prerequisite: M1–M8 complete; `uv run pytest tests/workflow -q` passes.
- Files: `app/agent/types.py`, `tools.py`, `registry.py`, `__init__.py`.
- Canonical command:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_01_contracts.py tests/agent/test_02_registry.py -q
  ```

- Expected result: `9 passed` with no network call.
- Stop condition: answers, observations, and results are mutually exclusive by construction, and the registry publishes strict closed schemas.

### M9.2 — Tool-calling providers

- Prerequisite: M9.1 is complete.
- Files: `app/agent/provider.py`.
- Canonical command:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_03_provider.py -q
  ```

- Expected result: `3 passed` with no network call.
- Stop condition: the deterministic queue and the OpenAI adapter return the same neutral turn shape with usage attached.

### M9.3 — The agent loop

- Prerequisite: M9.2 is complete.
- Files: `app/agent/loop.py`.
- Canonical command:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_04_loop.py -q
  ```

- Expected result: `8 passed` with no network call.
- Stop condition: every tool failure becomes an explicit observation, budgets fail closed, and final answers may cite only retrieved chunk ids.

### M9.4 — Built-in filing tools

- Prerequisite: M9.3 is complete.
- Files: `app/agent/builtin_tools.py`.
- Canonical command:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_05_builtin_tools.py -q
  ```

- Expected result: `3 passed` with no network call.
- Stop condition: search, chunk reading, and year comparison expose M2 retrieval without new retrieval logic.

### M9.5 — Decomposition and its measurement

- Prerequisite: M9.4 is complete.
- Files: `app/agent/decompose.py`, `app/agent/eval.py`.
- Canonical command:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_06_decompose.py -q
  ```

- Expected result: `5 passed` with no network call.
- Stop condition: the decomposed retriever plugs into the unmodified M3 harness and the comparison reports per-category deltas.

### M9.6 — MCP server and CLI

- Prerequisite: M9.5 is complete.
- Files: `app/agent/mcp_server.py`, `app/agent/__main__.py`.
- Canonical command:

  ```bash
  uv run pytest -o addopts="" tests/agent/test_07_mcp_cli.py -q
  ```

- Expected result: `4 passed` with no network call.
- Stop condition: MCP clients receive the registry's exact strict schemas and tool failures come back as typed error results.

## Offline quick start

```bash
uv run pytest -o addopts="" tests/agent -q
uv run ruff check app/agent tests/agent
uv run python -m app.agent --question "How did NVIDIA's revenue change?" --provider deterministic
```

The deterministic CLI run needs the seeded local PostgreSQL corpus from M2; it performs one real hybrid search and then answers `NOT_IN_DOCS` honestly, proving the loop without an API key.
