# M4 Overview — evidence-checked workflow

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

M4 turns ranked filing chunks into a guarded answer without letting a model decide its own evidence rules. The implementation separates three boundaries:

1. `app.llm` owns strict structured output, one repair, and typed refusal; 2. `app.observability` owns cumulative budgets, raw traces, and persistence mapping; and 3. `app.workflow` owns pure state transitions and thin orchestration.

The path is `retrieve -> grade -> check -> report`. Empty or insufficient evidence skips unnecessary model calls and still produces a typed `NOT_IN_DOCS` report.

## Reading order

1. [Measured findings](01-findings.md) explains the decisions established in this checkout. 2. [Normative specification](02-spec.md) defines state, node, failure, and budget contracts. 3. [Build tutorial](03-build.md) follows the implementation in dependency order. 4. [Bug journal](04-bugs.md) records the traps and the code boundaries that prevent them. 5. [Verification](05-verify.md) maps every acceptance claim to an executable command.

## Layer route

| Layer | Goal | Main files | Stop condition |
|---|---|---|---|
| M4.1 | Fail-closed structured provider | `app/llm/` | Invalid output repairs once, then refuses |
| M4.2 | Trace and budget provenance | `app/observability/` | Exhaustion returns `budget_exceeded` |
| M4.3a | Strict state and reasons | `app/workflow/types.py` | Every degraded path has a typed reason |
| M4.3b | Pure node transitions | `app/workflow/nodes.py` | Citation guards are deterministic |
| M4.3c | Thin orchestration | `app/workflow/runner.py` | The full offline workflow suite passes |
| M4.4 | Strict decoding boundary | `app/llm/provider.py` | Schema-invalid shapes cannot be generated |

## Sortable checkpoint route

### M4.1 — Strict provider boundary

- Prerequisite: the source-bound retrieval contract from M3.4 is available.
- Files: `app/llm/`, `tests/workflow/test_01_schemas.py`, and `tests/workflow/test_02_provider.py`.
- Canonical command:

  ```bash
  uv run pytest -o addopts="" tests/workflow/test_01_schemas.py tests/workflow/test_02_provider.py -q
  ```

- Expected result: `31 passed` with no network call.
- Stop condition: invalid structured output is repaired at most once and then returned as a typed refusal with trace-ready metadata.
### M4.2 — Observable cumulative failure

- Prerequisite: M4.1 strict provider results are complete.
- Files: `app/observability/`, required DB run/trace models, and `tests/workflow/test_03_observability.py`.
- Canonical command:

  ```bash
  uv run pytest -o addopts="" tests/workflow/test_03_observability.py -q
  ```

- Expected result: `21 passed` with no network call.
- Stop condition: strict traces accumulate deterministically, zero or exhausted budgets return `budget_exceeded`, and persistence retains provenance without stored credentials.
### M4.3 — Evidence-checked workflow

- Prerequisite: M4.1 and M4.2 are complete.
- Files: `app/workflow/`, `tests/workflow/test_04_nodes.py`, and `tests/workflow/test_05_runner.py`.
- Canonical command:

  ```bash
  uv run pytest -o addopts="" tests/workflow/test_04_nodes.py tests/workflow/test_05_runner.py -q
  ```

- Expected result: `21 passed` with no network call.
- Stop condition: every reachable route returns a strict report or typed failure, fabricated citations cannot survive, and cumulative exhaustion preserves prior traces.
### M4.4 — Strict decoding boundary

- Prerequisite: M4.1 through M4.3 are complete.
- Files: `app/llm/provider.py`, `app/llm/__init__.py`, and `tests/workflow/test_07_structured_outputs.py`.
- Canonical command:

  ```bash
  uv run pytest -o addopts="" tests/workflow/test_02_provider.py tests/workflow/test_07_structured_outputs.py -q
  ```

- Expected result: `21 passed` with no network call.
- Stop condition: the default request carries a strict `text.format`, unsupported schema constructs fail at build time with a path, and the validate-repair loop still guards both request paths.
## Offline quick start

```bash
uv run pytest -o addopts="" tests/workflow -q
uv run ruff check app/llm app/observability app/workflow tests/workflow
uv run ruff format --check app/llm app/observability app/workflow tests/workflow
uv run python scripts/check_doc_code.py docs/en/m4-workflow docs/ko/m4-workflow
```

No command above calls a paid service. The live OpenAI smoke test requires three explicit environment variables and is documented as a separate manual gate in [verification](05-verify.md#6-optional-live-provider-gate).

## Why no LangGraph dependency

The locked environment does not contain `langgraph`. Adding a new orchestration dependency would increase the runtime and tutorial surface without changing the four-state path, so M4 uses an equivalent typed async runner. The runner contains only sequencing, dependency calls, and one pre-node guard; the state transformations remain ordinary pure functions.

This is a deliberate local compatibility decision, not a claim that LangGraph is generally unsuitable. If the dependency is introduced later, the four pure node functions are the stable migration boundary.

## Completion meaning

Machine completion proves deterministic schema handling, evidence filtering, citation identity, cumulative token refusal, trace preservation, direct canonical imports, and documentation synchronization. It does not prove the quality of a live model, authorize paid calls, or replace review of the underlying retrieval quality measured in M3.
