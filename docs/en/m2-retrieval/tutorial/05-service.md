# M2.7 Tutorial 5 — Composing the pieces into one request

Everything built so far gets assembled. Three decisions are made here.

**Prerequisite:** Tutorial 4's `uv run pytest tests/retrieval/test_06_rerank.py -q` passes.

## The session is owned by the caller

The service does not create a session; it **receives one from the caller.** The same philosophy as M1.4's `persist_seed_batch` requiring an idle session.

The reason lies in M5. If one FastAPI request both retrieves and records workflow output, all of it has to sit in the same session and the same transaction to stay consistent. Let the service quietly make its own and that control becomes impossible.

## Raw scores never leave

`RetrievalResult` returns the fused result plus **the ranks each component saw.** It does not return scores — only ranks (`chunk_id` and position).

Ranks are enough for debugging. Knowing "this chunk was 2nd by vector and 8th by lexical" explains the fused result.

Publish raw scores and callers start computing with them — thresholds, averages. At that moment the **mixing of incomparable scores** that M2.5 worked to avoid reappears. Better not to hand them out at all.

## One normalization, for `R&D`

A problem found by measurement. PostgreSQL's full-text search splits `R&D` into the separate lexemes `r` and `d`. Both are so common that the search effectively fails.

Yet 10-K filings far more often spell the same concept out as "research and development." The question arrives as `R&D` while the document spells it out, so lexical search misses.

So the query is normalized once **before the two retrievers diverge.** Having vector and lexical see the same string matters. Normalize only one side and the two lists answer different questions, and the fused result cannot be explained.

> This kind of domain-specific normalization has no end once you start. Only one measured case is included here. If the rules grow, that is work to do after M3's evaluation confirms the effect.

## What to define, what to implement, and what to inspect

M2.7 touches three files: the service, the command-line path, and the package surface that replaces M2.1's temporary one.

| Area | Learning action | What to take away |
|---|---|---|
| `app/retrieval/service.py` header | **Define the structure** | This is the only module that imports all the others |
| `_normalize_query` | **Implement** the normalization yourself | Why it runs before the paths diverge |
| `ComponentRankings` and `RetrievalResult` | **Write the model declarations** | What provenance may be published |
| `retrieve` | **Implement** the composition yourself | How one session reaches two adapters safely |
| `app/retrieval/__main__.py` | **Write the structure, then inspect the entry contract** | Input contract, output shape, and failure paths |
| `app/retrieval/__init__.py` | **Replace the existing definition** | The finished public surface of M2 |

## 1. The module that knows about all the others

### Create `app/retrieval/service.py` — module header

**Learning action — define the structure:** read the import list as an architecture diagram. Everything points inward to here, and nothing points back out.

```python
"""Production composition for deterministic hybrid retrieval."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DIM
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K, hybrid_search
from app.retrieval.lexical import lexical_search
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search
```

**What to look for in the code**

- Five of the six retrieval modules are imported here, and none of them imports this one. That one-way dependency is why each of them stayed testable on its own.
- `DIM` comes from the ORM again, so this module can compare a provider's dimension against the database column before doing any work.

## 2. Normalizing once, before the paths diverge

### Extend `app/retrieval/service.py` — query normalization

**Learning action — implement the normalization:** write the pattern and the substitution. Check what the `\b` boundaries and `\s*` allow.

<!-- src: app/retrieval/service.py::RankedChunkId,_normalize_query -->
```python
RankedChunkId = Annotated[int, Field(gt=0)]
RESEARCH_AND_DEVELOPMENT = re.compile(r"\bR\s*&\s*D\b", flags=re.IGNORECASE)


def _normalize_query(query: str) -> str:
    """Expand the common R&D abbreviation for embedding and PostgreSQL FTS parity."""
    return RESEARCH_AND_DEVELOPMENT.sub("research development", query)
```

**What to look for in the code**

- `\s*` around `&` catches `R & D` and `R&D` alike, and `re.IGNORECASE` catches `r&d`.
- The replacement is "research development", not "research and development". The stop word "and" is dropped by the FTS dictionary anyway, so including it would buy nothing.
- The pattern is compiled once at module level rather than inside the function, since a retrieval service runs this on every request.

## 3. Provenance that may be published

### Extend `app/retrieval/service.py` — result models

**Learning action — write the model declarations:** two small models. The interesting part is which field is *absent*.

<!-- src: app/retrieval/service.py::ComponentRankings,RetrievalResult -->
```python
class ComponentRankings(BaseModel):
    """Ranked chunk identities from each retrieval component, without raw scores."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    vector: tuple[RankedChunkId, ...]
    lexical: tuple[RankedChunkId, ...]


class RetrievalResult(BaseModel):
    """Fused evidence plus inspectable rank-only component provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hits: tuple[ChunkHit, ...]
    component_rankings: ComponentRankings
```

**What to look for in the code**

- `ComponentRankings` holds only `chunk_id` values. Position in the tuple *is* the rank, so no score has anywhere to hide.
- `hits` is a tuple, not a list. A caller cannot append to or reorder a result that M2.5 already ordered deterministically.
- `RankedChunkId` reuses the `gt=0` constraint, so a placeholder zero cannot enter the provenance record.

## 4. The composition

Eighty lines, and every one of them is arrangement rather than algorithm. Nothing new is computed here; six modules are simply put in the right order.

Order is the whole content of this function, so read it as a sequence of gates. Reject bad arguments before spending anything. Reject a mismatched provider before touching the database. Normalize once, before the paths split. Then, and only then, hand two closures to `hybrid_search` and let it drive.

The closures are the piece worth studying. `hybrid_search` was written in M2.5 knowing nothing about sessions or embedders — and it still needs both. Closing over them here is what lets a database-free library function drive real database work without ever naming it.

### Complete `app/retrieval/service.py` — the retrieve entry point

**Learning action — implement the composition:** write the validation block first, then the dimension check, then the two closures, then the fusion call. Each stage has a reason for its position.

<!-- src: app/retrieval/service.py::retrieve -->
```python
async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    provider: EmbeddingProvider | None = None,
    k: int = 5,
    candidate_k: int | None = None,
    filters: RetrievalFilters | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    reranker: RerankProvider | None = None,
    route_by_language: bool | None = None,
    lexical_ranker: LexicalRanker | None = None,
    bm25_k1: float | None = None,
    bm25_b: float | None = None,
    bm25_idf: BM25Idf | None = None,
) -> RetrievalResult:
    """Run vector then lexical search through one session and fuse their ranks.

    The component adapters close over the same ``AsyncSession``. They are awaited
    sequentially by ``hybrid_search`` because concurrent use of one session is unsafe.
    Component scores stay inside their native lanes; only ranked chunk identities are
    exposed beside the fused hits. An omitted candidate limit expands to
    ``max(20, 4 * k)`` at this production boundary.

    With no reranker the fused list is truncated to ``k`` by fusion itself, which is
    the M2.7 behaviour. Supplying one turns the request into two stages: fusion keeps
    the full candidate list, and the reranker rescores it and returns the top ``k``.
    Retrieval therefore goes wide cheaply first, then narrow expensively.

    Reranked hits carry cross-encoder scores rather than fusion scores. Component
    rankings are unaffected because they record what each retriever proposed, not
    what survived reranking.

    ``route_by_language`` resolves from ``Settings.query_language_routing`` when it is
    omitted. With routing on and a Korean query, the lexical component is skipped and
    ranking is vector-only. The lexical index is built with the ``english`` text-search
    configuration, so that component contributes nothing for Korean anyway; asking it
    anyway costs a database round trip and, worse, gives fusion a component whose
    silence is indistinguishable from a considered "no candidates". A skipped component
    is visible instead: ``ComponentRankings.lexical`` is empty, so the taken route can
    be read off the result rather than inferred from the configuration.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")
    limit = max(20, 4 * k) if candidate_k is None else candidate_k
    if limit < k:
        raise ValueError("candidate_k must be at least k")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    settings = get_settings()
    active_lexical_ranker = settings.lexical_ranker if lexical_ranker is None else lexical_ranker
    active_bm25_k1 = settings.bm25_k1 if bm25_k1 is None else bm25_k1
    active_bm25_b = settings.bm25_b if bm25_b is None else bm25_b
    if active_lexical_ranker not in ("ts_rank_cd", "bm25"):
        raise ValueError("lexical_ranker must be 'ts_rank_cd' or 'bm25'")
    if active_bm25_k1 <= 0:
        raise ValueError("bm25_k1 must be positive")
    if not 0 <= active_bm25_b <= 1:
        raise ValueError("bm25_b must be between 0 and 1")
    active_bm25_idf = settings.bm25_idf if bm25_idf is None else bm25_idf
    if active_bm25_idf not in BM25_IDF_VARIANTS:
        raise ValueError("bm25_idf must be 'lucene' or 'robertson'")
    normalized_query = _normalize_query(query)
    active_routing = (
        settings.query_language_routing if route_by_language is None else route_by_language
    )
    skip_lexical = active_routing and detect_query_language(normalized_query) == "ko"

    active_provider = provider or get_embedding_provider()
    if active_provider.dimensions != DIM:
        raise ValueError(
            f"embedding provider dimension {active_provider.dimensions} does not match "
            f"database dimension {DIM}"
        )

    vector_hits: list[ChunkHit] = []
    lexical_hits: list[ChunkHit] = []

    async def vector_component(
        component_query: str,
        component_k: int,
        component_filters: RetrievalFilters,
    ) -> list[ChunkHit]:
        query_vector = await active_provider.embed_query(component_query)
        hits = await vector_search(
            session,
            query_vector,
            k=component_k,
            filters=component_filters,
        )
        vector_hits.extend(hits)
        return hits

    async def lexical_component(
        component_query: str,
        component_k: int,
        component_filters: RetrievalFilters,
    ) -> list[ChunkHit]:
        if skip_lexical:
            return []
        if active_lexical_ranker == "bm25":
            hits = await bm25_search(
                session,
                component_query,
                component_k,
                component_filters,
                k1=active_bm25_k1,
                b=active_bm25_b,
                idf=active_bm25_idf,
            )
        else:
            hits = await lexical_search(
                session,
                component_query,
                component_k,
                component_filters,
            )
        lexical_hits.extend(hits)
        return hits

    fused = await hybrid_search(
        normalized_query,
        limit if reranker is not None else k,
        filters,
        vector_search=vector_component,
        lexical_search=lexical_component,
        candidate_k=limit,
        rrf_k=rrf_k,
    )
    if reranker is not None:
        fused = await rerank_hits(
            normalized_query,
            fused,
            provider=reranker,
            top_k=k,
        )
    return RetrievalResult(
        hits=tuple(fused),
        component_rankings=ComponentRankings(
            vector=tuple(hit.chunk_id for hit in vector_hits),
            lexical=tuple(hit.chunk_id for hit in lexical_hits),
        ),
    )
```

**What to look for in the code**

- Every validation happens **before any I/O**. No embedding call, no query. A rejected request costs nothing and touches no external service.
- The dimension check compares the provider against `DIM` up front. Without it, a mismatched provider would fail deep inside pgvector with a far less useful message.
- The two closures capture `session` rather than receiving it. That is how one caller-owned session reaches both adapters while `hybrid_search` stays free of any database type.
- `vector_hits` and `lexical_hits` are filled as a **side effect** of the closures. This is how component provenance is captured without changing `hybrid_search`'s signature — the price is that these lists must be read only after fusion has awaited both.
- `candidate_k` defaults to `max(20, 4 * k)` here and not in `hybrid_search`. The library keeps a neutral default; this production boundary states the tuned one.
- `filters` is passed through unnormalized, since `RetrievalFilters` already canonicalized itself in M2.1.

## 5. The command-line acceptance path

Everything up to here is provable by tests. This file is what makes M2 provable by hand.

There is a difference. A green test suite says each contract holds in isolation, with fakes standing in for the parts that are slow or cost money. It does not say that a real query, against a real corpus, through a real PostgreSQL, returns evidence a person would accept.

That is what the acceptance command is for, and it is why its output is JSON rather than prose: the run has to leave a record someone can diff, attach to a report, or feed to M3.

### Create `app/retrieval/__main__.py` — module header

**Learning action — define the structure:** note that this is the first retrieval module allowed to import `app.db.session`.

```python
"""Command-line acceptance path for the M2 retrieval service."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
import json
from typing import Literal

from app.config import Settings, get_settings
from app.db.session import Session
from app.retrieval.embeddings import (
    EmbeddingBackfillResult,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.service import RetrievalResult, retrieve

ProviderName = Literal["deterministic", "openai"]
```

**What to look for in the code**

- `app.db.session` is imported at module top level here, unlike M1.4's `seed.py` which deferred it into a function. That is safe because `__main__.py` is never imported by a test — it exists only to be executed.

## 6. Arguments and output shape

### Extend `app/retrieval/__main__.py` — arguments and payload

**Learning action — write the structure, then inspect the entry contract:** the argument definitions are mechanical. `_payload` is where the no-scores rule is enforced again.

<!-- src: app/retrieval/__main__.py::arguments,_payload -->
```python
def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse retrieval acceptance arguments."""
    parser = argparse.ArgumentParser(description="Run exact hybrid retrieval over PostgreSQL.")
    parser.add_argument("--query", required=True, help="Nonempty retrieval query.")
    parser.add_argument("-k", type=int, default=5, help="Number of fused hits to return.")
    parser.add_argument(
        "--candidate-k",
        type=int,
        help="Candidates per component; defaults to max(20, 4 * k).",
    )
    parser.add_argument(
        "--provider",
        choices=("deterministic", "openai", "sbert"),
        help=(
            "Override EMBEDDING_PROVIDER for this command. Stored embeddings are only "
            "comparable with query embeddings from the same provider, so switching "
            "requires re-embedding every chunk with --embed-missing on an empty column."
        ),
    )
    parser.add_argument(
        "--embed-missing",
        action="store_true",
        help="Fill null chunk embeddings before retrieval.",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Rescore fused candidates with a local cross-encoder before truncating to k.",
    )
    parser.add_argument(
        "--lexical-ranker",
        choices=("ts_rank_cd", "bm25"),
        help="Override LEXICAL_RANKER for this command.",
    )
    parser.add_argument(
        "--bm25-k1",
        type=float,
        help="Override BM25_K1; must be positive.",
    )
    parser.add_argument(
        "--bm25-b",
        type=float,
        help="Override BM25_B; must be between 0 and 1.",
    )
    parser.add_argument(
        "--bm25-idf",
        choices=("lucene", "robertson"),
        help="Override BM25_IDF; 'robertson' can score common terms negatively.",
    )
    parser.add_argument(
        "--rebuild-bm25-stats",
        action="store_true",
        help="Create missing schema objects and atomically rebuild BM25 term statistics.",
    )
    return parser.parse_args(argv)


def _provider_settings(settings: Settings, provider: ProviderName | None) -> Settings:
    """Return settings with an optional validated command-line provider override."""
    if provider is None:
        return settings
    return settings.model_copy(update={"embedding_provider": provider})


def _payload(
    *,
    query: str,
    provider: str,
    backfill: EmbeddingBackfillResult | None,
    result: RetrievalResult,
    lexical_ranker: LexicalRanker = "ts_rank_cd",
    bm25_k1: float = 1.2,
    bm25_b: float = 0.75,
    bm25_idf: BM25Idf = "lucene",
    bm25_stats: TermStatCounts | None = None,
) -> dict[str, object]:
    """Build stable JSON output while keeping component scores private."""
    return {
        "query": query,
        "provider": provider,
        "lexical_ranker": lexical_ranker,
        "bm25_k1": bm25_k1 if lexical_ranker == "bm25" else None,
        "bm25_b": bm25_b if lexical_ranker == "bm25" else None,
        "bm25_idf": bm25_idf if lexical_ranker == "bm25" else None,
        "bm25_stats": asdict(bm25_stats) if bm25_stats is not None else None,
        "backfill": asdict(backfill) if backfill is not None else None,
        "hits": [hit.model_dump(mode="json") for hit in result.hits],
        "component_rankings": result.component_rankings.model_dump(mode="json"),
    }
```

**What to look for in the code**

- `arguments` takes `argv` instead of always reading `sys.argv`, which is what lets tests call it directly.
- `_provider_settings` uses `model_copy` rather than mutating settings, so the cached `get_settings()` object is never altered for the rest of the process.
- `_payload` emits `component_rankings` and never a component score. The rule from the top of this section is enforced at the last boundary too, where it would be easiest to leak.

## 7. Running one request

### Complete `app/retrieval/__main__.py` — the run path

**Learning action — implement the run order:** write `_run` yourself and justify why the backfill sits inside the session but the payload is built outside it.

<!-- src: app/retrieval/__main__.py::_run,main -->
```python
async def _run(args: argparse.Namespace) -> dict[str, object]:
    """Run optional embedding backfill and one retrieval request."""
    settings = _provider_settings(get_settings(), args.provider)
    provider = get_embedding_provider(settings)
    lexical_ranker = args.lexical_ranker or settings.lexical_ranker
    bm25_k1 = settings.bm25_k1 if args.bm25_k1 is None else args.bm25_k1
    bm25_b = settings.bm25_b if args.bm25_b is None else args.bm25_b
    bm25_idf = args.bm25_idf or settings.bm25_idf
    if args.rebuild_bm25_stats:
        await bootstrap_schema(engine)
    async with Session() as session:
        backfill = None
        bm25_stats = None
        if args.rebuild_bm25_stats:
            bm25_stats = await backfill_term_stats(session)
        if args.embed_missing:
            backfill = await embed_missing_chunks(session, provider)
        result = await retrieve(
            session,
            args.query,
            provider=provider,
            k=args.k,
            candidate_k=args.candidate_k,
            reranker=CrossEncoderReranker() if args.rerank else None,
            lexical_ranker=lexical_ranker,
            bm25_k1=bm25_k1,
            bm25_b=bm25_b,
            bm25_idf=bm25_idf,
        )
    return _payload(
        query=args.query,
        provider=settings.embedding_provider,
        backfill=backfill,
        result=result,
        lexical_ranker=lexical_ranker,
        bm25_k1=bm25_k1,
        bm25_b=bm25_b,
        bm25_idf=bm25_idf,
        bm25_stats=bm25_stats,
    )


def main() -> None:
    """Run the M2 acceptance command and print machine-readable evidence."""
    print(json.dumps(asyncio.run(_run(arguments())), indent=2, ensure_ascii=False))
```

Add the module execution guard at the end of the file. Those two lines are what make `python -m app.retrieval` work.

```python
if __name__ == "__main__":
    main()
```

**What to look for in the code**

- One session wraps both the backfill and the retrieval, which is the caller-owned-session decision demonstrated in practice.
- The **same** `provider` instance goes to the backfill and to `retrieve`, so documents and the query are embedded by one model — M2.2's first constraint, honored at the top.
- `_payload` is built after `async with` closes. Nothing in the payload is lazily loaded from the session, so building it outside proves that.
- `ensure_ascii=False` keeps filing text readable in the JSON output instead of escaping it.

## 8. The finished public surface

### Create or replace `app/retrieval/__init__.py` — the M2 public API

**Learning action — replace the existing definition:** this replaces the temporary initializer written in M2.1.

<!-- file: app/retrieval/__init__.py -->
```python
"""Public contracts and production entry points for the retrieval milestone."""

from app.retrieval.bm25 import TermStatCounts, backfill_term_stats, bm25_search
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingBackfillResult,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.hybrid import DEFAULT_RRF_K, hybrid_search, rrf_fuse
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import RerankProvider, rerank_hits
from app.retrieval.sbert import SentenceTransformerEmbeddingProvider
from app.retrieval.service import ComponentRankings, RetrievalResult, retrieve
from app.retrieval.types import ChunkHit, ChunkKind, RetrievalFilters, sort_hits
from app.retrieval.vector import vector_search

__all__ = [
    "DEFAULT_RRF_K",
    "ChunkHit",
    "ChunkKind",
    "ComponentRankings",
    "CrossEncoderReranker",
    "DeterministicEmbeddingProvider",
    "EmbeddingBackfillResult",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "RerankProvider",
    "RetrievalFilters",
    "RetrievalResult",
    "SentenceTransformerEmbeddingProvider",
    "TermStatCounts",
    "backfill_term_stats",
    "bm25_search",
    "embed_missing_chunks",
    "get_embedding_provider",
    "hybrid_search",
    "lexical_search",
    "rerank_hits",
    "retrieve",
    "rrf_fuse",
    "sort_hits",
    "vector_search",
]
```

That last replacement removes the temporary M2.1 initializer. The package now matches the completed retrieval surface.

Note what is **not** exported: `_normalize_query`, `_filtered_statement`, `_filter_predicates`, `validate_embeddings`, and `rrf_fuse`'s helpers. The underscore-prefixed names are internal, and the surface a later module may depend on is exactly this list.

## Focused tests and the contracts they protect

```bash
uv run pytest tests/retrieval/test_07_service.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| Validation moved after the first embed call | A rejected request performs no I/O. |
| A provider whose dimension differs from `DIM` | Mismatches fail early with a clear message. |
| A session created inside the service | The caller keeps transaction control. |
| Different queries reaching the two components | Both lists answer the same question. |
| Concurrent component calls | One `AsyncSession` is never used concurrently. |
| A component score present in the output | Incomparable scores are never republished. |

A clean pass means all service tests pass for pre-I/O validation, one-session ownership, sequential call order, `R&D` normalization, RRF composition, provenance, and CLI output.

The rule for moving on is simple: do not accept M2.7 if validation performs I/O, the session identity or call order changes, query normalization diverges, or raw component scores leak.

When it fails, use the first failed mock assertion as the boundary. Confirm that validation precedes `embed_query`, both searches receive the same normalized query and filters, and the caller-owned `AsyncSession` is never replaced or closed.

## What you should be able to explain now

- **What does M5 lose if the service creates its own session?**
  - **Answer:** M5 loses request-level transaction and lifecycle control, because retrieval can no longer participate in the caller's existing session.
- **Why are ranks published while scores are not?**
  - **Answer:** Rank positions have the same meaning across retrievers, while their raw scores do not; exposing scores would invite invalid thresholds, averages, and comparisons.
- **What breaks if only one of the two paths sees the normalized query?**
  - **Answer:** The component lists answer different questions, so their fused result and any attribution of it become invalid.
- **How does one session reach both adapters without `hybrid_search` knowing about it?**
  - **Answer:** `retrieve` defines two adapter closures that capture the caller-owned session, then passes those database-agnostic callables to `hybrid_search`.
- **Why may `__main__.py` import `app.db.session` at module level when `seed.py` may not?**
  - **Answer:** Offline tests do import `app.retrieval.__main__`, so the claim that tests never import it is false. Importing `app.db.session` creates an engine object but opens no connection; `seed.py` defers even that setup because it is a more broadly reusable library boundary.

---

[← Previous: Fusion](04-fusion.md) · [Module overview](../03-build.md) · [Next →: Live PostgreSQL](06-live-postgres.md)
