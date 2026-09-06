# Failure analysis

This system treats failure visibility as part of the product. The correct outcome is often an inspectable refusal or `NOT_IN_DOCS`, not a fluent answer.

## Failure matrix

| Boundary | Failure | Detection | System behavior | Residual tradeoff |
|---|---|---|---|---|
| Source | Filing bytes change | stored SHA-256 differs | source-bound golden and chunk validation fail | legitimate source replacement requires deliberate re-ingestion and review |
| Ingestion | Section or table loses raw coordinates | span round-trip and corpus tests fail | do not persist the invalid batch | normalized table text is still a projection of HTML, not the original rendering |
| Backfill | Row changes during provider I/O | compare stored `index_text` before update | skip the stale row and report it | skipped rows need a later backfill pass |
| Retrieval | Query is blank or limits are invalid | strict service/CLI validation | typed input error; no database/provider work | caller must correct the request |
| Retrieval | Lexical query returns no candidates | component rankings and eval artifacts | vector candidates still pass through RRF | measured for the unrelaxed baseline and fixed in M2.4; the mode still exists for stop-word-only queries |
| Workflow | Retrieval is empty | empty hit tuple | return `NOT_IN_DOCS`; make zero model calls | cannot distinguish missing corpus coverage from a genuinely absent fact without corpus inspection |
| Workflow | Context budget is too small | whole-chunk accounting | drop complete chunks and record their IDs; refuse if none remain | partial but potentially useful evidence is excluded |
| Workflow | Model cites an unknown chunk | citation allow-list intersection | remove the ID and downgrade unsupported output | syntactic schema validity alone never proves grounding |
| Provider | Structured output is invalid twice | strict validation plus one repair | return `schema_rejected` with trace metadata | no best-effort answer is emitted |
| Budget | Cumulative tokens or cost reach the limit | pre-node guard reads prior traces | return `budget_exceeded` and retain completed traces | a nearly complete run may stop before report generation |
| Serving | PostgreSQL or provider is unavailable | typed dependency exception mapping | return a non-leaking `503` resource | availability is visible, but recovery remains operational work |
| Demo | Runtime service fails | typed `ApiProblemError` mapping | render unsupported state and zero attempted-call evidence | unexpected exception classes still require an integration fix |

## What the evaluation failed to prove

The recorded run passed all indexing and query-time budgets, but it did not establish production retrieval quality:

- Recall@5 peaked at `0.125` in that run; the follow-up ten-arm run peaked at `0.520833` on the BM25 lexical arm.
- Lexical retrieval returned no candidates for all 28 questions in both chunking arms of that run.
- Hybrid quality exactly matched vector quality and added latency; in the follow-up run hybrid trails plain lexical retrieval instead.
- The deterministic provider is a stable token-hash baseline, not a semantic embedding model.
- All 28 golden cases remain agent-curated and pending author approval.

The lexical failure mechanism was conjunctive matching of the retained terms from a full natural-language question: no single chunk contained every retained lexeme. The diagnosis was confirmed and fixed in M2.4, which relaxes the parsed conjunction to a disjunction and normalizes `ts_rank_cd` by extent distance and length; the [evaluation report](eval-report.md) records the re-measured matrix.

Decision: keep the run as reproducible pipeline evidence. Do not select the 500- or 1200-character arm, or vector versus hybrid retrieval, until golden review and a separately authorized semantic-provider experiment are complete.

## Portfolio-specific failure risks

### Synthetic demo evidence presented as corpus evidence

The default `CannedDemoService` returns an Acme filing, citation, character span, and hash created as deterministic UI fixtures. Acme is not one of the four tickers in the committed manifest. The demo proves supported/unsupported rendering and zero-cost trace display; it does not prove retrieval against the SEC corpus.

The runtime adapter is verified against the M5 domain return type, but the default launcher still selects `CannedDemoService`. Every capture of that default UI must visibly say **canned fixture**; only an explicitly injected runtime path may use a local-runtime label.

### The production retrieval shape is enforced at the demo join

`RuntimeDemoService` iterates `RetrievalResult.hits`, matching the production M5 runtime. The integration regression constructs the real `RetrievalResult` and explicitly confirms that no `results` attribute exists, so the historical fake shape can no longer make a broken join pass. This proves the injected local-runtime projection; it does not turn the default canned launch into a corpus-backed run.

### A passing UI with a failing evidence seam

Gradio can render a polished answer even if citation identity is missing. The focused demo tests therefore assert citation, span, hash-safe rendering, supported/unsupported contrast, injected runtime delegation, and typed service failure. The integration gate must stop if a presentation-only fallback bypasses these assertions.

### Stale screenshots and test totals

Screenshots and pass counts age independently from code. No screenshot is currently used as proof. The post-integration suite measured `697 passed, 1 skipped`; this was a complete rerun, not arithmetic based on the `691 passed, 1 skipped` predecessor.

## Legacy evidence disposition

The M6 build plan treated tracked `old/` files as migration evidence through M5 and required their removal only after their useful lessons were represented. The 22 tracked legacy files were removed after this reconciliation. The untracked `old/.env` was initially preserved as user data, then removed during the approved repository cleanup; `old/` is now absent and `scripts/` remains preserved.

| Legacy lesson | Current representation |
|---|---|
| synthetic evaluation could report perfect hit rate | the complete M3 matrix reports low, mixed metrics and rejects production selection |
| empty retrieval and prompt injection require guarded behavior | typed workflow refusal, citation allow-listing, and regression tests fail closed |
| unsupported evidence must not become a polished answer | CLI, API, and demo expose `NOT_IN_DOCS` or an unsupported state |
| unknown model pricing must not silently become zero | cost estimation fails closed until a known price and explicit budget are supplied |
| service, API, database, and Compose behavior need integration proof | current M5/M6 tests and Compose validation own those contracts |

Historical output that converted a partially supported result into a contradiction is kept only as a failure lesson; it is not promoted into a current product claim. Legacy fallback data was not ported because current typed boundaries prefer an inspectable refusal.

## Cost and secret boundary

Ordinary commands use deterministic embeddings and no LLM provider. A live workflow test requires explicit opt-in variables, and the runtime requires an injected LLM provider plus its budget. Secrets must not enter UI state, evidence cards, traces, or persisted reports.

Unknown pricing models fail closed rather than returning a zero estimate. Before any paid experiment, recheck current provider pricing, approve a ceiling, confirm model access, and write a separate artifact that names the provider and cost provenance.

## Failure triage order

1. Verify raw source hash and span identity. 2. Inspect vector and lexical component rankings independently. 3. Inspect typed workflow status, degradation reasons, and node path. 4. Inspect request/token/cost traces without exposing credentials. 5. Compare CLI, HTTP, and demo evidence projections. 6. Verify that the demo adapter consumes the production `RetrievalResult.hits` shape. 7. Only then investigate presentation or deployment behavior.

The complete measured matrix is in [eval-report.md](eval-report.md). Reproduction and stop conditions are in [M6 verification](m6-demo/05-verify.md).
