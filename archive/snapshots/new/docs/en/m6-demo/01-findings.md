# M6 Findings

These findings are grounded in the repository state and local acceptance evidence recorded on 2026-08-12. M6.1, M6.2, and the M6.3 integration join are complete.

## F1 — The optional Gradio surface is locked and runnable

The project declares the `demo` optional dependency and the lock resolves Gradio. A locked extra sync reported no changes. The focused demo suite produced `6 passed`, `build_demo()` constructed the UI, and a real loopback launch returned `http://127.0.0.1:7861/` before the server closed cleanly.

This proves that M6.1 is locally executable. It does not prove database connectivity, runtime-backed retrieval, or public hosting.

## F2 — The default demo is intentionally canned

`build_demo()` selects `CannedDemoService` when no service is injected. Its supported branch returns an Acme citation, span, hash, chunk ID, body, and a zero-cost trace. Its unsupported branch returns no evidence and `retrieval_empty`.

Acme does not occur in the committed manifest, whose 20 filings are evenly split across AMD, INTC, MU, and NVDA. The canned values are therefore synthetic UI fixtures. This gives the portfolio a deterministic offline path while imposing a strict labeling requirement.

## F3 — The runtime adapter preserves the M5 seam

The focused tests prove that `RuntimeDemoService` delegates through injected M5 services, passes typed filters, converts returned chunks into public evidence, and maps a typed `ApiProblemError` into a non-secret failure state. It does not discover credentials or open services while building the UI.

M6.3 closed the concrete return-shape gap: `RuntimeDemoService` reads `RetrievalResult.hits`, matching `RuntimeApiServices.retrieve()`. The focused integration regression constructs that actual domain return type and confirms it has no `results` attribute. The default launcher still selects canned mode; runtime labels require explicit service injection.

## F4 — The strongest project evidence is source lineage

The ingestion and retrieval boundaries preserve document ID, human citation, raw-source span, source SHA-256, chunk kind, and chunk ID. M4 filters model citations against retrieved and graded IDs. M5 projects the same identity through CLI and HTTP.

This is a stronger portfolio claim than raw answer fluency because it is deterministic and executable across layers.

## F5 — Evaluation quality is low and mixed

The source-bound golden suite contains 28 agent-curated cases: 24 positives and 4 absent cases. The two-by-three deterministic experiment measured:

| Chunk target | Best Recall@5 | Best MRR | Fastest strategy P95 |
|---:|---:|---:|---:|
| 500 | 0.125 | 0.070833 | 5.644 ms lexical, with zero hits |
| 1200 | 0.062500 | 0.083333 | 8.151 ms lexical, with zero hits |

Lexical search returned no candidates, so hybrid quality equaled vector quality and added latency. The experiment validates evaluation plumbing and latency budgets, not a production retrieval choice.

## F6 — Performance budgets passed

The isolated deterministic run indexed 12,984 chunks for the 500-character arm in 75.158 s and 9,172 chunks for the 1200-character arm in 63.881 s. Both were below 300 s. The fixed 200-query 1200-hybrid measurement took 12.994 s with 71.480 ms P95, below 90 s.

These are local environment measurements. They are not hosted-service latency guarantees.

## F7 — The post-M6 regression count is measured

The complete post-M6 suite produced `697 passed, 1 skipped`. The skip is the explicitly opt-in live OpenAI workflow test. This value came from a full rerun after the runtime join; it was not produced by adding the six demo tests to the `691` predecessor.

## F8 — No screenshot currently carries evidentiary weight

No image artifact is committed for M6. A text placeholder is deliberately labeled as such. This avoids presenting a stale or canned capture as proof of runtime integration. A future screenshot is optional evidence and must name its mode and correspond to a passing revision.
