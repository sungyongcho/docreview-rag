# M4 Bugs

This file records implementation traps and the narrow fix for each. It is not a list of speculative future features.

## B01 — Treating an absent graph library as an implicit optional path

**Symptom:** local code examples assume LangGraph, while the lockfile and runtime contain no such module.

**Root cause:** architecture prose named a framework before dependency compatibility was checked.

**Fix:** use one typed deterministic runner and document the missing framework surface. Pure node functions remain the migration boundary if a later milestone justifies the dependency.

**Regression check:**

```bash
uv run python -c 'import importlib.util; assert importlib.util.find_spec("langgraph") is None'
```

## B02 — Trusting syntactically valid citations

**Symptom:** a strict `AnswerDecision` can still cite chunk `999` because positive integers are schema-valid.

**Root cause:** JSON validation proves shape, not membership in retrieved evidence.

**Fix:** intersect citations with grade-approved chunk IDs, record removed IDs, and downgrade support when the intersection is empty.

**Regression check:**

```bash
uv run pytest -o addopts="" tests/workflow/test_04_nodes.py -k "citation" -q
uv run pytest -o addopts="" tests/workflow/test_05_runner.py -k "fabricated" -q
```

## B03 — Letting missing grades pass silently

**Symptom:** the grader returns one valid grade for a multi-chunk prompt and the omitted chunks disappear from the decision history.

**Root cause:** `RelevanceJudgment` guarantees unique IDs but cannot know the expected set.

**Fix:** compare returned IDs with supplied evidence IDs. Unknown IDs create `GradeReferencesFiltered`; omitted IDs create `GradeCoverageIncomplete` and count as not relevant.

**Regression check:**

```bash
uv run pytest -o addopts="" tests/workflow/test_04_nodes.py -k "coverage" -q
```

## B04 — Resetting workflow budget at each provider call

**Symptom:** grade and check each pass an individual limit even though their sum exceeds the run limit.

**Root cause:** provider budgets and workflow budgets solve different boundaries. Reusing the original provider allowance ignores prior traces.

**Fix:** the pre-node guard reads cumulative traces, and each provider call receives an allowance reduced by prior token and estimated-cost use.

**Regression check:**

```bash
uv run pytest -o addopts="" tests/workflow/test_05_runner.py -k "cumulative" -q
```

## B05 — Truncating inside a cited chunk

**Symptom:** the prompt contains a body fragment while the final citation points to the complete stored span.

**Root cause:** character-budget code slices strings instead of selecting evidence units.

**Fix:** retain or drop each complete `index_text` value. Record every dropped chunk ID and never construct a synthetic partial citation.

**Regression check:**

```bash
uv run pytest -o addopts="" tests/workflow/test_04_nodes.py -k "context_limit" -q
```

## B06 — Catching a provider failure but losing raw output

**Symptom:** a run says `schema_rejected`, but there is no inspectable model output or retry count.

**Root cause:** the workflow maps only parsed data and discards provider metadata on failure.

**Fix:** convert every provider result to `StepTrace` before applying the node transition. Terminal reports retain the trace tuple and typed refusal.

**Regression check:**

```bash
uv run pytest -o addopts="" tests/workflow/test_05_runner.py -k "schema_rejection" -q
```

## B07 — Calling a paid test during ordinary acceptance

**Symptom:** a developer with a configured key runs the normal suite and incurs an unintended request.

**Root cause:** credential presence alone is treated as consent.

**Fix:** the live test requires `RUN_OPENAI_WORKFLOW_LIVE=1`, an explicit model, and a key. Normal deterministic acceptance supplies none of them.
