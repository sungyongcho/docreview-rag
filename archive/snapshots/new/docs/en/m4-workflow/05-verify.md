# M4 Verification

Run acceptance in dependency order. Stop at the first failure; a higher layer cannot repair a lower contract.

## 1. Foundation tests

```bash
uv run pytest -o addopts="" tests/workflow/test_01_schemas.py tests/workflow/test_02_provider.py -q
uv run pytest -o addopts="" tests/workflow/test_03_observability.py -q
```

The first command validates strict schemas, repair, provider refusal, explicit call budgets, and offline OpenAI adapter mapping. The second validates trace/report accumulation, the one pre-node guard, Decimal cost estimates, secret-safe persistence mapping, and DB models.

## 2. Pure node tests

```bash
uv run pytest -o addopts="" tests/workflow/test_04_nodes.py -q
```

Required outcomes:

- empty retrieval produces typed absence;
- duplicate, quota-capped, and truncated evidence remains visible;
- unknown and missing grades are recorded;
- only relevant retrieved chunk IDs survive citation filtering;
- uncited support is downgraded; and
- reports expose complete machine citation identity.

## 3. Deterministic runner tests

```bash
uv run pytest -o addopts="" tests/workflow/test_05_runner.py -q
```

Required paths:

| Scenario | Status | Node path |
|---|---|---|
| Supported evidence | `ok` | `retrieve, grade, check, report` |
| Empty evidence | `ok` | `retrieve, report` |
| Irrelevant evidence | `ok` | `retrieve, grade, report` |
| Grade schema rejection | `schema_rejected` | `retrieve, grade` |
| Zero budget | `budget_exceeded` | empty |
| Grade consumes token cap | `budget_exceeded` | `retrieve, grade` |
| Retriever error | `error` | `retrieve` |

## 4. Complete offline workflow gate

```bash
uv run pytest -o addopts="" tests/workflow -q
```

Expected checkpoint for this source revision:

```text
78 passed, 1 skipped
```

The one skip is `test_06_openai_live.py`. It is expected and must not be rewritten as a pass.

## 5. Canonical package gate

The command in the previous section imports `app.llm`, `app.observability`, and `app.workflow` directly. Missing symbols may skip during stepwise implementation; acceptance requires the complete expected checkpoint.

## 6. Optional live provider gate

Do not run this during ordinary acceptance. It can make paid API calls and requires explicit human authorization, a valid key, and model access.

```bash
RUN_OPENAI_WORKFLOW_LIVE=1 OPENAI_WORKFLOW_MODEL="approved-model" OPENAI_API_KEY="your-key" uv run pytest -o addopts="" tests/workflow/test_06_openai_live.py -q
```

This task did not run the command. A skipped test proves only that the opt-in gate is closed.

## 7. Repository quality gate

```bash
uv run pytest -o addopts="" -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_doc_code.py
git diff --check
```

Record the exact full-suite count in the coordinator handoff. A live PostgreSQL test may skip only when its existing loopback availability guard says the database is unavailable; no paid provider test may run implicitly.

## 8. Contract-to-test map

| Contract | Primary proof |
|---|---|
| Strict model output and one repair | `test_01_schemas.py`, `test_02_provider.py` |
| Cumulative pre-node budget | `test_03_observability.py`, `test_05_runner.py` |
| No evidence means `NOT_IN_DOCS` | `test_04_nodes.py`, `test_05_runner.py` |
| Unknown citations removed | `test_04_nodes.py` |
| Uncited support downgraded | `test_04_nodes.py`, `test_05_runner.py` |
| Schema rejection preserves trace | `test_05_runner.py` |
| Persistence preserves prompt/raw output safely | `test_03_observability.py`, `test_05_runner.py` |
| Live calls require explicit consent | `test_06_openai_live.py` |

## Failure triage

| Symptom | Boundary | First action |
|---|---|---|
| Parsed invalid object | M4.1 schema/provider | inspect strict JSON parsing and repair count |
| Missing raw output | M4.2 trace mapping | inspect provider metadata before node transition |
| Model called with no evidence | M4.3 routing | inspect the post-retrieve short circuit |
| Fabricated citation survives | M4.3 check node | compare against `relevant_chunk_ids` |
| Budget resets between calls | M4.3 runner | inspect accumulated `steps` and remaining allowance |
| Partial cited body | M4.3 retrieve node | enforce whole-chunk context selection |
| Canonical package import fails | package layout | verify the documented exports in `app.llm` and `app.workflow` |
| Documentation drift | source markers | run the doc checker with `--fix`, then review the diff |
