# M4 Findings

These findings describe the deterministic checkout and its offline tests. No paid provider request was executed.

## F1 — The locked environment has no compatible LangGraph installation

Both `pyproject.toml` and `uv.lock` omit LangGraph, and the active environment resolves `importlib.util.find_spec("langgraph")` to `None`. M4 therefore uses a typed equivalent runner instead of adding a speculative dependency.

The consequence is intentionally small: there is no LangGraph checkpoint or visualization API in R1. The benefit is that every transition is a direct Python function, the runner is fully offline-testable, and M5 can inject retrieval and provider dependencies without a framework adapter.

## F2 — Empty evidence never reaches the model

When retrieval returns zero chunks, `retrieve_node` adds `RetrievalEmpty`, the runner skips both `grade` and `check`, and `report_node` returns `NOT_IN_DOCS`. The observed node path is:

```text
retrieve -> report
```

The resulting run contains zero provider requests and zero trace rows. This removes the largest prompt-injection surface: a model is never asked to invent an answer without evidence.

## F3 — Citations are an executable allow-list

The checker may return syntactically valid chunk IDs that were never supplied or were graded irrelevant. Code intersects those IDs with the graded evidence set. Removed IDs create a `CitationsFiltered` reason; a `SUPPORTED` answer with no remaining citation is downgraded and adds `SupportedWithoutCitations`.

The final citation object exposes `chunk_id`, `doc_id`, human citation, half-open source span, and `source_sha256`. M5 therefore does not need to reconstruct evidence identity from answer text.

## F4 — Provider schema failures remain refusals

M4.1 validates strict JSON, feeds validation errors back once, and returns `schema_rejected` after a second failure. M4.3 maps that typed result into a `grade` or `check` trace, preserves final raw output and retry count, and stops without calling `report_node`.

No invalid object is converted into a fallback supported answer. A provider refusal, provider error, and retrieval exception also become typed terminal reports rather than uncaught application tracebacks.

## F5 — Workflow budgets accumulate across model calls

The only workflow budget check occurs immediately before each node. It reads the complete trace tuple, so grade usage is visible before check and check usage is visible before report. At exact equality the next node is refused because no capacity remains.

A deterministic acceptance test consumes the complete input-token allowance during grade. The observed result is `status="budget_exceeded"`, path `retrieve -> grade`, one preserved grade trace, and `blocked_node="check"`.

## F6 — Context limits drop whole evidence units

The workflow counts `index_text` characters in retrieval order and either retains a complete chunk or drops it. It never slices a chunk body, because partial evidence would detach the prompt from the stored citation span. Every drop creates `ContextTruncated` with exact chunk IDs and the configured character limit.

If all retrieved chunks are dropped, the run returns `NOT_IN_DOCS` without a model call. It does not fabricate a shortened context or hide the reason.

## F7 — Deterministic and paid checks are physically separate

The offline contract, node, runner, observability, and provider tests run under ordinary `pytest`. The live smoke test lives in `test_06_openai_live.py` and skips unless an explicit flag, model name, and credential are all present.

The current offline checkpoint is recorded in [verification](05-verify.md). The skipped live test is not counted as evidence of model access, answer quality, or a measured bill.
