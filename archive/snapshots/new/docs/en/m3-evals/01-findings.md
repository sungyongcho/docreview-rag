# M3 Findings

These findings describe the committed `20260812T200916Z` run only. The run used 384- dimension deterministic token-hash vectors, isolated temporary PostgreSQL tables, exact pgvector search, PostgreSQL full-text search, and rank-only hybrid fusion. It made no paid API call and left the populated 9,172 embeddings unchanged.

## F1 — The suite is source-grounded but not author-approved

The strict loader validates 28 cases: 24 source-bearing positives and four absent cases. All 24 positives cite the immutable raw filing with `doc_id`, `source_sha256`, and a half-open character interval. Every case remains:

```text
curation_status=agent-curated
approval_status=pending-author-approval
human_verified=false
```

Passing schema, hash, bounds, distribution, and evidence checks establishes machine consistency only. Author review is still required before the cases can be called verified.

## F2 — One golden identity works across both chunking arms

The experiment re-chunked the same 20 filings with `target_text_chars=500` and `1200`. Golden data was not rewritten. Relevance matched each retrieved chunk against the stable raw-source hash and span, so the two arms remained comparable even though they produced 12,984 and 9,172 chunks respectively.

## F3 — The deterministic comparison is weak and mixed

| Chunk target | Retrieval | Recall@5 | Hit Rate@5 | MRR | P95 ms | Raw evidence |
|---:|---|---:|---:|---:|---:|---|
| 500 | lexical | 0.000000 | 0.000000 | 0.000000 | 5.644 | [JSON](../../../data/eval_runs/20260812T200916Z-structure-500-lexical.json) |
| 500 | vector | 0.125000 | 0.125000 | 0.070833 | 81.242 | [JSON](../../../data/eval_runs/20260812T200916Z-structure-500-vector.json) |
| 500 | hybrid | 0.125000 | 0.125000 | 0.070833 | 99.614 | [JSON](../../../data/eval_runs/20260812T200916Z-structure-500-hybrid.json) |
| 1200 | lexical | 0.000000 | 0.000000 | 0.000000 | 8.151 | [JSON](../../../data/eval_runs/20260812T200916Z-structure-1200-lexical.json) |
| 1200 | vector | 0.062500 | 0.083333 | 0.083333 | 59.101 | [JSON](../../../data/eval_runs/20260812T200916Z-structure-1200-vector.json) |
| 1200 | hybrid | 0.062500 | 0.083333 | 0.083333 | 79.185 | [JSON](../../../data/eval_runs/20260812T200916Z-structure-1200-hybrid.json) |

The 500-character arm measured higher Recall@5 and Hit Rate@5, while the 1200-character arm measured higher MRR. Hybrid quality equaled vector quality because the lexical component returned no candidates for these full natural-language questions. The metrics are too low and the directions too mixed to select a production winner.

## F4 — Raw natural-language questions over-constrained the lexical baseline

All 28 lexical case records contain empty hit lists in both chunking arms. A representative question parsed to this PostgreSQL query:

```text
'amd' & 'gross' & 'margin' & 'percentag' & 'chang' & 'fiscal' & '2018' & 'fiscal' & '2019'
```

No chunk contained every required lexeme. This is a measured limitation of passing the complete question directly to `websearch_to_tsquery`, not a scoring failure. M2.4 was later changed on the strength of this measurement: the parsed conjunction is now relaxed to a disjunction and ranked under extent-distance and length normalization, which lifted the lexical arm from 0.000 to 0.271 recall@5. The zero stands in this document as what the unrelaxed baseline measured.

## F5 — The deterministic provider is a reproducibility baseline

The local provider hashes normalized tokens into a 384-dimensional signed bag-of-words vector. It is stable and free, but it does not model semantic similarity like a production embedding model. The committed results therefore establish that the runner, provenance, span scoring, latency capture, and comparison matrix work; they do not establish expected OpenAI quality and do not reveal the provider used by the populated corpus.

## F6 — Both measured budgets passed

The corrected timer starts before manifest loading, parsing, and chunk construction, then includes temporary table creation, persistence, GIN construction, and deterministic embedding backfill.

| Measurement | Observed | Budget | Result |
|---|---:|---:|---|
| 500-character indexing, 20 documents / 12,984 chunks | 75.158 s | 300 s | pass |
| 1200-character indexing, 20 documents / 9,172 chunks | 63.881 s | 300 s | pass |
| 200 sequential 1200-character hybrid queries | 12.994 s | 90 s | pass |

The 200-query run measured 64.970 ms mean, 64.604 ms P50, 71.480 ms P95, and 78.916 ms maximum latency. The source of record is the [budget artifact](../../../data/eval_runs/20260812T200916Z-budgets.json).

## F7 — The remaining gates are intentionally manual

Two decisions remain outside machine acceptance:

1. the author must inspect and approve or revise every golden case; and 2. the author must explicitly approve provider cost and credentials before an OpenAI ablation is run.

Until both gates are handled, the deterministic report remains the only committed baseline and no semantic-provider or production configuration claim is justified.
