# M2 Spec

## 1. Scope

M2 shall consume the source-cited `Document` and `Chunk` rows produced by M1.4. It shall provide deterministic embedding backfill, exact vector search, PostgreSQL full-text search, rank-only fusion, an optional reranking boundary, one-session production composition, and a command-line acceptance path.

The M2.1 through M2.8 baseline shall not create an approximate vector index, claim PostgreSQL FTS is literal BM25, implement a BM25 ranking function, perform evaluation, select an M3 winning configuration, or migrate an existing database schema. Section 15 specifies the deferred BM25 arm.

## 2. Embedding contract

Every provider shall implement asynchronous document and query embedding. Provider output shall preserve input order and contain exactly one finite numeric vector per input.

The database and provider dimension is 384. The production provider shall request `text-embedding-3-small` with `dimensions=384` and float encoding. The offline provider shall use stable SHA-256 token hashing and return normalized 384-dimensional vectors without a network call.

Empty document batches return an empty list. Individual empty strings, wrong vector counts, wrong dimensions, booleans, nonnumeric components, NaN, and infinity are invalid.

Embedding backfill shall:

1. select only rows whose embedding is null in ascending chunk-ID order; 2. close the selection transaction before provider I/O; 3. process bounded batches; 4. update only a row whose embedding is still null and whose `index_text` is unchanged; 5. report selected, embedded, stale-skipped, and batch counts; and 6. require a caller session with no active transaction.

Provider identity is not persisted in M2. A database embedding set and every query against it shall use the same provider and configuration. Vectors from different models occupy unrelated spaces, so changing the provider requires re-embedding every chunk. Mixing them raises nothing and returns a computable similarity, which makes this the one contract in M2 that fails silently.

## 3. `ChunkHit`

`ChunkHit` is a frozen Pydantic value object. Unknown fields are rejected. It contains:

| Field | Contract |
|---|---|
| `chunk_id` | Positive `chunks.id` surrogate key |
| `doc_id` | Nonempty `documents.doc_id`, at most 32 characters |
| `item` | Nullable SEC Item, at most 8 characters when present |
| `kind` | Exactly `text` or `table` |
| `citation` | Nonempty human-readable filing and Item label |
| `start_char`, `end_char` | Half-open canonical-source span with `0 <= start_char < end_char` |
| `source_sha256` | Exactly 64 lowercase hexadecimal characters |
| `body` | Nonempty source-derived evidence |
| `context_header` | Synthetic retrieval context; it may be empty |
| `index_text` | Exactly context plus two newlines plus body, or body when context is empty |
| `score` | Finite strategy score whose range is strategy-specific |

The contract shall not accept a snippet in place of `body`. Downstream citation and span evaluation require the complete stored evidence. The score is not constrained to `[0, 1]` because cosine similarity, text ranking, RRF, and reranking do not share one scale.

## 4. Retrieval filters

`RetrievalFilters` is frozen and supports:

- chunk dimensions: `doc_ids`, `items`, and `kinds`;
- document dimensions: `tickers`, `fiscal_years`, and `forms`.

Every field is a tuple. An empty tuple means unrestricted. Multiple values in one field are SQL alternatives, including explicit null handling for `items`. Populated fields combine with SQL `AND` semantics.

Equivalent filters shall compare and serialize identically: duplicates are removed, strings and years are sorted, Items place `None` before named Items, and kinds use `text` before `table`. Empty strings, nonpositive years, unsupported kinds, and unknown dimensions are invalid.

## 5. Deterministic ordering

Every strategy shall expose results ordered by:

1. strategy score descending; 2. `doc_id` ascending; 3. `source_sha256` ascending; 4. `start_char` ascending; 5. `end_char` ascending; and 6. `chunk_id` ascending.

Exact vector SQL orders cosine distance ascending, followed by the equivalent source tie-breakers. In-memory `sort_hits()` returns a new list and shall not mutate its input.

## 6. Vector retrieval

Vector retrieval accepts a finite 384-dimensional query vector, positive `k`, and shared filters. It shall exclude null embeddings and use exact pgvector cosine distance. A returned hit score is `1 - cosine_distance`.

M2 shall not define HNSW or IVFFlat indexes. Approximate indexing requires M3 latency and recall evidence.

The low-level vector function may return an empty list for `k=0` without database access, but the production hybrid service requires positive `k`.

## 7. Lexical retrieval

Lexical retrieval accepts a nonblank query, positive `k`, and shared filters. It shall bind the query as a SQL value and parse it with PostgreSQL `websearch_to_tsquery('english', query)`, which is the injection and syntax defence. The parsed conjunction shall then be relaxed to a disjunction before use — rewriting `&` to `|` in the tsquery's text form and reparsing with `to_tsquery` — because requiring every content lexeme of a natural-language question measured recall@5 of exactly zero on the golden suite. Quoted phrases keep their `<->` proximity semantics through the rewrite. Matching and ranking shall consume the same relaxed query, against the generated `content_tsv`, ranked with `ts_rank_cd` under normalization `4 | 1`: division by the mean harmonic distance between extents and by `1 + log(length)`, the combination that measured best, because the default of zero degenerates into occurrence counting and also measures zero recall.

The returned native score is a PostgreSQL cover-density score. Documentation and code shall not describe it as literal BM25 or compare it numerically with cosine similarity. Section 15 specifies the separate BM25 arm that shares this adapter signature.

## 8. Fusion and reranking

RRF shall key identity by `chunk_id`, ignore duplicate occurrences after the first item in one component list, and add `1 / (rrf_k + rank)` for each one-based component rank. Both `k` and `rrf_k` shall be positive.

The hybrid adapter shall await vector search before lexical search. It shall request `candidate_k` from each component and require `candidate_k >= k`.

Reranking is optional. A reranker receives the query and complete candidate `index_text` values, returns one finite numeric score per candidate, and may replace scores only in its explicit experiment arm. With no provider it preserves deterministic source ordering and truncates to `top_k`.

## 9. Production service result

Before component work, the service shall reject a blank query, nonpositive `k`, `candidate_k < k`, nonpositive `rrf_k`, or provider/database dimension mismatch. When `candidate_k` is omitted, the service shall request `max(20, 4 * k)` candidates from each component. An explicit `candidate_k >= k` shall be preserved.

The common `R&D` abbreviation shall expand to `research development` before both query embedding and PostgreSQL FTS. This keeps the two component query meanings aligned. The original user query may remain in the CLI response.

The vector and lexical adapters shall close over one caller-supplied `AsyncSession` and run sequentially. The service returns:

- `hits`: immutable fused `ChunkHit` values; and
- `component_rankings.vector` and `component_rankings.lexical`: immutable ordered chunk-ID tuples.

Component rankings shall not contain raw component scores. Fused hits retain their RRF score because that value defines the returned fused order.

## 10. PostgreSQL bootstrap

A fresh-schema bootstrap shall execute `CREATE EXTENSION IF NOT EXISTS vector` before `Base.metadata.create_all` in one engine transaction. Repeating it shall be safe.

The helper creates missing objects only. It shall not be presented as a migration for an older schema, and integration tests shall not reset or truncate the application schema. The live test shall accept only a loopback project database URL, normalize `localhost` to `127.0.0.1`, and use connection-local temporary tables. Its bounded reachability probe and retrieval exercise shall share one event loop.

## 11. CLI acceptance path

`python -m app.retrieval` shall require `--query`, accept positive result and candidate limits, select deterministic or OpenAI embedding providers, optionally fill null embeddings, and emit JSON containing:

- the original query and provider name;
- optional embedding-backfill counts;
- complete fused hits; and
- vector and lexical chunk-ID rankings.

The provider used to backfill documents shall match the provider used for query embedding.

## 12. Public surface and canonical test path

`app.retrieval` shall export the shared contracts, both embedding providers, embedding backfill, vector and lexical search, RRF and hybrid search, reranking, service result types, and `retrieve`.

The tests import `app.retrieval` and its layer modules directly. Create every canonical file at the path documented in the build guide. Missing symbols may skip dependent tests through `tests.support.need`, but completion requires the direct M2 suite to pass.

## 13. Completion gates

- Every provider and database boundary validates shape and finiteness.
- Filters and all equal-score results are deterministic.
- Vector SQL is exact cosine search and has no approximate index.
- Lexical SQL safely parses raw text and uses cover-density ranking.
- RRF consumes ranks rather than source scores.
- One session runs vector and lexical components sequentially.
- Component rankings expose IDs without raw scores.
- The literal acceptance query returns a cited NVDA FY2024 chunk first.
- Deterministic offline and optional live PostgreSQL tests pass.
- A configured OpenAI probe returns 384 finite components.
- Focused and full pytest, Ruff, and documentation synchronization pass.

## 14. Future external search-engine boundary

In the current baseline, PostgreSQL is the only source of truth for `documents` and `chunks`. Elasticsearch or OpenSearch shall not be added for 9,172 chunks and the current requirements alone. Traffic growth by itself is not an adoption trigger. An external search engine becomes a candidate only when measured `p95` or `p99` search latency still misses its target after PostgreSQL query and index tuning, search load must scale independently, or requirements such as analyzers, synonyms, typo tolerance, or highlighting cannot be met reasonably with PostgreSQL FTS.

Even after an external engine is introduced, PostgreSQL remains the source of truth and the external index shall be a rebuildable search projection. Every indexed document shall carry `chunk_id`, `source_sha256`, `start_char`, `end_char`, `index_text`, and a search-schema version. This allows the application to compare external documents with source chunks and rebuild the entire index from PostgreSQL when mappings or analyzers change.

An application request shall not dual-write directly to PostgreSQL and the external engine. Committed changes shall be published through a transactional outbox or CDC based on PostgreSQL logical decoding, and consumers shall apply repeated changes idempotently. A PostgreSQL transaction cannot include the external engine, so the current one-session snapshot guarantee becomes an eventual-consistency boundary between systems. The migration must therefore define the maximum acceptable synchronization lag first and monitor lag, failures, and missing-document counts as operating metrics.

Adoption proceeds in this order:

1. Record the current PostgreSQL retrieval-quality and latency baselines. 2. Create a versioned external index and backfill it completely from PostgreSQL. 3. Connect the change stream and monitor synchronization lag and failures. 4. Shadow real requests through both search paths and compare results, recall, and latency. 5. Atomically switch the alias to the verified index while retaining a PostgreSQL fallback.

The existing boundaries provide only part of this readiness. An external search adapter must still accept `RetrievalFilters` and return `ChunkHit`, which allows `rrf_fuse` and the public `retrieve` response contract to remain stable. However, M2 currently has no external-engine adapter, synchronization worker, lag monitoring, reindexing, or cutover code. Actual adoption is decided from M3 and production measurements.

Primary references:

- [PostgreSQL logical decoding](https://www.postgresql.org/docs/16/logicaldecoding.html)
- [Elasticsearch aliases and zero-downtime reindexing](https://www.elastic.co/guide/en/elasticsearch/reference/current/aliases.html)

## 15. Deferred BM25 lexical ranking arm

Sections 1 through 14 define the M2.1 through M2.8 baseline. That baseline contains no BM25 implementation, and no document may present it as one.

BM25 is still required. The mandatory lexical-baseline requirement names BM25 or TF-IDF, and cover-density ranking is neither. M2.9 shall add a hand-written BM25 ranking arm once the baseline is complete.

The arm shall reuse the lexical adapter signature and return `ChunkHit`, so that `rrf_fuse` and the public `retrieve` contract stay unchanged. It shall derive every statistic from the generated `content_tsv` column that `ts_rank_cd` already ranks. Both arms then share one tokenizer, one stemmer, and one stop-word list, which leaves the ranking function as the only variable between them.

The stored tsvector supplies the required statistics. `unnest(content_tsv)` yields each lexeme with `cardinality(positions)` as its term frequency, document frequency is a count over matching chunk rows, and document length is the summed term frequency of one chunk. Persisted term statistics shall be rebuildable from `chunks` alone, shall not modify an existing column, and shall not alter a golden span. This adds no extension and no external search engine.

The scoring function shall accept `k1` and `b` as explicit parameters rather than embedded constants. Setting `b` to zero disables length normalization and isolates its contribution. That configuration is not TF-IDF and shall not be labeled as such, because the probabilistic IDF term differs.

The IDF term shall be selectable between the two published variants. Robertson's `ln((N - df + 0.5) / (df + 0.5))` turns negative for a lexeme held by more than half the corpus, which makes every match subtract and inverts the ranking on a corpus this size; Lucene's `ln(1 + ...)` has a floor at zero. `lucene` shall therefore be the default, and `robertson` shall remain selectable because the difference is measurable. Document frequency shall be clamped to the corpus size so that statistics left stale by a chunk deletion cannot make the logarithm undefined.

The ranking function, its constants, and its IDF variant shall be reachable from configuration and overridable for a single command. Derived term statistics shall be rebuilt by an explicit command whenever the chunk set changes, and never implicitly per query.

Unit tests shall verify the formula against hand-computed fixtures. An unverified ranking function is worse evidence than no ranking function. At least one test shall run the SQL against a live PostgreSQL corpus and require agreement with the independent Python reference, because a statement that runs is not yet a statement that computes BM25.

M2.9 shall not select a production lexical ranker. Both arms enter the M3.4 ablation matrix, and the documented default follows measured recall, MRR, and latency.

## 16. Deferred local model providers

Sections 1 through 15 describe a system with no machine-learning dependency. Embeddings come from an API or from token hashing, and the reranking boundary has no implementation. M2.10 and M2.11 change that, and neither is part of the default install.

A torch backend shall be declared as a mutually exclusive extra so that exactly one is installable, and importing `app.retrieval` shall not require any of them. Both providers shall import their model library inside the call that first needs it, and constructing a provider shall load no weights.

M2.10 shall add a local sentence-transformer behind `EmbeddingProvider`. Its default model shall produce exactly `DIM` dimensions so that adopting it needs no migration, and a model whose width differs shall be rejected before any vector is stored. It shall reuse the existing output validation rather than introducing its own.

M2.11 shall add a cross-encoder behind `RerankProvider`. Its scores are unbounded logits and shall not be constrained to a range, compared with cosine similarity, or compared with BM25.

The production service shall accept an optional reranker. With none supplied, its behaviour shall be identical to M2.7. With one supplied, fusion shall retain the full candidate pool and the reranker shall reduce it to `k`; handing the reranker only `k` items defeats the purpose of the stage. Component rankings shall continue to record what each retriever proposed.

Both providers run a synchronous, compute-bound model, which shall be executed off the event loop.

M2.10 and M2.11 shall not select a production default. Reranking stays off unless a caller enables it, and M3.4 decides from measured recall, MRR, and latency.
