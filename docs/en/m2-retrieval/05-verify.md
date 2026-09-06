# M2 Verification

Run the checks in this order. A failure stays attached to the smallest responsible layer, and the live database path remains distinguishable from deterministic unit coverage.

## 1. Focused retrieval suite

```bash
uv run pytest -o addopts="" tests/retrieval -q
```

With PostgreSQL available, every test passes. The live fixture accepts only a loopback project database URL, normalizes `localhost` to `127.0.0.1`, and performs its three-second probe plus exercise in one event loop. Without PostgreSQL, that test skips; all SQL compilation, provider, fusion, service, CLI, and bootstrap-order tests still run.

## 2. Test map

| Test file | Evidence |
|---|---|
| `test_01_contract.py` | strict cited hits, canonical filters, stable tie-breakers, public package exports |
| `test_02_embeddings.py` | deterministic vectors, OpenAI request/ordering, output validation, resumable backfill |
| `test_03_vector.py` | exact cosine SQL, null exclusion, filters, full hit mapping, no HNSW |
| `test_04_lexical.py` | safe web-search parsing, cover-density ranking, filters, full projection |
| `test_05_hybrid.py` | rank-only RRF, deduplication, deterministic ties, sequential injection |
| `test_06_rerank.py` | optional provider, complete indexed text, score validation, deterministic fallback |
| `test_07_service.py` | one session, exact order, abbreviation parity, component IDs, exports, CLI payload |
| `test_08_postgres.py` | extension-before-schema order and optional live vector + FTS + RRF proof |

The layer order and primary tests are in the [build step map](03-build.md).

## 3. Real database bootstrap and corpus

Start only the database service:

```bash
docker compose up -d db
docker compose ps db
```

Create missing schema objects and seed the fixed corpus:

```bash
uv run python -m app.ingestion.seed --create-schema
```

The helper enables pgvector before table creation. Repeating the command is safe for the current schema and corpus, but it is not a migration for older table definitions.

Inspect the application state without changing it:

```sql
SELECT extversion FROM pg_extension WHERE extname = 'vector';
SELECT count(*) FROM documents;
SELECT count(*) FROM chunks;
SELECT count(*) FROM chunks WHERE embedding IS NOT NULL;
SELECT count(*)
FROM pg_indexes
WHERE tablename = 'chunks' AND indexdef ILIKE '%hnsw%';
```

Before M2 backfill, the non-null embedding count should be zero. The HNSW count must remain zero throughout M2.

## 4. Deterministic offline acceptance

Populate null vectors and run the literal milestone query:

```bash
uv run python -m app.retrieval --provider deterministic --embed-missing --query "NVDA 2024 R&D" -k 3
```

Verify all of the following in the JSON response:

- `provider` is `deterministic`;
- backfill counts are internally consistent;
- the first hit belongs to `NVDA-FY2024`;
- every hit has a positive chunk ID, citation, valid half-open span, source hash, body, context, and indexed text;
- `component_rankings.vector` and `component_rankings.lexical` contain chunk IDs only; and
- no component ranking contains a score.

Repeat without backfill to prove the query-only path:

```bash
uv run python -m app.retrieval --provider deterministic --query "NVDA 2024 R&D" -k 3 --candidate-k 20
```

The recorded exact corpus result is in [findings F11](01-findings.md#f11--recorded-verification-evidence).

## 5. OpenAI provider verification

The unit test uses a fake async client and proves the exact request shape without network access. When a valid key is configured, this bounded live probe verifies the current SDK and provider response without printing the key or vector:

```bash
uv run python - <<'PY'
import asyncio
import math

from app.config import get_settings
from app.retrieval.embeddings import get_embedding_provider


async def main() -> None:
    settings = get_settings().model_copy(update={"embedding_provider": "openai"})
    provider = get_embedding_provider(settings)
    vector = await provider.embed_query("M2 retrieval verification")
    print(f"dimensions={len(vector)}")
    print(f"finite={all(math.isfinite(value) for value in vector)}")
    print(f"l2_norm={math.sqrt(sum(value * value for value in vector)):.9f}")


asyncio.run(main())
PY
```

Do not run an OpenAI query against a database populated by the deterministic provider. A live OpenAI corpus acceptance requires a fresh or explicitly rebuilt OpenAI embedding set.

## 6. Repository gates

Run lint without automatic edits:

```bash
uv run ruff check --no-fix app tests scripts
```

Run documentation source and link synchronization:

```bash
uv run python scripts/check_doc_code.py
```

Run the full regression suite:

```bash
uv run pytest -o addopts="" -q
```

Finally, verify whitespace and conflict markers:

```bash
git diff --check
```

## 7. Completion checklist

- [x] `ChunkHit` preserves complete evidence, context, citation, hash, and source span.
- [x] Filters and equal-score ordering are deterministic.
- [x] The offline provider is stable, normalized, 384-dimensional, and network-free.
- [x] OpenAI requests `text-embedding-3-small` with 384 float dimensions.
- [x] Missing-vector backfill is bounded, resumable, and stale-safe.
- [x] Vector retrieval is exact cosine search and excludes null embeddings.
- [x] PostgreSQL FTS uses safe web-search parsing and cover-density ranking.
- [x] RRF ignores native scores and uses chunk-ID identity.
- [x] Optional reranking stays behind a dependency-free provider boundary.
- [x] Production composition uses one session sequentially.
- [x] Component provenance exposes rankings without raw scores.
- [x] Omitted candidate depth expands to `max(20, 4 * k)` at the service boundary.
- [x] `R&D` has matching embedding and lexical semantics.
- [x] Schema bootstrap enables pgvector before `create_all`.
- [x] No HNSW index is present before M3.
- [x] `python -m app.retrieval` completes the deterministic acceptance path.

## 8. Failure triage

| Symptom | Likely owner | First check |
|---|---|---|
| `type "vector" does not exist` | bootstrap or database permissions | run the extension query as the schema owner |
| database test skips | local service availability | `docker compose ps db` |
| wrong vector dimension | provider/config/model mismatch | compare provider dimensions with `app.db.models.DIM` |
| zero vector hits | missing or incompatible embeddings | inspect non-null count and provider identity |
| zero lexical hits for `R&D` | bypassed service normalization | call `app.retrieval.retrieve`, not low-level lanes independently |
| same session concurrency error | service composition | remove `gather`; preserve vector-then-lexical order |
| unstable equal-score order | SQL or pure sort tie-breakers | compare with the six-field ordering contract |
| OpenAI authentication error | credential or account permission | run the bounded provider probe without exposing the key |
| OpenAI query returns irrelevant corpus hits | mixed embedding spaces | rebuild with one provider before evaluating relevance |
| doc sync mismatch | copied source block drifted | run the documented sync checker and inspect the first symbol mismatch |

Do not respond to a retrieval-quality failure by adding HNSW. Approximate indexes address latency and may reduce recall; M3 must measure both before changing the baseline.
