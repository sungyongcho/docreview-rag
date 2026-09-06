# M4 Spec

## 1. Scope

M4 consumes M2 `ChunkHit` values and returns an M4.2 `RunReport`. It owns no database transaction, HTTP route, UI state, or provider credential. Those boundaries remain with the caller.

The workflow contains four named nodes:

```text
retrieve -> grade -> check -> report
```

`grade` and `check` are the only LLM boundaries. `retrieve` calls an injected M2 retriever, and `report` is deterministic projection.

## 2. Strict request and state

`WorkflowRequest` requires a stable run ID, nonblank query, positive `k`, exact retrieval filters, workflow budget, provider budget, nonnegative context-character limit, and complete system prompt. Unknown fields and scalar coercion are rejected.

`WorkflowState` is frozen. Transitions return a new value containing immutable tuples for hits, evidence, relevant chunk IDs, reasons, node path, and traces. Pure nodes do not perform I/O, read environment variables, call time, or mutate an input state.

## 3. Typed degradation reasons

Every non-happy path uses one of these discriminated values:

| Code | Meaning |
|---|---|
| `retrieval_empty` | No chunks were returned |
| `duplicate_retrieved_chunks` | Duplicate chunk identities were removed |
| `duplicate_evidence_text` | Distinct chunk identities carrying the same body were collapsed |
| `document_quota_applied` | Hits beyond one document's share of the slots were dropped |
| `context_truncated` | Complete chunks exceeded the context limit |
| `grade_references_filtered` | The grader named an unknown chunk |
| `grade_coverage_incomplete` | The grader omitted a supplied chunk |
| `relevance_below_threshold` | No valid chunk was graded relevant |
| `citations_filtered` | The checker cited evidence outside the relevant set |
| `supported_without_citations` | A supported answer lost every valid citation |
| `provider_failure` | A typed provider refusal stopped grade or check |
| `node_error` | A non-provider dependency raised before returning typed data |

Reasons are serialized into the final report or terminal failure object. Silent dropping is not permitted.

## 4. Retrieve contract

The injected retriever accepts `(query, k, filters)` and returns either `RetrievalResult` or a sequence of `ChunkHit`. Results retain retrieval order. The workflow asks for `evidence_overfetch` times as many hits as the `k` it will keep, because every selection pass below only removes hits while retrieval truncates to whatever it was asked for.

Selection then narrows that list in four ordered passes. Duplicate chunk IDs keep the first hit and record the removed identity. Distinct chunk IDs whose `body` matches after whitespace normalization also keep the first hit, and record which identity absorbed which. One `doc_id` contributes at most `max_hits_per_document` hits. The survivors are cut to `k`.

Context selection counts complete `index_text` values plus separators. A chunk is included only when the full value fits. Dropped chunks remain in `retrieved_hits` for provenance but are absent from `evidence` and cannot be graded or cited.

Zero effective evidence routes directly to report and returns `NOT_IN_DOCS`.

## 5. Grade contract

The grade prompt contains the query and deterministic JSON evidence. Evidence is labeled as untrusted data. The provider must return one unique `ChunkRelevance` per supplied chunk.

Unknown grade IDs are removed, missing IDs are treated as not relevant, and both cases are recorded. The minimum relevant count is one. Falling below it routes directly to report and does not call check.

## 6. Check and citation contract

The check prompt contains only chunks that survived grade. `AnswerDecision` first enforces the label shape: supported decisions require at least one syntactic citation, while `NOT_IN_DOCS` forbids citations and requires the exact absence answer.

Workflow code then enforces semantic citation membership:

1. intersect requested IDs with graded evidence IDs; 2. record every removed ID; 3. preserve valid IDs in model-return order; and 4. downgrade `SUPPORTED` to `NOT_IN_DOCS` when no valid ID remains.

The final report builds citation metadata from stored `ChunkHit` values, never from model text.

## 7. Provider failure contract

M4.1 performs strict validation, one repair, and typed refusal. M4.3 maps statuses as follows:

| Provider status | Run status |
|---|---|
| `schema_rejected` | `schema_rejected` |
| `budget_exceeded` | `budget_exceeded` |
| `provider_refused` | `error` |
| `provider_error` | `error` |

The provider metadata always becomes a `StepTrace`, including final raw output, token totals, latency, retries, model, and API URL. A failure stops immediately and does not create a fake answer report.

## 8. Cumulative budget contract

The single enforcement function is `pre_node_budget_guard`. The runner calls it immediately before every node using accumulated `node_path` and `steps`. It checks iterations, input tokens, output tokens, and elapsed wall time in that stable order.

Equality refuses entry. A zero limit is valid and deterministically blocks the first node. Negative, nonfinite, boolean, or coerced limits are schema errors.

Provider-call budgets are reduced by prior workflow usage. The provider boundary can therefore return a typed overage for a response that crosses the remaining allowance, while the next pre-node check catches capacity exhausted by a successful prior call.

## 9. Persistence contract

The runner returns `RunReport` and never commits a transaction. Callers pass that value to `report_to_records` or `persist_run_report`. System prompt, raw output, node path, counters, structured answer, and typed failure remain present; recognizable and caller-supplied secret values are redacted only at the persistence boundary.

## 10. Framework compatibility

The locked environment has no LangGraph dependency. The R1 implementation uses an equivalent typed async runner. Its sequencing is intentionally thin, and the pure node functions are compatible migration units if LangGraph is introduced after a measured need.

No code may conditionally import LangGraph or silently choose different execution semantics based on the environment.

## 11. Canonical test path

Workflow tests import `app.llm`, `app.observability`, and `app.workflow` directly. Create and edit those canonical packages in milestone order, then run the complete workflow suite:

```bash
uv run pytest -o addopts="" tests/workflow -q
```

Missing symbols may skip dependent tests during implementation. A skip is a progress marker, not acceptance evidence.

## 12. Completion gate

M4 is machine-complete when deterministic workflow tests, the full repository suite, Ruff, format checks, documentation synchronization, and diff hygiene pass. The optional live test must remain skipped unless a human explicitly supplies the paid-call flag, model, and key.
