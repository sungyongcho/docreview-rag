# M2 Findings

This file owns the measured and source-verified evidence that shaped M2. Normative rules are in [the specification](02-spec.md); implementation order is in [the build guide](03-build.md).

## F1 — Python 3.14 does not require a local embedding model

The project runs Python 3.14.1 and already includes OpenAI 2.53.0, SQLAlchemy 2.0.51, asyncpg, and pgvector. A local Sentence Transformers dependency would add a separate PyTorch compatibility and memory boundary that M2 does not need.

Decision: keep an asynchronous `EmbeddingProvider` boundary. Use OpenAI as the configured production provider and a dependency-free deterministic token-hash provider for tests and offline exercises.

Evidence: provider tests run without network access, and the live configured OpenAI probe returned one 384-dimensional finite vector.

## F2 — OpenAI supports explicit shortened embedding dimensions

The installed asynchronous SDK accepts `dimensions` and `encoding_format` on `embeddings.create`. The current OpenAI documentation identifies `text-embedding-3-small` as an embeddings model, and the official SDK declares the `dimensions` parameter for `text-embedding-3` models.

Decision: request 384 float components explicitly and reject missing, duplicate, out-of-order, non-finite, or wrong-shaped responses before they reach PostgreSQL.

Primary references:

- [OpenAI text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small)
- [OpenAI Python embeddings resource](https://github.com/openai/openai-python/blob/main/src/openai/resources/embeddings.py)

## F3 — Exact pgvector search is the correct unmeasured baseline

pgvector performs exact nearest-neighbor search by default. Approximate indexes trade recall for speed and can change results. M2 has only 9,172 chunks, while M3 owns retrieval-quality and latency measurements.

Decision: order by cosine distance with `<=>`, convert distance to similarity only when constructing a `ChunkHit`, and create no HNSW or IVFFlat index before M3 measurements.

Primary reference: [pgvector querying and indexing](https://github.com/pgvector/pgvector#querying).

## F4 — PostgreSQL FTS is a lexical baseline, not literal BM25

PostgreSQL provides forgiving web-search query parsing and cover-density ranking through `websearch_to_tsquery` and `ts_rank_cd`. Its native ranking is not the BM25 formula.

Decision: bind raw query values, use the generated `content_tsv`, rank by `ts_rank_cd`, and describe the result accurately as PostgreSQL full-text search.

Primary reference: [PostgreSQL text-search controls](https://www.postgresql.org/docs/current/textsearch-controls.html).

## F5 — Native scores cannot be fused safely

Cosine similarity and `ts_rank_cd` measure different quantities and have unrelated scales. A weighted sum would make an undocumented calibration choice and would be unstable across corpora or query forms.

Decision: fuse one-based positions using RRF and expose component provenance as ordered chunk IDs only. The public component structure has no score field.

Regression: `test_service_uses_one_session_sequentially_and_exposes_rank_only_components`.

## F6 — One `AsyncSession` requires sequential composition

SQLAlchemy async sessions represent mutable transaction state and are not safe for concurrent task use. Creating one session per component would also blur transaction and connection ownership.

Decision: service-local vector and lexical adapters close over one caller-supplied session. `hybrid_search` awaits the vector adapter first and the lexical adapter second.

Regression: the service test records `embed`, `vector`, and `lexical` events and confirms that both database calls receive the same object.

## F7 — The literal acceptance query exposed an abbreviation mismatch

The first real-corpus run used `"NVDA 2024 R&D"`. PostgreSQL parsed the final abbreviation as `'r' & 'd'`, so the lexical component returned no rows. The deterministic provider also hashed `r` and `d`, while filing prose frequently spells out `Research and Development`. The result incorrectly ranked Intel chunks above the requested filing.

Decision: the production service expands the common `R&D` abbreviation to `research development` before both query embedding and lexical search. The CLI still echoes the user's original query.

Regression: the service test asserts that both components receive `"NVDA 2024 research development"` and the live acceptance path ranks an NVDA FY2024 chunk first.

## F8 — pgvector must exist before SQLAlchemy creates vector columns

A fresh PostgreSQL database does not know the `vector(384)` type until the extension is enabled. Calling `Base.metadata.create_all` first therefore fails before it can create the chunk table.

Decision: one idempotent bootstrap transaction executes `CREATE EXTENSION IF NOT EXISTS vector` before `create_all`. The existing seed CLI uses this helper when `--create-schema` is explicit.

Regression: the unit test records operation order, and the live test enables the extension twice before exercising temporary vector tables.

## F9 — A result limit is not a useful fusion candidate limit

Requesting only `k` vector and lexical candidates leaves RRF almost no room to recover a chunk that is moderately ranked in both components. The production service therefore uses `max(20, 4 * k)` when `candidate_k` is omitted while preserving explicit values at least as large as `k`.

Regression: the service test omits `candidate_k` and proves that both sequential component calls receive 20 for `k=2` and 24 for `k=6`.

## F10 — One loopback event loop keeps the live test bounded

The original live test resolved `localhost` and called `asyncio.run` once for reachability and again for the exercise. In the Python 3.14 sandbox, executor shutdown could then wait 300 seconds after the SQL work had already finished.

Decision: a session-scoped test fixture accepts only loopback database URLs, normalizes the host to `127.0.0.1`, and runs connection probing plus temporary-table acceptance in one event loop.

## F11 — Recorded verification evidence

Recorded on 2026-08-12 against PostgreSQL 16.14 and pgvector 0.8.3:

| Check | Exact result |
|---|---|
| Retrieval unit/integration suite | 90 passed, 0 skipped, 0 failed |
| Layer counts | 29, 41, 52, 61, 70, 79, 88, 90 cumulative tests |
| Seed bootstrap | 20 documents and 9,172 chunks committed |
| Deterministic backfill | 9,172 selected, 9,172 embedded, 0 stale, 72 batches |
| Deterministic acceptance | top hit chunk 9056, `NVDA-FY2024`, Item 15, table |
| Acceptance component ranks | vector 20 chunk IDs; lexical 13 chunk IDs; no component scores |
| OpenAI live provider probe | 384 components, all finite, Euclidean norm 0.999817907 |
| Approximate indexes | 0 HNSW indexes on `chunks` |

The PostgreSQL test used connection-local temporary tables and passed instead of skipping. The real-corpus acceptance command then used the application schema populated through the idempotent seed bootstrap. No live OpenAI corpus backfill was performed because the same application database already contained deterministic vectors; mixing provider spaces would make the retrieval result invalid.
