# M2 Overview — Hybrid retrieval

> **`zero` branch note:** The complete code below is the pinned reference target — write the canonical files yourself. Live progress: [module plan](../../project/module-plan.md).

M2 turns the source-cited PostgreSQL chunks from M1.4 into deterministic retrieval results. It embeds indexed text, runs exact pgvector cosine search and PostgreSQL full-text search, combines their ranks with reciprocal rank fusion (RRF), and preserves the complete citation surface in every result.

## One-sentence contract

`query + filters -> query embedding -> exact vector rank + lexical rank -> RRF -> cited hits`

The runtime result also exposes the vector and lexical chunk-ID rankings. It never adds the native cosine or `ts_rank_cd` values to that component provenance because those scores have unrelated scales.

## What M2 includes

| Step | Responsibility | Reference implementation |
|---|---|---|
| M2.1 | Strict cited-hit and filter contracts | `app/retrieval/types.py` |
| M2.2 | Deterministic and OpenAI embedding providers; resumable backfill | `app/retrieval/embeddings.py` |
| M2.3 | Exact pgvector cosine retrieval | `app/retrieval/vector.py` |
| M2.4 | Safe PostgreSQL full-text retrieval | `app/retrieval/lexical.py` |
| M2.5 | Rank-only RRF | `app/retrieval/hybrid.py` |
| M2.6 | Optional reranker provider boundary | `app/retrieval/rerank.py` |
| M2.7 | One-session production composition and JSON CLI | `app/retrieval/service.py`, `app/retrieval/__main__.py` |
| M2.8 | pgvector bootstrap and live PostgreSQL proof | `app/db/bootstrap.py`, `tests/retrieval/test_08_postgres.py` |
| M2.9 | Hand-written BM25 ranking arm | `app/retrieval/bm25.py` |
| M2.10 | Local sentence-transformer embedding provider | `app/retrieval/sbert.py` |
| M2.11 | Cross-encoder reranking provider | `app/retrieval/cross_encoder.py` |

## Reading order

1. [Measured findings](01-findings.md) explains why the implementation uses these providers, searches, and boundaries. 2. [Normative specification](02-spec.md) defines the contracts that code and tests must preserve. 3. [Layer-by-layer build guide](03-build.md) moves from the concepts to source code and cumulative tests. 4. [Bugs and design traps](04-bugs.md) records symptoms, root causes, fixes, and regression guards. 5. [Verification](05-verify.md) provides acceptance commands, the test map, and failure triage.

## Quick start: deterministic offline provider

Start only PostgreSQL, create and seed the schema, then fill null embeddings with the deterministic token-hash provider:

```bash
docker compose up -d db
uv run python -m app.ingestion.seed --create-schema
uv run python -m app.retrieval --provider deterministic --embed-missing --query "NVDA 2024 R&D" -k 3
```

The first retrieval command backfills only rows whose embedding is null. Later queries can omit `--embed-missing`:

```bash
uv run python -m app.retrieval --provider deterministic --query "NVDA 2024 R&D" -k 3 --candidate-k 20
```

The JSON output contains complete hits and two component rank lists. A hit includes `chunk_id`, citation, half-open source span, source hash, evidence body, synthetic context, indexed text, and the fused RRF score.

## OpenAI provider

M2 uses `text-embedding-3-small` with an explicit 384-dimensional output. Populate and query a fresh embedding set with the same provider:

```bash
EMBEDDING_PROVIDER=openai OPENAI_API_KEY="your-key" uv run python -m app.retrieval --embed-missing --query "NVDA 2024 R&D" -k 3 --candidate-k 20
```

The current schema does not persist embedding-provider identity. Never query deterministic vectors with OpenAI query vectors, or the reverse. Use one provider for both corpus backfill and queries; changing providers requires an explicit rebuild or migration.

## Baseline boundaries

- Vector search is exact cosine search. M2 creates no HNSW or IVFFlat index.
- Lexical search is PostgreSQL `websearch_to_tsquery` relaxed to a disjunction, ranked by `ts_rank_cd` with extent-distance and length normalization; it is not literal BM25. Real BM25 arrives as a second arm in M2.9.
- Local models are optional. `import app.retrieval` needs no torch backend, and M2.10 and M2.11 load weights only when a provider is actually used.
- Reranking stays off unless a caller supplies a reranker. M2.11 fills the boundary and M3.4 decides whether to switch it on.
- RRF combines one-based ranks, not native component scores.
- The service requests `max(20, 4 * k)` candidates per component unless the caller sets `--candidate-k` explicitly.
- One `AsyncSession` is shared sequentially by vector and lexical search.
- Reranking is an optional experiment arm and is not part of the default acceptance path.
- `--create-schema` creates missing objects in a fresh schema; it is not a migration tool.

## Direct implementation path

Create each canonical algorithm module directly in the order documented in [the build guide](03-build.md). Missing symbols skip their dependent tests after the package exists, so the focused suite remains a progress board.
