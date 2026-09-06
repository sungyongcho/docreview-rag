# M2 Bugs

Each entry records the symptom, root cause, fix, and regression guard. Measured final results remain in [findings F11](01-findings.md#f11--recorded-verification-evidence).

## B01 — A fresh schema could not create the vector column

Status: fixed.

Symptom: `create_all` failed because PostgreSQL did not recognize `vector(384)`.

Root cause: pgvector is installed in the server image but extensions are enabled per database. SQLAlchemy attempted to create the chunk table before enabling it.

Fix: run `CREATE EXTENSION IF NOT EXISTS vector` before `Base.metadata.create_all` in the same bootstrap transaction. Route the seed CLI's explicit `--create-schema` path through that helper.

Regression: `test_bootstrap_enables_vector_before_create_all` and the live idempotence exercise.

## B02 — Parallel component calls could corrupt session state

Status: fixed by contract.

Symptom: a tempting `asyncio.gather` implementation would issue vector and lexical SQL at the same time through one `AsyncSession`.

Root cause: asynchronous syntax does not make a mutable SQLAlchemy session safe for concurrent task use.

Fix: inject two adapters that close over one session and await vector first, then lexical.

Regression: the service test records exact call order and session object identity.

## B03 — `R&D` made the lexical acceptance list empty

Status: fixed after real-corpus integration.

Symptom: `"NVDA 2024 R&D"` produced no lexical hits and ranked Intel chunks above NVDA.

Root cause: PostgreSQL parsed the abbreviation as `'r' & 'd'`, while the relevant filing text commonly uses the full phrase `Research and Development`. The deterministic provider also hashed the isolated letters.

Fix: expand `R&D` to `research development` once at the production service boundary before both query embedding and lexical search.

Regression: the service test asserts the normalized query received by both components; the real acceptance command returns an NVDA FY2024 chunk first.

## B04 — Fusion compared unrelated score scales

Status: fixed.

Symptom: a high `ts_rank_cd` value or cosine similarity could dominate a weighted sum for reasons unrelated to relevance.

Root cause: the two values have different meanings and no shared calibration.

Fix: ignore source scores during RRF and add only reciprocal rank contributions. Expose component rankings as chunk IDs without scores.

Regression: RRF tests use deliberately extreme source scores and prove that fused results do not retain them; the service payload checks the rank-only shape.

## B05 — An approximate index appeared before evidence

Status: prevented.

Symptom: adding HNSW would make the system look optimized while silently introducing a recall tradeoff that M2 had not measured.

Root cause: treating a common production optimization as a default correctness primitive.

Fix: retain exact pgvector search and defer approximate-index decisions to M3 latency and retrieval-quality measurements.

Regression: model and SQL tests assert that no HNSW index exists.

## B06 — Provider and database dimensions could diverge

Status: fixed.

Symptom: a provider returned a valid vector that PostgreSQL rejected because its dimension did not match `chunks.embedding`.

Root cause: provider validation alone cannot know the active database model dimension.

Fix: validate provider dimensions against `app.db.models.DIM` before embedding or SQL.

Regression: the service rejects a 32-dimensional deterministic provider before I/O.

## B07 — A provider switch reused incompatible stored vectors

Status: documented M2 limitation.

Symptom: deterministic document vectors queried with an OpenAI query vector produce meaningless cosine distances even though both have 384 components.

Root cause: dimensions describe shape, not embedding-space identity. M2 does not persist a provider/model fingerprint with each vector.

Fix: use one provider configuration for backfill and query. A provider change requires an explicit rebuild or migration; `--embed-missing` intentionally does not overwrite non-null vectors.

Regression: provider selection and null-only backfill are tested. M3 should record provider configuration in experiment artifacts.

## B08 — Invalid fusion settings performed work before failing

Status: fixed.

Symptom: a nonpositive `rrf_k` could reach the provider and database before RRF rejected it.

Root cause: validation lived only in the final pure fusion function.

Fix: validate blank query, `k`, `candidate_k`, `rrf_k`, and provider dimension at the service boundary. The hybrid helper also rejects nonpositive `rrf_k` before component calls.

Regression: parameterized service tests replace all I/O with functions that fail if called.

## B09 — Provider response order was trusted implicitly

Status: fixed.

Symptom: an SDK response whose data items arrived out of input order could assign the wrong vector to a chunk.

Root cause: treating response list position as caller order instead of using the response index.

Fix: validate unique complete indices, map by index, and restore caller order before shape validation.

Regression: the OpenAI provider test supplies reversed response items and expects restored order; duplicate and incomplete indices fail.

## B10 — `create_all` was mistaken for migration

Status: documented limitation.

Symptom: running `--create-schema` against an older existing table definition left missing columns unchanged.

Root cause: SQLAlchemy metadata creation creates missing objects; it is not an alteration planner.

Fix: describe bootstrap as a fresh-schema operation only. Use a reviewed migration or a disposable database for schema evolution.

Regression: CLI help and the M1.4/M2 specifications state the boundary.

## B11 — The default candidate pool collapsed to the result limit

Status: fixed.

Symptom: omitting `candidate_k` requested only `k` candidates from each component, leaving RRF too little ranking depth to recover consensus candidates.

Root cause: the low-level hybrid helper's minimal fallback leaked into the production service contract.

Fix: the service computes `max(20, 4 * k)` only when the caller omits `candidate_k` and preserves every explicit value that satisfies `candidate_k >= k`.

Regression: the service composition test omits `candidate_k` and records 20 for both component calls when `k=2`, then 24 when `k=6`.

## B12 — The live PostgreSQL test stalled after completing SQL

Status: fixed.

Symptom: the test connection disappeared from `pg_stat_activity`, but the sandboxed pytest process could remain alive for 300 seconds during Python executor shutdown.

Root cause: the test resolved `localhost` and split reachability and exercise work across two `asyncio.run` event loops.

Fix: the project test database fixture accepts loopback URLs only, normalizes the host to `127.0.0.1`, and executes probing plus temporary-table acceptance in one event loop.

Regression: the focused retrieval suite includes the real live test and exits promptly.
