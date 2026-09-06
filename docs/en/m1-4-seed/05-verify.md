# M1.4 Verification

## Required commands

Run focused tests:

```bash
uv run pytest tests/db -q
```

Run scoped lint without modifying files:

```bash
uv run ruff check --no-fix app/db/models.py app/ingestion/seed.py tests/db
```

The focused test command requires no database. `test_05_postgres.py` skips after a short probe when PostgreSQL is unavailable and activates automatically when it is reachable.

## Test map

| Test file | Evidence |
|---|---|
| `test_01_models.py` | Document metadata, parser/item status JSON, source identity, evidence/context split, generated TSV, nullable embedding, constraints |
| `test_02_records.py` | Deterministic conversion, status preservation, and fail-closed provenance validation |
| `test_03_upserts.py` | PostgreSQL conflict targets, no embedding inserts, conditional invalidation, batching, commit, rollback |
| `test_04_corpus.py` | All 20 filings, every current M1.3 chunk, table kind, source hashes and spans |
| `test_05_postgres.py` | Optional temporary-table rerun, stable counts, embedding preservation and invalidation |

## Completion assertions

- [x] `documents.doc_id` is the document conflict key.
- [x] `(chunks.doc_id, chunks.ordinal)` is the chunk conflict key.
- [x] Document metadata includes report period, source length, and source SHA-256.
- [x] Document metadata preserves parser status and xref Item status/reference evidence.
- [x] Chunk rows store body, context header, index text, kind, Item, ordinal, citation, source span, and source SHA-256.
- [x] PostgreSQL computes `content_tsv` from `index_text`.
- [x] M1.4 record and insert values omit embeddings.
- [x] Equal indexed text preserves an existing M2 embedding.
- [x] Changed indexed text invalidates the stored embedding to `NULL`.
- [x] Full preparation precedes the database transaction.
- [x] One explicit transaction owns every corpus write and stale-row delete.
- [x] Identical reruns cannot add rows.
- [x] A shorter current chunk set cannot leave trailing rows.
- [x] Tests grade the canonical `app/ingestion/seed.py` path directly.

## Corpus golden source

`tests/db/golden.py` derives document identities and aggregate counts from `tests/chunk/golden.py`. This prevents M1.3 and M1.4 from publishing conflicting chunk totals. `test_04_corpus.py` checks prepared records per document and kind, not only the aggregate.

Current expected baseline:

```text
documents = 20
chunks = 9172
text chunks = 8083
table chunks = 1089
```

If the reviewed M1.3 chunk contract changes, update its golden file first. M1.4 will then prove that the new complete set is persisted one-to-one.

## Manual database audit

After running the seed against an intended application database, inspect counts and null embeddings:

```sql
SELECT count(*) FROM documents;
SELECT kind, count(*) FROM chunks GROUP BY kind ORDER BY kind;
SELECT count(*) FROM chunks WHERE embedding IS NOT NULL;
```

The first result must be 20 for the fixed corpus. Both `text` and `table` must be present. Before M2 runs, the final result must be zero.

Run the identical seed command again and repeat the count queries. Counts must not change.

## Failure triage

| Failure | Likely owner |
|---|---|
| Manifest count or metadata error before SQL | corpus manifest or M1.1 parser input |
| Span/hash/body conversion error | M1.3 chunk contract or replaced source snapshot |
| Conflict SQL compilation error | M1.4 L2 statement construction |
| Partial-write or nested-session error | M1.4 L3 transaction caller |
| PostgreSQL test skipped | local database availability, not a unit-test failure |
| Existing non-null embedding becomes null | expected when `index_text` changed; M2 must regenerate it |

## Sign-off record

Recorded on 2026-08-12:

| Gate | Result |
|---|---|
| Focused canonical suite | 27 passed |
| Scoped Ruff `--no-fix` | passed |
| Optional PostgreSQL path | passed against temporary tables |
| Corpus preparation | 20 documents and 9,172 chunks matched golden data |
| Full M1.1-M1.4 suite | 401 passed |
| Scoped whitespace check | passed |

The live PostgreSQL path proved equal-text embedding preservation, changed-text embedding invalidation, stable identical-rerun counts, and stale trailing-ordinal deletion.
