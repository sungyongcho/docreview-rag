# Retrieval evaluation report

| Field | Value |
|---|---|
| Run | `20260824T203336Z` |
| Suite | `m3-retrieval-v1` |
| Provider | deterministic 384-dimensional token-hash vectors |
| Environment | isolated temporary PostgreSQL tables with pgvector |
| Cost | no paid API calls |
| Corpus mutation | populated embeddings unchanged |

## Executive result

The complete ten-arm experiment and both performance budgets ran successfully: two chunk targets crossed with lexical, vector, and hybrid retrieval, and every arm that runs a lexical query crossed with both PostgreSQL rankers. The strongest arm was 1200-character BM25 lexical retrieval at Recall@5 `0.520833` and MRR `0.395139`. Plain lexical retrieval beat rank fusion in every comparison, because fusing the deterministic vector ranking into a stronger lexical ranking dilutes it, so this run does **not** justify enabling hybrid retrieval or selecting a production configuration.

## Portfolio verdict

This run proves that the repository can build isolated corpora, execute the complete chunking-by-retrieval-by-ranker matrix, score immutable raw-source spans, retain per-case ranks, and enforce local latency budgets without paid calls or corpus mutation. It also proves the two M2 lexical rankers are genuinely selectable and measurably different.

It does **not** prove semantic retrieval quality, human-approved golden truth, production scale, or hosted latency. Vector quality is a deterministic token-hash baseline, its weakness caps every hybrid arm, and all golden cases remain pending author approval. Those are decision-stopping limitations, not details to hide behind the passing budgets.

The architectural implications and operational responses are documented in [architecture.md](architecture.md) and [failure-analysis.md](failure-analysis.md).

## Golden suite provenance

The suite contains 28 agent-curated candidates: 24 positive source-bearing cases and four absent cases. Positive answers are immutable `(doc_id, source_sha256, [start, end))` raw filing coordinates and remain identical across both chunking arms. Every case is pending author approval and has `human_verified=false`; machine validation must not be presented as human review.

The taxonomy is balanced by construction: categories split into 13 `simple_lookup`, 5 `exact_number`, 6 `multi_hop`, and 4 `absent` cases; facets split into 6 `factual`, 6 `comparison`, 6 `risk`, 5 `policy`, and 5 `numeric`; and the 24 positives cover all 20 filings with six cases per ticker. Since M3.5 the suite grows only through the gated curation pipeline in `app/evals/curation.py`: generated candidates enter the `m3s` namespace, pass machine gates for source binding, duplication, and span width, and reach `m3c` ids only through explicitly recorded review decisions.

Known biases of this construction: the generator drafted questions while reading the filings, so wording drifts toward source vocabulary and lexical retrieval likely scores optimistically; span granularity — sentence, fragment, or table row — was chosen by the curator and fixes what "relevant" means for every matching rule; and a single agent family generated every case, so failure modes that generator cannot imagine are missing from the suite. The candidate round `data/golden/candidates/r1.json` deliberately paraphrases away from source wording to probe the first bias.

## Quality and case latency

| Chunk target | Retrieval | Lexical ranker | Recall@5 | Hit Rate@5 | MRR | Mean ms | P95 ms | Raw artifact |
|---:|---|---|---:|---:|---:|---:|---:|---|
| 500 | lexical | `ts_rank_cd` | 0.333333 | 0.333333 | 0.216667 | 122.578 | 213.585 | [JSON](../../data/eval_runs/20260824T203336Z-structure-500-lexical-ts-rank-cd.json) |
| 500 | lexical | `bm25` | 0.458333 | 0.458333 | 0.361111 | 46.602 | 69.846 | [JSON](../../data/eval_runs/20260824T203336Z-structure-500-lexical-bm25.json) |
| 500 | vector | - | 0.125000 | 0.125000 | 0.070833 | 37.800 | 43.989 | [JSON](../../data/eval_runs/20260824T203336Z-structure-500-vector.json) |
| 500 | hybrid | `ts_rank_cd` | 0.208333 | 0.208333 | 0.131944 | 182.608 | 290.973 | [JSON](../../data/eval_runs/20260824T203336Z-structure-500-hybrid-ts-rank-cd.json) |
| 500 | hybrid | `bm25` | 0.333333 | 0.333333 | 0.195833 | 81.317 | 99.212 | [JSON](../../data/eval_runs/20260824T203336Z-structure-500-hybrid-bm25.json) |
| 1200 | lexical | `ts_rank_cd` | 0.270833 | 0.291667 | 0.171528 | 108.865 | 180.363 | [JSON](../../data/eval_runs/20260824T203336Z-structure-1200-lexical-ts-rank-cd.json) |
| 1200 | lexical | `bm25` | 0.520833 | 0.541667 | 0.395139 | 35.560 | 55.357 | [JSON](../../data/eval_runs/20260824T203336Z-structure-1200-lexical-bm25.json) |
| 1200 | vector | - | 0.062500 | 0.083333 | 0.083333 | 26.856 | 28.016 | [JSON](../../data/eval_runs/20260824T203336Z-structure-1200-vector.json) |
| 1200 | hybrid | `ts_rank_cd` | 0.104167 | 0.125000 | 0.097222 | 152.894 | 238.234 | [JSON](../../data/eval_runs/20260824T203336Z-structure-1200-hybrid-ts-rank-cd.json) |
| 1200 | hybrid | `bm25` | 0.270833 | 0.291667 | 0.190972 | 59.262 | 77.894 | [JSON](../../data/eval_runs/20260824T203336Z-structure-1200-hybrid-bm25.json) |

Metrics cover the 24 positive cases only. Raw artifacts still contain all 28 questions, ranked hits, source spans, per-case latency, and `score=null` for each absent case.

## Taxonomy breakdown of the strongest arm

Grouping the strongest arm — 1200-character BM25 lexical retrieval at k=5 — by golden category and facet with `app/evals/breakdown.py`:

| Category | Cases | Recall@k | Hit rate@k | MRR |
|---|---:|---:|---:|---:|
| simple_lookup | 13 | 0.730769 | 0.769231 | 0.621795 |
| exact_number | 5 | 0.000000 | 0.000000 | 0.000000 |
| multi_hop | 6 | 0.500000 | 0.500000 | 0.233333 |

| Facet | Cases | Recall@k | Hit rate@k | MRR |
|---|---:|---:|---:|---:|
| factual | 5 | 0.700000 | 0.800000 | 0.800000 |
| comparison | 6 | 0.500000 | 0.500000 | 0.233333 |
| risk | 5 | 0.800000 | 0.800000 | 0.416667 |
| policy | 3 | 0.666667 | 0.666667 | 0.666667 |
| numeric | 5 | 0.000000 | 0.000000 | 0.000000 |

The aggregate Recall@5 of `0.520833` is not a uniform property of the suite. `exact_number` cases score zero on every metric while `simple_lookup` reaches `0.730769` recall, and `numeric` is the only zero facet. The zeros concentrate where answers live inside large financial tables, whose raw-source spans dwarf the golden answer under the current overlap rule — a measurement artifact to resolve before reading these rows as "the retriever cannot find numbers." The breakdown is what turns one aggregate into that diagnosis.

## Performance budgets

| Measurement | Work | Observed | Limit | Result |
|---|---|---:|---:|---|
| 500 indexing | parse, chunk, temporary PostgreSQL persistence, GIN, BM25 term statistics, 12,984 deterministic vectors | 38.453 s | 300 s | pass |
| 1200 indexing | parse, chunk, temporary PostgreSQL persistence, GIN, BM25 term statistics, 9,172 deterministic vectors | 33.860 s | 300 s | pass |
| query budget | 200 sequential 1200-hybrid queries under `ts_rank_cd` | 29.786 s | 90 s | pass |

The query budget measured 148.928 ms mean, 148.145 ms P50, 213.559 ms P95, and 283.420 ms maximum latency under the first configured ranker, `ts_rank_cd`. See the [raw budget record](../../data/eval_runs/20260824T203336Z-budgets.json).

## Interpretation

- BM25 beat `ts_rank_cd` in every arm that ran a lexical query. Corpus statistics — document frequency, saturation, length — are exactly what cover density cannot see, and the gap they buy measured `0.520833` against `0.270833` at 1200 characters.
- The relaxed `ts_rank_cd` baseline now retrieves where the prior run measured exactly zero. Its cost is candidate breadth: disjunctive matching pushed its P95 latencies to 180-291 ms, the slowest arms in the matrix.
- Lexical retrieval beat hybrid fusion everywhere. RRF is rank-only and cannot know that one component is weak, so fusing the deterministic vector ranking into a stronger lexical ranking can only dilute it.
- The 500-character arm no longer wins across the board. With a working lexical ranker the 1200-character BM25 arm is the strongest, so chunking and ranking interact and neither can be tuned alone.
- The deterministic provider remains a plumbing and reproducibility baseline, not semantic quality. Only the lexical-versus-lexical comparison is embedding-independent.

## Prior run

The `20260812T200916Z` artifacts preserve the six-arm predecessor of this matrix. Its lexical arms measured zero hits for all 28 questions, which was diagnosed as conjunctive full-text matching and drove the M2.4 relaxation and ranking-normalization fix. Those artifacts stay committed as the record of what the unrelaxed baseline measured.

## Reproducibility command

```bash
uv run python -m app.evals --provider deterministic --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

`--lexical-rankers` defaults to both rankers, which is what expands the six named arms into ten. The command builds isolated temporary corpus tables, rebuilds BM25 statistics once per corpus arm, and never overwrites the populated embeddings. Provider identity is supplied explicitly and is not inferred from existing vectors.

## OpenAI opt-in gate

No OpenAI embedding request was executed. After explicit author cost approval and credential/model-access confirmation, run a separate experiment with:

```bash
OPENAI_API_KEY="your-key" uv run python -m app.evals --provider openai --target-text-chars 500 1200 --strategies lexical vector hybrid -k 5 --candidate-k 20 --rrf-k 60 --budget-queries 200 --artifact-dir data/eval_runs
```

The estimated input is about 3.855 million tokens using a four-characters-per-token planning approximation. Using the official [`text-embedding-3-small` price of $0.02 per million input tokens](https://developers.openai.com/api/docs/models/text-embedding-3-small), checked on 2026-08-12, the dated planning estimate is about **$0.08**. Approve a **$0.10** ceiling and recheck current pricing immediately before execution. Actual provider tokenization, retries, and billing determine the final cost.

## Decision and unresolved gates

Keep this deterministic run as the reproducible offline baseline. The lexical-ranker comparison is embedding-independent and stands on its own; the production default nevertheless remains `ts_rank_cd`, and promoting BM25 is an explicit author decision, not an automatic consequence of a measurement. The remaining gates are author review of all golden cases and an explicitly approved, separately labeled semantic-provider run; neither is implied by the completed machine checks.

## Regression context

The full offline suite at the revision that produced this run measured `833 passed, 1 skipped`. The one skip remains the explicitly opt-in live OpenAI workflow test; ordinary verification made no paid provider call. The historical M6 checkpoint of `697 passed, 1 skipped` and the post-M7 checkpoint of `718 passed, 1 skipped` remain recorded in their module documents.
