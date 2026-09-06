# Canonical module route

> Unified navigation starts at [`docs/00-README.md`](../00-README.md). The Status column below is the single human-readable progress view; the machine-readable state is [`learning.toml`](learning.toml), and both are owned by `zero` — imports from `new` merge rows but preserve Status cells. Complete future code blocks remain in `docs/en/**` and `docs/ko/**` as implementation targets. At each step, create the documented canonical path directly; there is no parallel learner file. The documentation checker compares future blocks with pinned `reference_revision` without adding those files to `zero/app/`.

This is the visually sorted R1 learning and delivery route. Follow dependency arrows from left to right; do not start a step until every item in **Requires** is complete.

Status key: **Complete** = implemented and verified on `zero`; **In progress** = the checkpoint is underway; **Next** = start here; **Not started** = tutorial and tests are retained, but runtime implementation is absent.

Dependency spine:

- `M1.1 → M1.2 → M1.3 → M1.4 → M2.1 → M2.2 → M2.3 → M2.4`
- `M2.4 → M2.5 → M2.6 → M2.7 → M2.8 → M2.9 → M2.10 → M2.11 → M3.1 → (M3.2 + M3.3) → M3.4 → M3.5`
- `M3.4 → M4.1 → M4.2 → M4.3 → M4.4 → (M5.1 + M5.2) → M5.3 → M5.4`
- `M5.3 → (M6.1 + M6.2) → M6.3 → M7.1 → M7.2 → M7.3`
- `M7.3 → M8.1 → M8.2 → M8.3 → M8.4`
- `M8.4 → M9.1 → M9.2 → M9.3 → M9.4 → M9.5 → M9.6`

## M1 — Source-grounded ingestion

| Step | Outcome | Requires | Document | Status |
|---|---|---|---|---|
| M1.1 | 10-K HTML to Item sections | Start | [Parser](../en/m1-1-parser/00-README.md) | Complete |
| M1.2 | SEC HTML tables to markdown | M1.1 | [Tables](../en/m1-2-tables/00-README.md) | Complete |
| M1.3 | Sections to source-stable chunks | M1.1 + M1.2 | [Chunking](../en/m1-3-chunk/00-README.md) | Complete |
| M1.4 | Idempotent PostgreSQL seed | M1.3 | [Database seed](../en/m1-4-seed/00-README.md) | Complete |

## M2 — Deterministic hybrid retrieval

| Step | Outcome | Requires | Document | Status |
|---|---|---|---|---|
| M2.1 | Strict cited-hit and filter contracts | M1.4 | [Build step](../en/m2-retrieval/03-build.md#m21--make-evidence-impossible-to-blur) | Complete |
| M2.2 | Async embedding providers and resumable backfill | M2.1 | [Build step](../en/m2-retrieval/03-build.md#m22--separate-provider-io-from-persistence) | Complete |
| M2.3 | Exact pgvector cosine retrieval | M2.2 | [Build step](../en/m2-retrieval/03-build.md#m23--establish-exact-cosine-retrieval) | Complete |
| M2.4 | Safe PostgreSQL full-text retrieval | M2.3 | [Build step](../en/m2-retrieval/03-build.md#m24--add-a-safe-lexical-floor) | Complete |
| M2.5 | Rank-only reciprocal rank fusion | M2.4 | [Build step](../en/m2-retrieval/03-build.md#m25--fuse-positions-not-incompatible-scores) | Complete |
| M2.6 | Optional reranker boundary | M2.5 | [Build step](../en/m2-retrieval/03-build.md#m26--keep-reranking-optional) | Complete |
| M2.7 | One-session service and JSON CLI | M2.6 | [Build step](../en/m2-retrieval/03-build.md#m27--compose-one-production-request) | Complete |
| M2.8 | pgvector bootstrap and live PostgreSQL proof | M2.7 | [Build step](../en/m2-retrieval/03-build.md#m28--bootstrap-and-prove-postgresql-end-to-end) | Complete |
| M2.9 | Hand-written BM25 lexical ranking arm | M2.8 | [Spec section](../en/m2-retrieval/02-spec.md#15-deferred-bm25-lexical-ranking-arm) | Complete |
| M2.10 | Local sentence-transformer embedding provider | M2.9 | [Tutorial](../en/m2-retrieval/tutorial/08-local-embeddings.md) | Complete |
| M2.11 | Cross-encoder reranking provider and service wiring | M2.10 | [Tutorial](../en/m2-retrieval/tutorial/09-cross-encoder.md) | Complete |

## M3 — Retrieval evaluation

M3.2 and M3.3 branch after the golden contract, then reunite at M3.4. M3.5 grows the suite after M3.4; M4.1 requires only M3.4.

| Step | Outcome | Requires | Document | Status |
|---|---|---|---|---|
| M3.1 | Source-bound golden cases and loader | M2.8 | [M3 specification](../en/m3-evals/02-spec.md) | Complete |
| M3.2 | Span IoU and retrieval metrics | M3.1 | [M3 specification](../en/m3-evals/02-spec.md#8-deterministic-retrieval-scoring) | Complete |
| M3.3 | Stored baselines and regression guard | M3.1 | [M3 tutorial](../en/m3-evals/03-build.md#m33--regression-baselines) | Complete |
| M3.4 | Ablation runner, latency evidence, and report | M3.2 + M3.3 | [M3 tutorial](../en/m3-evals/00-README.md) | Complete |
| M3.5 | Gated golden curation and taxonomy breakdown | M3.4 | [M3 tutorial](../en/m3-evals/tutorial/09-golden-curation.md) | Complete |

## M4 — Evidence-checked workflow

The learning route is M4.1 schemas and providers, then M4.2 observability, then M4.3 workflow integration, then the M4.4 strict decoding boundary.

| Step | Outcome | Requires | Document | Status |
|---|---|---|---|---|
| M4.1 | LLM provider and fail-closed schemas | M3.4 | [M4 tutorial](../en/m4-workflow/03-build.md#m41--validate-before-workflow-code) | Complete |
| M4.2 | Trace persistence and budget guards | M4.1 | [M4 tutorial](../en/m4-workflow/03-build.md#m42--make-failure-observable-first) | Complete |
| M4.3 | Retrieve, grade, check, and report workflow | M4.2 | [M4 tutorial](../en/m4-workflow/00-README.md) | Complete |
| M4.4 | Strict structured decoding boundary | M4.3 | [M4 tutorial](../en/m4-workflow/tutorial/09-structured-outputs.md) | Complete |

## M5 — Typed serving surfaces

M5.1 and M5.2 can proceed together after M4.3; M5.3 joins them.

| Step | Outcome | Requires | Document | Status |
|---|---|---|---|---|
| M5.1 | Typed FastAPI resources | M4.3 | [M5 tutorial](../en/m5-serving/03-build.md#m51--typed-http-resources) | Complete |
| M5.2 | CLI, container, and runtime entrypoints | M4.3 | [M5 tutorial](../en/m5-serving/03-build.md#m52--deterministic-runtime-entrypoints) | Complete |
| M5.3 | Serving integration and smoke proof | M5.1 + M5.2 | [M5 tutorial](../en/m5-serving/00-README.md) | Complete |
| M5.4 | Server-sent-events run streaming | M5.3 | [M5 tutorial](../en/m5-serving/tutorial/06-streaming.md) | Complete |

## M6 — Portfolio surface

M6.1 and M6.2 can proceed together after M5.3; M6.3 joins them.

| Step | Outcome | Requires | Document | Status |
|---|---|---|---|---|
| M6.1 | Gradio evidence demo | M5.3 | [M6 tutorial](../en/m6-demo/03-build.md#m61--a-gradio-demo-that-shows-the-evidence) | Complete |
| M6.2 | Portfolio documentation and reports | M5.3 | [M6 tutorial](../en/m6-demo/03-build.md#m62--a-portfolio-is-an-evidence-map-not-a-technology-list) | Complete |
| M6.3 | Demo integration and legacy cleanup | M6.1 + M6.2 | [M6 tutorial](../en/m6-demo/03-build.md#m63--proving-the-demo-shows-the-real-thing) | Complete |

## M7 — Deployment-ready release

| Step | Outcome | Requires | Document | Status |
|---|---|---|---|---|
| M7.1 | Canned mode, rate limiting, and cost guards | M6.3 | [M7 tutorial](../en/m7-deployment/03-build.md#m71--canned-mode-rate-limiting-and-cost-guards) | Complete |
| M7.2 | Hugging Face Spaces and container release assets | M7.1 | [M7 tutorial](../en/m7-deployment/03-build.md#m72--hugging-face-and-container-release-assets) | Complete |
| M7.3 | Clean-checkout verification and honest release gate | M7.2 | [M7 tutorial](../en/m7-deployment/03-build.md#m73--clean-archive-verification-and-honest-release-gate) | Complete |

## M8 — Cross-lingual retrieval

| Step | Outcome | Requires | Document | Status |
|---|---|---|---|---|
| M8.1 | Korean twin golden suite over the same immutable spans | M7.3 | [M8 tutorial](../en/m8-crosslingual/03-build.md#m81--the-data-has-to-be-identical-before-the-metrics-can-differ) | Complete |
| M8.2 | Language-sliced measurement through the unmodified harness | M8.1 | [M8 tutorial](../en/m8-crosslingual/03-build.md#m82--measure-the-failure-before-owning-it) | Complete |
| M8.3 | Detection, routing, and translation entered as arms | M8.2 | [M8 tutorial](../en/m8-crosslingual/03-build.md#m83--two-ideas-two-arms-no-beliefs) | Complete |
| M8.4 | ko/en parity ratio, its gate, and one improvement cycle | M8.3 | [Verification](../en/m8-crosslingual/05-verify.md) | Complete |

## M9 — Tool-calling agent

| Step | Outcome | Requires | Document | Status |
|---|---|---|---|---|
| M9.1 | Strict agent contracts and one tool registry | M8.4 | [M9 tutorial](../en/m9-agent/03-build.md#m91--contracts-before-autonomy) | Complete |
| M9.2 | Provider turns with usage accounting | M9.1 | [M9 tutorial](../en/m9-agent/03-build.md#m92--a-turn-is-a-measured-unit) | Complete |
| M9.3 | Hand-rolled fail-closed agent loop | M9.2 | [M9 tutorial](../en/m9-agent/03-build.md#m93--the-loop-is-the-safety-boundary) | Complete |
| M9.4 | Built-in filing tools over M2 | M9.3 | [M9 tutorial](../en/m9-agent/03-build.md#m94--tools-stay-thin) | Complete |
| M9.5 | Query decomposition measured per category | M9.4 | [M9 tutorial](../en/m9-agent/03-build.md#m95--an-improvement-is-a-measured-delta) | Complete |
| M9.6 | MCP server and acceptance CLI | M9.5 | [M9 tutorial](../en/m9-agent/03-build.md#m96--one-contract-exposed-twice) | Complete |
