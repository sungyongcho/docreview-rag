# M2 Build — Retrieval, Built Outward from the Evidence

## There are 9,172 chunks in the database. Now find them

M1 is done. PostgreSQL holds 20 documents and 9,172 chunks, each carrying source coordinates and a citation label. The `embedding` column is `NULL` everywhere.

Now a question like "what are NVIDIA's 2024 risk factors?" has to find the relevant chunks.

Retrieval code is **easy to make impressive and hard to make trustworthy.** Bolt on an embedding library, take the top 10 by cosine similarity, and it works in thirty minutes. The problem is that nobody knows whether it is any good.

So this chapter takes the order below. **Fix the identity of one piece of evidence first**, build two deliberately different search paths, and only then compose them into a single request.

## Why there are two retrieval paths

There is a reason not to stop at vector search. The two are good at different things.

| | Vector (dense) | Lexical (sparse) |
|---|---|---|
| Method | semantic embedding cosine similarity | PostgreSQL full-text search |
| Strength | finds it despite different wording | exact terms, numbers, proper nouns |
| Weakness | weak on numbers like `26,974` | knows no synonyms |

10-K retrieval needs both. A question like "supply chain risk" has many phrasings and favors vectors; exact tokens like "Item 7A" or a specific dollar amount favor lexical search.

So the two are built separately and fused with **RRF (Reciprocal Rank Fusion)**. It mixes **ranks** rather than scores, for reasons covered in M2.5.

## What you will build

| Step | Concept | Source | Primary test |
|---|---|---|---|
| M2.1 | Evidence and filters are strict values | `types.py` | `test_01_contract.py` |
| M2.2 | Embedding is an async provider boundary | `embeddings.py` | `test_02_embeddings.py` |
| M2.3 | Dense retrieval is exact cosine SQL | `vector.py` | `test_03_vector.py` |
| M2.4 | Lexical retrieval is PostgreSQL FTS | `lexical.py` | `test_04_lexical.py` |
| M2.5 | Fusion consumes ranks | `hybrid.py` | `test_05_hybrid.py` |
| M2.6 | Reranking is an optional provider | `rerank.py` | `test_06_rerank.py` |
| M2.7 | Production composition owns one session | `service.py`, `__main__.py` | `test_07_service.py` |
| M2.8 | A fresh database enables pgvector first | `bootstrap.py` | `test_08_postgres.py` |

The path one request travels:

```text
null Chunk.embedding -> embed_missing_chunks -> populated document vectors

query + filters -> embedding provider -> vector_search  ---+
query + filters ---------------------> lexical_search ---+-> rrf_fuse -> RetrievalResult

candidate hits + optional provider -> rerank_hits
bootstrap_schema -> pgvector extension -> tables -> live PostgreSQL proof
```

The two retrieval paths **meet only at rank fusion.** Until then they know nothing of each other, which is what lets each be tested and replaced independently. Reranking is a separate helper, and the default service ends at `RetrievalResult` after RRF.

## Starting conditions

Install the locked environment and prove the M1.4 boundary first.

```bash
uv sync --group dev
uv run pytest tests/db -q
```

This chapter's reference tests compile PostgreSQL SQL and verify it without a database. Only M2.8 probes a real database for three seconds and skips that one test if it cannot connect.

At each checkpoint, read the design pressure first, write the code at the named canonical `app/...` path, then run the command immediately below. The code always comes before its test. Work directly on `zero` and do not create `_mine.py` files or redirect the tests.


---

## Tutorial — built in nine sittings

M2 produces twelve files. That is more than one sitting, so it is split into nine stretches, each finished and closed by a test. Each document targets **under 30 minutes** to read and implement.

| Document | Covers | Files built | Approx. |
|---|---|---|---|
| [1. Contracts](tutorial/01-contracts.md) | M2.1 | `types.py`, temporary `__init__.py` | 20 min |
| [2. Embeddings](tutorial/02-embeddings.md) | M2.2 | `embeddings.py` | 30 min |
| [3. Retrieval paths](tutorial/03-retrieval-paths.md) | M2.3–M2.4 | `vector.py`, `lexical.py` | 30 min |
| [4. Fusion](tutorial/04-fusion.md) | M2.5–M2.6 | `hybrid.py`, `rerank.py` | 25 min |
| [5. Service](tutorial/05-service.md) | M2.7 | `service.py`, `__main__.py`, `__init__.py` | 30 min |
| [6. Live PostgreSQL](tutorial/06-live-postgres.md) | M2.8 + acceptance | no new files | 20 min |
| [7. BM25](tutorial/07-bm25.md) | M2.9 | `bm25.py`, term statistics tables | 35 min |
| [8. Local embeddings](tutorial/08-local-embeddings.md) | M2.10 | `sbert.py` | 30 min |
| [9. Cross-encoder](tutorial/09-cross-encoder.md) | M2.11 | `cross_encoder.py` | 30 min |

Follow them in order. Do not move on while a stretch's focused test is failing.

The [reference baseline](#reference-baseline--the-complete-canonical-files) below is not a shortcut past the learning; it is the **standard you check your own work against**. Compare after finishing each stretch, never before.

---

## Not all eleven stretches are equally hard

Eleven looks like a lot, but they fall into three kinds. Making that split first decides where the time goes.

| Kind | Checkpoints | Learning action |
|---|---|---|
| Contract declaration | M2.1 | **Write the model declarations** — just confirm which invalid states become unrepresentable |
| Algorithm | M2.3, M2.4, M2.5, M2.9 | **Implement** the queries yourself — spend the time here |
| Boundaries and arrangement | M2.2, M2.6, M2.7, M2.8, M2.10, M2.11 | **Write the structure, then review the call order** |

If time is short, linger longest on RRF in M2.5. The other ten are preparation for that one summation.

## Concepts you meet here first

If RAG is new to you, the following four probably appear here for the first time. Settle them before reading code.

**Embedding.** A piece of text turned into a fixed-length vector of real numbers — in this project one chunk becomes 384 numbers. Those numbers are not human-interpretable; they are the output of a model trained so that texts with similar meaning land near each other in the vector space. One property matters most: **only vectors from the same model can be compared.** Embed documents with model A and questions with model B and the two vectors have no relationship at all.

**Cosine similarity.** Similarity measured as the angle between two vectors, using direction only, never length. A long paragraph and a short sentence on the same topic point in a similar direction even though their lengths differ, so the measure is not swayed by text length. Values run from −1 to 1, and closer to 1 means more similar.

**Dense and sparse.** Embedding search is called dense because nearly every position in the vector holds a non-zero value. Lexical search is sparse: its vector is the size of the vocabulary and only the positions of words that actually occur hold a value. The names come from the storage shape, but the real difference is **searching by meaning versus searching by characters**.

**Reranking.** Both retrievers above embed the question and the document **separately** and then compare (a bi-encoder). That is fast, but it never reads the question and the document side by side. A reranking model takes the question and a candidate **together** and re-scores relevance (a cross-encoder). It is more accurate but costs one model call per candidate, so it is applied only to the top few. This chapter builds the boundary without switching it on — whether to switch it on is decided by measurement in M3.

## M2.1 — Make evidence impossible to blur

Fix what a single retrieval result is before anything else. A hit carries not just a chunk id and a score but the source coordinates and the citation label, and no field can be filled in later. Filters follow the same principle, so ticker and year are validated values rather than free strings. Let this contract wobble and no later ranking can say what it is a ranking of.

**Document:** [1. Contracts](tutorial/01-contracts.md) · **Passing:** `uv run pytest tests/retrieval/test_01_contract.py -q`

## M2.2 — Separate provider I/O from persistence

Embedding is a network call; storing is a transaction. Overlap them and a database transaction stays open while a slow HTTP response is awaited. So calls and writes are split into batches, with a stale guard covering the chance that a chunk's text changed in between. That is also why a deterministic offline provider is built alongside — retrieval quality cannot be measured by tests that depend on the network.

**Document:** [2. Embeddings](tutorial/02-embeddings.md) · **Passing:** `uv run pytest tests/retrieval/test_02_embeddings.py -q`

## M2.3 — Establish exact cosine retrieval

The first vector search uses exact cosine with no approximate index. At this scale a full scan is fast enough, and more importantly it **creates the baseline to compare against when an approximate index is switched on later**. An approximate index like HNSW buys speed by missing some true neighbours, and without a baseline there is no way to say how many. That baseline is built here.

**Document:** [3. Retrieval paths](tutorial/03-retrieval-paths.md) · **Passing:** `uv run pytest tests/retrieval/test_03_vector.py -q`

## M2.4 — Add a safe lexical floor

Vector search is weak on exact tokens like `26,974`. PostgreSQL full-text search holds that floor. The care needed here is in handling the query string: feed raw user input straight into full-text syntax and a syntax error kills the whole request. So the input is split into tokens and reassembled safely.

**Document:** [3. Retrieval paths](tutorial/03-retrieval-paths.md) · **Passing:** `uv run pytest tests/retrieval/test_04_lexical.py -q`

## M2.5 — Fuse positions, not incompatible scores

The two retrievers' scores use different units. Cosine runs from −1 to 1; a full-text rank has no upper bound. Normalize and add them and the choice of normalization drives the result, so the moment one retriever's score distribution shifts the fused output moves with it, silently. RRF discards the scores and uses **rank alone**: placing r-th in a list contributes `1 / (rrf_k + r)`, and the sums are sorted. With no units involved, no normalization is needed.

**Document:** [4. Fusion](tutorial/04-fusion.md) · **Passing:** `uv run pytest tests/retrieval/test_05_hybrid.py -q`

## M2.6 — Keep reranking optional

The reranking boundary gets built but stays off in the default path. Switching it on looks appealing, but it adds cost and latency per call and **there is currently no way to measure whether it helped**. The measuring apparatus arrives in M3. Until then it stays a replaceable boundary, and the default service ends at the RRF result.

**Document:** [4. Fusion](tutorial/04-fusion.md) · **Passing:** `uv run pytest tests/retrieval/test_06_rerank.py -q`

## M2.7 — Compose one production request

The pieces so far get bound into a single request. Session ownership is the crux. If vector search and lexical search each open their own session, they can observe different snapshots within one request. So the composition step creates one session and hands it to both, and the retrieval functions never create one.

**Document:** [5. Service](tutorial/05-service.md) · **Passing:** `uv run pytest tests/retrieval/test_07_service.py -q`

## M2.8 — Bootstrap and prove PostgreSQL end to end

The previous seven stretches verified SQL by compiling it without a database. Finally, connect to a real PostgreSQL and run the whole path through once. On a fresh database the pgvector extension has to be enabled before the tables can be created, so the bootstrap order itself is the content of this stretch.

**Document:** [6. Live PostgreSQL](tutorial/06-live-postgres.md) · **Passing:** `uv run pytest tests/retrieval/test_08_postgres.py -q`

## M2.9 — Rank with corpus statistics, then measure

M2.4's lexical floor scores one document in isolation. BM25 adds what that floor cannot see: how rare a word is across the whole corpus, how quickly repetition should stop paying, and how much a chunk's length flatters it. Every statistic behind it is derived from the `content_tsv` column that already exists.

**Document:** [7. BM25](tutorial/07-bm25.md) · **Passing:** `uv run pytest tests/retrieval/test_09_bm25.py -q`

## M2.10 — Take the dependency, once there is a reason

Everything through M2.9 runs with no machine-learning dependency at all. This stretch installs PyTorch, picks a backend from the workload rather than from the hardware on hand, and puts a local bi-encoder behind the embedding boundary. The lesson that matters most is the failure it introduces: vectors from two providers do not share a space, and mixing them raises nothing.

**Document:** [8. Local embeddings](tutorial/08-local-embeddings.md) · **Passing:** `uv run pytest tests/retrieval/test_10_sbert.py -q`

## M2.11 — Fill the boundary M2.6 left open

A cross-encoder reads the query and the document together instead of separately, which is more accurate and costs one forward pass per candidate. That price is what makes retrieval two-stage: cheap and wide first, expensive and narrow second. Attaching it costs one optional parameter, which is the return on the boundary drawn five checkpoints earlier.

**Document:** [9. Cross-encoder](tutorial/09-cross-encoder.md) · **Passing:** `uv run pytest tests/retrieval/test_11_cross_encoder.py -q`

## What you should be able to explain now

- **Why must documents and questions go through the same embedding path?**
  - **Answer:** Only vectors produced by the same model inhabit a comparable space; otherwise their cosine similarity is meaningless.
- **What exactly becomes risky when a network call and a transaction overlap?**
  - **Answer:** Slow or failed network I/O keeps database locks and the connection open, increasing contention, and a timeout can roll back work already completed in that transaction.
- **Why was an approximate index not switched on from the start?**
  - **Answer:** Exact search provides the recall baseline needed to measure how many true neighbours an approximate index misses, and a full scan is still affordable at this corpus size.
- **Why is normalizing and adding scores worse than RRF?**
  - **Answer:** Vector and lexical scores use incompatible units, while normalization makes the result depend on each query's score distribution. RRF avoids both problems by combining ranks only.
- **What breaks if a retrieval function creates its own session?**
  - **Answer:** The caller loses control of transaction scope and can no longer coordinate retrieval with the rest of the request on one session.
- **What justifies building reranking and leaving it off?**
  - **Answer:** Reranking adds cost and latency, but M2 has no evidence that it improves this corpus, and the current M3 experiment matrix does not measure it either. Keeping the boundary disabled avoids paying for it until a future experiment explicitly adds a reranking arm.

## What this module hands to the next one

After M2, a question finds evidence chunks. But **whether those are good results is still unknown.** Every decision deferred in this chapter therefore rolls into M3.

| What M2 produced | Receiver | What happens there |
|---|---|---|
| the `retrieve()` service entry point | **M4** | the workflow's retrieve node |
| `RetrievalResult.hits` | **M4** | evidence handed to the LLM |
| `component_rankings` | **M3** | analysis of which retriever contributed |
| `RetrievalFilters` | **M5** | ticker and year filters on API requests |
| the exact cosine baseline | **M3** | comparison target when an approximate index arrives |
| `rrf_k` default of 60 | **M3** | an ablation parameter |
| the `RerankProvider` boundary (unused) | **M3** | measurement decides whether to turn it on |

M2 deferred to M3 three times: not building HNSW, not enabling reranking, leaving `rrf_k` at 60. All of them are **decisions that cannot be made without measurement.**

The next chapter, M3, builds that measuring instrument. The key move is defining golden answers as **source coordinate ranges** rather than chunk IDs, which is what makes it possible to compare across chunk sizes. M1.3's coordinate-based citation design pays off one last time there.

<!-- complete-files:start -->
## Reference baseline — the complete canonical files

Create or replace the canonical paths below directly. Do not create `_mine.py` or another learner-copy module. The earlier excerpts explain individual decisions; the blocks in this section are the finished files to compare against once a checkpoint is done. Preserve the shown type annotations and English comments; `pyproject.toml` is the authoritative Ruff policy.

### M2.1 — Complete checkpoint

#### Create or replace `app/retrieval/__init__.py`

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

#### Create or replace `app/retrieval/types.py`

<!-- file: app/retrieval/types.py -->
```python
"""Shared value objects and deterministic ordering for retrieval results."""

from collections.abc import Iterable
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator

ChunkKind = Literal["text", "table"]

ChunkId = Annotated[StrictInt, Field(gt=0)]
DocId = Annotated[StrictStr, Field(min_length=1, max_length=32)]
Ticker = Annotated[StrictStr, Field(min_length=1, max_length=16)]
FiscalYear = Annotated[StrictInt, Field(gt=0)]
Form = Annotated[StrictStr, Field(min_length=1, max_length=16)]
Item = Annotated[StrictStr, Field(min_length=1, max_length=8)]
SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Score = Annotated[StrictFloat, Field(allow_inf_nan=False)]


class ChunkHit(BaseModel):
    """One scored database chunk with human and machine citation data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: ChunkId
    doc_id: DocId
    item: Item | None
    kind: ChunkKind
    citation: Annotated[StrictStr, Field(min_length=1)]
    start_char: Annotated[StrictInt, Field(ge=0)]
    end_char: Annotated[StrictInt, Field(gt=0)]
    source_sha256: SourceSha256
    body: Annotated[StrictStr, Field(min_length=1)]
    context_header: StrictStr
    index_text: Annotated[StrictStr, Field(min_length=1)]
    score: Score

    @model_validator(mode="after")
    def validate_source_and_index_text(self) -> Self:
        """Reject invalid spans and indexed text detached from its evidence."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")

        expected = f"{self.context_header}\n\n{self.body}" if self.context_header else self.body
        if self.index_text != expected:
            raise ValueError("index_text must equal context_header plus body")
        return self


class RetrievalFilters(BaseModel):
    """Optional exact-match restrictions shared by every retrieval strategy.

    Values within a field are alternatives, while populated fields are combined.
    Empty tuples mean that the corresponding database dimension is unrestricted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_ids: tuple[DocId, ...] = ()
    tickers: tuple[Ticker, ...] = ()
    fiscal_years: tuple[FiscalYear, ...] = ()
    forms: tuple[Form, ...] = ()
    items: tuple[Item | None, ...] = ()
    kinds: tuple[ChunkKind, ...] = ()

    @field_validator("doc_ids", "tickers", "forms", mode="after")
    @classmethod
    def canonicalize_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Remove duplicates and make equivalent string filters serialize equally."""
        return tuple(sorted(set(values)))

    @field_validator("fiscal_years", mode="after")
    @classmethod
    def canonicalize_years(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        """Remove duplicate years and store them in ascending order."""
        return tuple(sorted(set(values)))

    @field_validator("items", mode="after")
    @classmethod
    def canonicalize_items(cls, values: tuple[str | None, ...]) -> tuple[str | None, ...]:
        """Canonicalize Item filters while retaining support for unnumbered sections."""
        return tuple(sorted(set(values), key=lambda item: (item is not None, item or "")))

    @field_validator("kinds", mode="after")
    @classmethod
    def canonicalize_kinds(cls, values: tuple[ChunkKind, ...]) -> tuple[ChunkKind, ...]:
        """Canonicalize kinds in the schema's text-then-table order."""
        order = {"text": 0, "table": 1}
        return tuple(sorted(set(values), key=order.__getitem__))


def sort_hits(hits: Iterable[ChunkHit]) -> list[ChunkHit]:
    """Return hits in deterministic relevance order without mutating the input.

    Higher scores sort first. Equal scores use the stable source citation identity,
    followed by the database chunk id as a final unique tie-breaker.
    """
    return sorted(
        hits,
        key=lambda hit: (
            -hit.score,
            hit.doc_id,
            hit.source_sha256,
            hit.start_char,
            hit.end_char,
            hit.chunk_id,
        ),
    )
```

Run the checkpoint:

```bash
uv run pytest tests/retrieval/test_01_contract.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M2.2 — Complete checkpoint

#### Create or replace `app/retrieval/embeddings.py`

<!-- file: app/retrieval/embeddings.py -->
```python
"""Async embedding providers and resumable PostgreSQL embedding backfill."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import math
from numbers import Real
import re
import unicodedata

from openai import AsyncOpenAI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Chunk


def _texts(values: Sequence[str]) -> list[str]:
    """Return validated, materialized embedding inputs."""
    texts = list(values)
    if any(not isinstance(text, str) or not text for text in texts):
        raise ValueError("embedding inputs must be nonempty strings")
    return texts


def validate_embeddings(
    values: Sequence[Sequence[float]], *, expected_count: int, dimensions: int
) -> list[list[float]]:
    """Validate provider output before it crosses the database boundary."""
    if dimensions <= 0:
        raise ValueError("embedding dimensions must be positive")
    if len(values) != expected_count:
        raise ValueError(
            f"embedding provider returned {len(values)} vectors for {expected_count} inputs"
        )

    vectors: list[list[float]] = []
    for position, value in enumerate(values):
        if len(value) != dimensions:
            raise ValueError(
                f"embedding {position} has dimension {len(value)}, expected {dimensions}"
            )
        vector: list[float] = []
        for component in value:
            if isinstance(component, bool) or not isinstance(component, Real):
                raise ValueError(f"embedding {position} contains a nonnumeric component")
            number = float(component)
            if not math.isfinite(number):
                raise ValueError(f"embedding {position} contains a non-finite component")
            vector.append(number)
        vectors.append(vector)
    return vectors


class EmbeddingProvider(ABC):
    """Async provider boundary shared by query and document embeddings."""

    dimensions: int

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch in caller order."""

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query through the same model and validation path."""
        return (await self.embed_documents([text]))[0]


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Stable token-hashing vectors for tests and local exercises."""

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        self.dimensions = dimensions

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Hash normalized alphanumeric tokens into unit-length bag-of-words vectors."""
        inputs = _texts(texts)
        vectors: list[list[float]] = []
        for text in inputs:
            normalized = unicodedata.normalize("NFKC", text).casefold()
            tokens = re.findall(r"[^\W_]+", normalized)
            if not tokens:
                tokens = ["<empty>"]
            vector = [0.0] * self.dimensions
            for token in tokens:
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                dimension = int.from_bytes(digest[:8], "big") % self.dimensions
                sign = 1.0 if digest[8] & 1 else -1.0
                vector[dimension] += sign
            norm = math.sqrt(sum(component * component for component in vector))
            if norm == 0.0:
                digest = hashlib.sha256(" ".join(tokens).encode("utf-8")).digest()
                vector[int.from_bytes(digest[:8], "big") % self.dimensions] = 1.0
                norm = 1.0
            vectors.append([component / norm for component in vector])
        return validate_embeddings(
            vectors,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider with explicit output dimensions."""

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        dimensions: int = 384,
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
    ) -> None:
        if not model:
            raise ValueError("embedding model must be nonempty")
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        self.model = model
        self.dimensions = dimensions
        self._client = client or AsyncOpenAI(api_key=api_key)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed one batch and restore caller order from response indices."""
        inputs = _texts(texts)
        if not inputs:
            return []

        response = await self._client.embeddings.create(
            input=inputs,
            model=self.model,
            dimensions=self.dimensions,
            encoding_format="float",
        )
        by_index: dict[int, Sequence[float]] = {}
        for item in response.data:
            if not isinstance(item.index, int) or item.index in by_index:
                raise ValueError("embedding provider returned invalid response indices")
            by_index[item.index] = item.embedding
        if set(by_index) != set(range(len(inputs))):
            raise ValueError("embedding provider returned incomplete response indices")
        ordered = [by_index[index] for index in range(len(inputs))]
        return validate_embeddings(
            ordered,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )


def get_embedding_provider(
    settings: Settings | None = None, *, client: AsyncOpenAI | None = None
) -> EmbeddingProvider:
    """Build the configured provider without doing work at import time."""
    configured = settings or get_settings()
    if configured.embedding_provider == "deterministic":
        return DeterministicEmbeddingProvider(configured.embed_dim)
    if configured.embedding_provider == "sbert":
        # Imported here, not at module scope: app.retrieval.sbert imports this
        # module for the provider base class and its validation helpers.
        from app.retrieval.sbert import SentenceTransformerEmbeddingProvider

        return SentenceTransformerEmbeddingProvider(
            model=configured.sbert_model,
            dimensions=configured.embed_dim,
        )
    api_key = configured.openai_api_key.get_secret_value() if configured.openai_api_key else None
    return OpenAIEmbeddingProvider(
        model=configured.embedding_model,
        dimensions=configured.embed_dim,
        client=client,
        api_key=api_key,
    )


@dataclass(frozen=True, slots=True)
class PendingEmbedding:
    """One immutable database input selected for embedding."""

    chunk_id: int
    index_text: str


@dataclass(frozen=True, slots=True)
class EmbeddingBackfillResult:
    """Observable result of a resumable embedding backfill."""

    selected: int
    embedded: int
    skipped_stale: int
    batches: int


async def _missing_batch(session: AsyncSession, batch_size: int) -> list[PendingEmbedding]:
    """Load one stable batch and close its transaction before provider I/O."""
    async with session.begin():
        rows = (
            await session.execute(
                select(Chunk.id, Chunk.index_text)
                .where(Chunk.embedding.is_(None))
                .order_by(Chunk.id)
                .limit(batch_size)
            )
        ).all()
    return [PendingEmbedding(chunk_id=row.id, index_text=row.index_text) for row in rows]


async def _store_batch(
    session: AsyncSession,
    pending: Sequence[PendingEmbedding],
    vectors: Sequence[Sequence[float]],
) -> int:
    """Store current vectors and reject rows changed while the provider was running."""
    embedded = 0
    async with session.begin():
        for item, vector in zip(pending, vectors, strict=True):
            result = await session.execute(
                update(Chunk)
                .where(
                    Chunk.id == item.chunk_id,
                    Chunk.embedding.is_(None),
                    Chunk.index_text == item.index_text,
                )
                .values(embedding=list(vector))
            )
            if result.rowcount == 1:
                embedded += 1
    return embedded


async def embed_missing_chunks(
    session: AsyncSession,
    provider: EmbeddingProvider,
    *,
    batch_size: int | None = None,
) -> EmbeddingBackfillResult:
    """Embed all currently missing chunks in bounded, resumable batches."""
    effective_batch_size = get_settings().embedding_batch_size if batch_size is None else batch_size
    if effective_batch_size <= 0:
        raise ValueError("embedding batch size must be positive")
    if session.in_transaction():
        raise RuntimeError("embed_missing_chunks requires a session without an active transaction")

    selected = embedded = skipped_stale = batches = 0
    while pending := await _missing_batch(session, effective_batch_size):
        batches += 1
        selected += len(pending)
        vectors = await provider.embed_documents([item.index_text for item in pending])
        vectors = validate_embeddings(
            vectors,
            expected_count=len(pending),
            dimensions=provider.dimensions,
        )
        stored = await _store_batch(session, pending, vectors)
        embedded += stored
        skipped_stale += len(pending) - stored

    return EmbeddingBackfillResult(
        selected=selected,
        embedded=embedded,
        skipped_stale=skipped_stale,
        batches=batches,
    )
```

Run the checkpoint:

```bash
uv run pytest tests/retrieval/test_02_embeddings.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M2.3 — Complete checkpoint

#### Create or replace `app/retrieval/vector.py`

<!-- file: app/retrieval/vector.py -->
```python
"""Filtered, deterministic pgvector cosine retrieval."""

from collections.abc import Sequence
import math
from numbers import Real
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DIM, Chunk, Document
from app.retrieval.types import ChunkHit, RetrievalFilters


def validate_query_vector(values: Sequence[float], *, dimensions: int = DIM) -> list[float]:
    """Return a finite vector whose shape matches the database column."""
    if len(values) != dimensions:
        raise ValueError(f"query vector has dimension {len(values)}, expected {dimensions}")
    vector: list[float] = []
    for component in values:
        if isinstance(component, bool) or not isinstance(component, Real):
            raise ValueError("query vector contains a nonnumeric component")
        number = float(component)
        if not math.isfinite(number):
            raise ValueError("query vector contains a non-finite component")
        vector.append(number)
    return vector


def _filtered_statement(statement: Select[Any], filters: RetrievalFilters) -> Select[Any]:
    """Apply exact-match chunk and document filters with AND semantics."""
    if filters.tickers or filters.fiscal_years or filters.forms:
        statement = statement.join(Document, Document.doc_id == Chunk.doc_id)
    if filters.doc_ids:
        statement = statement.where(Chunk.doc_id.in_(filters.doc_ids))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates = []
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        statement = statement.where(or_(*item_predicates))
    if filters.kinds:
        statement = statement.where(Chunk.kind.in_(filters.kinds))
    if filters.tickers:
        statement = statement.where(Document.ticker.in_(filters.tickers))
    if filters.fiscal_years:
        statement = statement.where(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        statement = statement.where(Document.form.in_(filters.forms))
    return statement


def vector_search_statement(
    query_vector: Sequence[float],
    *,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build the exact cosine query used by runtime and SQL contract tests."""
    if k <= 0:
        raise ValueError("vector search k must be positive")
    vector = validate_query_vector(query_vector)
    restrictions = filters or RetrievalFilters()
    distance = Chunk.embedding.cosine_distance(vector).label("distance")
    statement = select(Chunk, distance).where(Chunk.embedding.is_not(None))
    statement = _filtered_statement(statement, restrictions)
    return statement.order_by(
        distance.asc(),
        Chunk.doc_id.asc(),
        Chunk.source_sha256.asc(),
        Chunk.start_char.asc(),
        Chunk.end_char.asc(),
        Chunk.id.asc(),
    ).limit(k)


async def vector_search(
    session: AsyncSession,
    query_vector: Sequence[float],
    *,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Return complete chunk evidence ordered by cosine similarity."""
    if k < 0:
        raise ValueError("vector search k must not be negative")
    if k == 0:
        return []

    statement = vector_search_statement(query_vector, k=k, filters=filters)
    rows = (await session.execute(statement)).all()
    return [
        ChunkHit(
            chunk_id=chunk.id,
            doc_id=chunk.doc_id,
            item=chunk.item,
            kind=chunk.kind,
            citation=chunk.citation,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            source_sha256=chunk.source_sha256,
            body=chunk.body,
            context_header=chunk.context_header,
            index_text=chunk.index_text,
            score=1.0 - float(distance),
        )
        for chunk, distance in rows
    ]
```

Run the checkpoint:

```bash
uv run pytest tests/retrieval/test_03_vector.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M2.4 — Complete checkpoint

#### Create or replace `app/retrieval/lexical.py`

<!-- file: app/retrieval/lexical.py -->
```python
"""PostgreSQL full-text lexical retrieval.

This is the project's mandatory lexical baseline. It uses PostgreSQL full-text
search with cover-density ranking; ``ts_rank_cd`` is not literal BM25.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Chunk, Document
from app.retrieval.types import ChunkHit, RetrievalFilters

TEXT_SEARCH_CONFIG = "english"

# ``ts_rank_cd`` normalization bitmask (PostgreSQL, "Ranking Search Results").
# Bit 4 divides the rank by the mean harmonic distance between extents, so query
# terms that appear close together outrank the same terms scattered apart; bit 1
# divides by ``1 + log(document length)``, so a long chunk stuffed with one common
# term cannot outrank a short chunk that actually answers. With the default of 0,
# rank degenerates into occurrence counting and, measured on the golden suite,
# recall@5 is exactly zero; 4|1 is the best-scoring native combination.
TS_RANK_NORMALIZATION = 4 | 1


def _filter_predicates(filters: RetrievalFilters) -> tuple[ColumnElement[bool], ...]:
    """Translate the shared exact-match filters to composable SQL predicates."""
    predicates: list[ColumnElement[bool]] = []
    if filters.doc_ids:
        predicates.append(Chunk.doc_id.in_(filters.doc_ids))
    if filters.tickers:
        predicates.append(Document.ticker.in_(filters.tickers))
    if filters.fiscal_years:
        predicates.append(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        predicates.append(Document.form.in_(filters.forms))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates: list[ColumnElement[bool]] = []
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        predicates.append(or_(*item_predicates))
    if filters.kinds:
        predicates.append(Chunk.kind.in_(filters.kinds))
    return tuple(predicates)


def lexical_statement(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build a safe PostgreSQL FTS statement ranked by cover density.

    ``websearch_to_tsquery`` accepts raw user text without exposing ``to_tsquery``
    syntax errors, and SQLAlchemy binds ``query`` as a value instead of interpolating
    it. But its output joins every content lexeme with ``&``: a natural-language
    question like "What was the total revenue reported for fiscal 2024?" becomes
    five AND-ed stems, and only a chunk containing all five matches. On this corpus
    that describes almost no chunk, and the baseline silently returns nothing.

    The statement therefore relaxes the parsed query before using it. The tsquery's
    text form quotes each lexeme and can never contain ``&`` inside one, so
    rewriting ``&`` to ``|`` and reparsing with ``to_tsquery`` turns the conjunction
    into a disjunction while leaving quoted phrases (``<->``) intact. Matching any
    query term is enough to become a candidate, and ``TS_RANK_NORMALIZATION`` makes
    the ranking prefer chunks where more of the query co-occurs closely over chunks
    that merely repeat one common term. One semantic is knowingly weakened: an
    explicit ``-term`` exclusion is relaxed along with everything else.

    PostgreSQL FTS is the lexical baseline here; this statement does not implement BM25.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")

    active_filters = filters or RetrievalFilters()
    parsed = func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, query)
    tsquery = func.to_tsquery(TEXT_SEARCH_CONFIG, func.replace(cast(parsed, Text), "&", "|"))
    score = func.ts_rank_cd(Chunk.content_tsv, tsquery, TS_RANK_NORMALIZATION).label("score")
    return (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.doc_id,
            Chunk.item,
            Chunk.kind,
            Chunk.citation,
            Chunk.start_char,
            Chunk.end_char,
            Chunk.source_sha256,
            Chunk.body,
            Chunk.context_header,
            Chunk.index_text,
            score,
        )
        .join(Document, Document.doc_id == Chunk.doc_id)
        .where(Chunk.content_tsv.op("@@")(tsquery), *_filter_predicates(active_filters))
        .order_by(
            score.desc(),
            Chunk.doc_id.asc(),
            Chunk.source_sha256.asc(),
            Chunk.start_char.asc(),
            Chunk.end_char.asc(),
            Chunk.id.asc(),
        )
        .limit(k)
    )


async def lexical_search(
    session: AsyncSession,
    query: str,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Run the PostgreSQL FTS baseline and return typed, deterministically ordered hits.

    The returned score is the native ``ts_rank_cd`` cover-density score, not BM25
    and not a probability. Fusion must consume its rank instead of comparing this
    value directly with another retrieval strategy's score.
    """
    result = await session.execute(lexical_statement(query, k, filters))
    return [ChunkHit.model_validate(row) for row in result.mappings().all()]
```

Run the checkpoint:

```bash
uv run pytest tests/retrieval/test_04_lexical.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M2.5 — Complete checkpoint

#### Create or replace `app/retrieval/hybrid.py`

<!-- file: app/retrieval/hybrid.py -->
```python
"""Rank-only reciprocal rank fusion and thin hybrid orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.retrieval.types import ChunkHit, RetrievalFilters, sort_hits

DEFAULT_RRF_K = 60

SearchCallable = Callable[[str, int, RetrievalFilters], Awaitable[list[ChunkHit]]]


@dataclass(slots=True)
class _FusedHit:
    hit: ChunkHit
    score: float = 0.0


def _unique_ranked_hits(hits: Sequence[ChunkHit]) -> list[ChunkHit]:
    """Keep the first occurrence of each chunk so one list contributes one rank."""
    seen: set[int] = set()
    unique: list[ChunkHit] = []
    for hit in hits:
        if hit.chunk_id not in seen:
            seen.add(hit.chunk_id)
            unique.append(hit)
    return unique


def rrf_fuse(
    vector_hits: Sequence[ChunkHit],
    lexical_hits: Sequence[ChunkHit],
    k: int,
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Fuse ranked lists by reciprocal rank, keyed by database ``chunk_id``.

    Source scores are intentionally ignored because vector similarity and PostgreSQL
    FTS cover-density scores have unrelated scales. Each list contributes
    ``1 / (rrf_k + rank)`` once per chunk, where rank is one-based.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    fused: dict[int, _FusedHit] = {}
    for ranking in (vector_hits, lexical_hits):
        for rank, hit in enumerate(_unique_ranked_hits(ranking), start=1):
            contribution = 1.0 / (rrf_k + rank)
            entry = fused.get(hit.chunk_id)
            if entry is None:
                fused[hit.chunk_id] = _FusedHit(hit=hit, score=contribution)
            else:
                entry.score += contribution

    hits = [entry.hit.model_copy(update={"score": entry.score}) for entry in fused.values()]
    return sort_hits(hits)[:k]


async def hybrid_search(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
    *,
    vector_search: SearchCallable,
    lexical_search: SearchCallable,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[ChunkHit]:
    """Retrieve two candidate lists and combine them with rank-only RRF.

    Injected callables let the production adapter close over its session, embedder,
    and vector query preparation. Calls are awaited sequentially so both adapters may
    safely share one SQLAlchemy ``AsyncSession``.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    limit = candidate_k if candidate_k is not None else k
    if limit < k:
        raise ValueError("candidate_k must be at least k")
    active_filters = filters or RetrievalFilters()

    vector_hits = await vector_search(query, limit, active_filters)
    lexical_hits = await lexical_search(query, limit, active_filters)
    return rrf_fuse(vector_hits, lexical_hits, k, rrf_k=rrf_k)
```

Run the checkpoint:

```bash
uv run pytest tests/retrieval/test_05_hybrid.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M2.6 — Complete checkpoint

#### Create or replace `app/retrieval/rerank.py`

<!-- file: app/retrieval/rerank.py -->
```python
"""Optional async reranking behind a dependency-free provider boundary."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
import math
from numbers import Real

from app.retrieval.types import ChunkHit, sort_hits


class RerankProvider(ABC):
    """Provider boundary for scoring query/document pairs."""

    @abstractmethod
    async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        """Return one relevance score per document in caller order."""


def _scores(values: Sequence[float], *, expected_count: int) -> list[float]:
    """Validate provider scores before replacing immutable hit scores."""
    if len(values) != expected_count:
        raise ValueError(f"reranker returned {len(values)} scores for {expected_count} hits")
    scores: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("reranker returned a nonnumeric score")
        score = float(value)
        if not math.isfinite(score):
            raise ValueError("reranker returned a non-finite score")
        scores.append(score)
    return scores


async def rerank_hits(
    query: str,
    hits: Sequence[ChunkHit],
    *,
    provider: RerankProvider | None = None,
    top_k: int = 5,
) -> list[ChunkHit]:
    """Optionally rescore top candidates and return deterministic top-k hits."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("rerank query must be nonempty")
    if top_k < 0:
        raise ValueError("rerank top_k must not be negative")
    if top_k == 0 or not hits:
        return []
    if provider is None:
        return sort_hits(hits)[:top_k]

    scores = _scores(
        await provider.score(query, [hit.index_text for hit in hits]),
        expected_count=len(hits),
    )
    rescored = [
        hit.model_copy(update={"score": score}) for hit, score in zip(hits, scores, strict=True)
    ]
    return sort_hits(rescored)[:top_k]
```

Run the checkpoint:

```bash
uv run pytest tests/retrieval/test_06_rerank.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M2.7 — Complete checkpoint

#### Create or replace `app/retrieval/service.py`

<!-- file: app/retrieval/service.py -->
```python
"""Production composition for deterministic hybrid retrieval."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BM25Idf, LexicalRanker, get_settings
from app.db.models import DIM
from app.retrieval.bm25 import BM25_IDF_VARIANTS, bm25_search
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K, hybrid_search
from app.retrieval.language import detect_query_language
from app.retrieval.lexical import lexical_search
from app.retrieval.rerank import RerankProvider, rerank_hits
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search

RankedChunkId = Annotated[int, Field(gt=0)]
RESEARCH_AND_DEVELOPMENT = re.compile(r"\bR\s*&\s*D\b", flags=re.IGNORECASE)


def _normalize_query(query: str) -> str:
    """Expand the common R&D abbreviation for embedding and PostgreSQL FTS parity."""
    return RESEARCH_AND_DEVELOPMENT.sub("research development", query)


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

#### Create or replace `app/retrieval/__main__.py`

<!-- file: app/retrieval/__main__.py -->
```python
"""Command-line acceptance path for the M2 retrieval service."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
import json
from typing import Literal

from app.config import BM25Idf, LexicalRanker, Settings, get_settings
from app.db.bootstrap import bootstrap_schema
from app.db.session import Session, engine
from app.retrieval.bm25 import TermStatCounts, backfill_term_stats
from app.retrieval.cross_encoder import CrossEncoderReranker
from app.retrieval.embeddings import (
    EmbeddingBackfillResult,
    embed_missing_chunks,
    get_embedding_provider,
)
from app.retrieval.service import RetrievalResult, retrieve

ProviderName = Literal["deterministic", "openai", "sbert"]


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


if __name__ == "__main__":
    main()
```

Run the checkpoint:

```bash
uv run pytest tests/retrieval/test_07_service.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M2.8 — Complete checkpoint

Run the checkpoint:

```bash
uv run pytest tests/retrieval/test_08_postgres.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M2.9 — Complete checkpoint

#### Create or replace `app/retrieval/bm25.py`

<!-- file: app/retrieval/bm25.py -->
```python
"""Deterministic PostgreSQL BM25 retrieval over stored full-text lexemes."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

from sqlalchemy import (
    Float,
    Integer,
    Select,
    SQLColumnExpression,
    String,
    bindparam,
    cast,
    delete,
    func,
    select,
    text,
    true,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BM25Idf
from app.db.models import Chunk, ChunkLength, ChunkTerm, Document, LexemeStat
from app.retrieval.lexical import TEXT_SEARCH_CONFIG, _filter_predicates
from app.retrieval.types import ChunkHit, RetrievalFilters

DEFAULT_BM25_K1 = 1.2
DEFAULT_BM25_B = 0.75
DEFAULT_BM25_IDF: BM25Idf = "lucene"
BM25_IDF_VARIANTS: tuple[BM25Idf, ...] = ("lucene", "robertson")


@dataclass(frozen=True, slots=True)
class TermStatCounts:
    """Committed row counts for one complete BM25 statistic rebuild."""

    terms: int
    chunks: int
    lexemes: int


async def backfill_term_stats(session: AsyncSession) -> TermStatCounts:
    """Atomically rebuild every BM25 statistic from ``chunks.content_tsv``.

    The function owns one transaction so readers observe either the previous
    complete statistic set or the new one. The source-table lock prevents a
    concurrent chunk write from producing a mixed-corpus snapshot, while the
    derived-table lock serializes competing rebuilds without blocking readers.
    """
    if session.in_transaction():
        raise RuntimeError("backfill_term_stats requires a session without an active transaction")

    async with session.begin():
        await session.execute(text("LOCK TABLE chunks IN SHARE MODE"))
        await session.execute(
            text("LOCK TABLE chunk_terms, chunk_lengths, lexeme_stats IN SHARE ROW EXCLUSIVE MODE")
        )
        await session.execute(delete(ChunkTerm))
        await session.execute(delete(ChunkLength))
        await session.execute(delete(LexemeStat))

        await session.execute(
            text(
                "INSERT INTO chunk_terms (chunk_id, lexeme, tf) "
                "SELECT c.id, t.lexeme, cardinality(t.positions) "
                "FROM chunks AS c CROSS JOIN LATERAL unnest(c.content_tsv) AS t "
                "WHERE t.positions IS NOT NULL AND cardinality(t.positions) > 0"
            )
        )
        await session.execute(
            text(
                "INSERT INTO chunk_lengths (chunk_id, dl) "
                "SELECT chunk_id, SUM(tf) FROM chunk_terms GROUP BY chunk_id"
            )
        )
        await session.execute(
            text(
                "INSERT INTO lexeme_stats (lexeme, df) "
                "SELECT lexeme, COUNT(*) FROM chunk_terms GROUP BY lexeme"
            )
        )

        row = (
            await session.execute(
                select(
                    select(func.count()).select_from(ChunkTerm).scalar_subquery().label("terms"),
                    select(func.count()).select_from(ChunkLength).scalar_subquery().label("chunks"),
                    select(func.count()).select_from(LexemeStat).scalar_subquery().label("lexemes"),
                )
            )
        ).one()
        counts = TermStatCounts(
            terms=int(row.terms),
            chunks=int(row.chunks),
            lexemes=int(row.lexemes),
        )

    return counts


def _idf_expression(
    variant: BM25Idf,
    corpus_size: SQLColumnExpression[int],
    document_frequency: SQLColumnExpression[int],
) -> SQLColumnExpression[float]:
    """Return the SQL inverse document frequency for one lexeme.

    Both published variants are available because they disagree about common
    terms. Robertson's original is ``ln((N - df + 0.5) / (df + 0.5))``, which turns
    negative once a lexeme appears in more than half the corpus; a chunk is then
    penalised for containing it, and on a small corpus that inverts the ranking
    outright. Lucene adds one before the logarithm, so its idf never drops below
    zero and a common term merely stops contributing. Lucene is the default for
    that reason; Robertson stays selectable because the difference is the whole
    lesson.

    ``df`` is clamped to the corpus size because a lexeme cannot occur in more
    chunks than exist. The clamp only bites on stale statistics: deleting chunks
    cascades their ``chunk_terms`` and ``chunk_lengths`` rows away but leaves
    ``lexeme_stats`` untouched, and an unclamped Robertson numerator would then go
    negative and make PostgreSQL raise on ``ln`` of a nonpositive argument.
    """
    if variant not in BM25_IDF_VARIANTS:
        raise ValueError("idf must be 'lucene' or 'robertson'")
    size = cast(corpus_size, Float)
    df = func.least(cast(document_frequency, Float), size)
    ratio = (size - df + 0.5) / (df + 0.5)
    if variant == "lucene":
        return func.ln(1.0 + ratio)
    return func.ln(ratio)


def _validated_parameters(query: str, k: int, k1: float, b: float) -> tuple[float, float]:
    """Validate public BM25 inputs and return normalized numeric parameters."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    if isinstance(k1, bool) or not isinstance(k1, Real):
        raise ValueError("k1 must be a finite positive number")
    if isinstance(b, bool) or not isinstance(b, Real):
        raise ValueError("b must be a finite number between 0 and 1")

    normalized_k1 = float(k1)
    normalized_b = float(b)
    if not math.isfinite(normalized_k1) or normalized_k1 <= 0:
        raise ValueError("k1 must be a finite positive number")
    if not math.isfinite(normalized_b) or not 0 <= normalized_b <= 1:
        raise ValueError("b must be a finite number between 0 and 1")
    return normalized_k1, normalized_b


def bm25_statement(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
    *,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
    idf: BM25Idf = DEFAULT_BM25_IDF,
) -> Select[Any]:
    """Build a bound BM25 query with shared filters and deterministic ordering."""
    normalized_k1, normalized_b = _validated_parameters(query, k, k1, b)
    active_filters = filters or RetrievalFilters()

    query_terms = select(
        func.unnest(
            func.tsvector_to_array(
                func.to_tsvector(
                    TEXT_SEARCH_CONFIG,
                    bindparam("bm25_query", value=query, type_=String()),
                )
            )
        ).label("lexeme")
    ).subquery("bm25_query_terms")
    corpus = select(
        func.count(ChunkLength.chunk_id).label("n"),
        func.avg(ChunkLength.dl).label("avgdl"),
    ).subquery("bm25_corpus")

    k1_param = bindparam("bm25_k1", value=normalized_k1, type_=Float())
    b_param = bindparam("bm25_b", value=normalized_b, type_=Float())
    document_length = cast(ChunkLength.dl, Float)
    idf_term = _idf_expression(idf, corpus.c.n, LexemeStat.df)
    length_norm = 1.0 - b_param + b_param * document_length / corpus.c.avgdl
    saturation = (ChunkTerm.tf * (k1_param + 1.0)) / (ChunkTerm.tf + k1_param * length_norm)
    score = cast(func.sum(idf_term * saturation), Float).label("score")

    scores = (
        select(ChunkTerm.chunk_id.label("chunk_id"), score)
        .select_from(ChunkTerm)
        .join(query_terms, query_terms.c.lexeme == ChunkTerm.lexeme)
        .join(LexemeStat, LexemeStat.lexeme == ChunkTerm.lexeme)
        .join(ChunkLength, ChunkLength.chunk_id == ChunkTerm.chunk_id)
        .join(corpus, true())
        .group_by(ChunkTerm.chunk_id)
        .subquery("bm25_scores")
    )

    return (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.doc_id,
            Chunk.item,
            Chunk.kind,
            Chunk.citation,
            Chunk.start_char,
            Chunk.end_char,
            Chunk.source_sha256,
            Chunk.body,
            Chunk.context_header,
            Chunk.index_text,
            scores.c.score,
        )
        .select_from(Chunk)
        .join(scores, scores.c.chunk_id == Chunk.id)
        .join(Document, Document.doc_id == Chunk.doc_id)
        .where(*_filter_predicates(active_filters))
        .order_by(
            scores.c.score.desc(),
            Chunk.doc_id.asc(),
            Chunk.source_sha256.asc(),
            Chunk.start_char.asc(),
            Chunk.end_char.asc(),
            Chunk.id.asc(),
        )
        .limit(bindparam("bm25_k", value=k, type_=Integer()))
    )


async def bm25_search(
    session: AsyncSession,
    query: str,
    k: int = 5,
    filters: RetrievalFilters | None = None,
    *,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
    idf: BM25Idf = DEFAULT_BM25_IDF,
) -> list[ChunkHit]:
    """Rank chunks by BM25 and return complete, deterministically ordered hits."""
    result = await session.execute(bm25_statement(query, k, filters, k1=k1, b=b, idf=idf))
    return [ChunkHit.model_validate(row) for row in result.mappings().all()]
```

Run the checkpoint:

```bash
uv run pytest tests/retrieval/test_09_bm25.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M2.10 — Complete checkpoint

#### Create or replace `app/retrieval/sbert.py`

<!-- file: app/retrieval/sbert.py -->
```python
"""Local sentence-transformer embeddings behind the shared provider boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Sequence
from typing import Protocol, cast

from app.retrieval.embeddings import EmbeddingProvider, _texts, validate_embeddings

# The multilingual sibling of the default model. It outputs 384 dimensions natively,
# so it drops into ``Settings.sbert_model`` without touching ``embed_dim``, the
# ``Vector(384)`` column, or any migration — the difference is entirely in the space
# the vectors live in, where Korean and English text sit near each other.
MULTILINGUAL_SBERT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class _EmbeddingMatrix(Protocol):
    """Array-like sentence-transformer output used by the provider boundary."""

    def tolist(self) -> list[list[float]]:
        """Return the encoded batch as nested Python floats."""
        ...


class _SentenceEncoder(Protocol):
    """Structural type for the lazily imported sentence-transformer."""

    def get_sentence_embedding_dimension(self) -> int | None:
        """Return the model output width when the model reports one."""
        ...

    def encode(
        self,
        sentences: Sequence[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
    ) -> _EmbeddingMatrix:
        """Encode one batch with the options required by this provider."""
        ...


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Local sentence-transformer embeddings behind the shared provider boundary.

    The model runs inside this process, so after the weights are cached there is no
    API key and no network call. ``sentence_transformers`` is imported lazily, which
    keeps ``app.retrieval`` importable when the project is installed without a torch
    backend extra.

    A local model is not interchangeable with a hosted one. Vectors produced here do
    not share a space with vectors produced by another model, so switching providers
    requires re-embedding every chunk. Mixing them yields no error, only meaningless
    neighbours.
    """

    def __init__(
        self,
        *,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimensions: int = 384,
        batch_size: int = 32,
    ) -> None:
        if not model:
            raise ValueError("embedding model must be nonempty")
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        if batch_size <= 0:
            raise ValueError("embedding batch size must be positive")
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self._encoder: _SentenceEncoder | None = None

    def _load(self) -> _SentenceEncoder:
        """Import and construct the encoder once, then reuse it.

        Raises
        ------
        RuntimeError
            If no torch backend extra is installed.
        ValueError
            If the model's output width does not match the database column.
        """
        if self._encoder is not None:
            return self._encoder

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; run one of "
                "`uv sync --extra cpu`, `--extra rocm`, or `--extra cu130`"
            ) from exc

        encoder = cast(_SentenceEncoder, SentenceTransformer(self.model))
        reported = encoder.get_sentence_embedding_dimension()
        if reported != self.dimensions:
            raise ValueError(
                f"model {self.model!r} produces {reported} dimensions, "
                f"but this database stores {self.dimensions}"
            )
        self._encoder = encoder
        return encoder

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode a batch off the event loop and validate before returning."""
        inputs = _texts(texts)
        if not inputs:
            return []

        encoder = self._load()

        def _encode() -> list[list[float]]:
            """Run the synchronous, CPU-bound forward pass in a worker thread."""
            return encoder.encode(
                inputs,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
            ).tolist()

        vectors = await asyncio.to_thread(_encode)
        return validate_embeddings(
            vectors,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )
```

Run the checkpoint:

```bash
uv run pytest tests/retrieval/test_10_sbert.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M2.11 — Complete checkpoint

#### Create or replace `app/retrieval/cross_encoder.py`

<!-- file: app/retrieval/cross_encoder.py -->
```python
"""Cross-encoder reranking provider for the M2.6 boundary.

``sentence_transformers`` is imported lazily so that installing the project without a
torch backend extra leaves ``app.retrieval`` importable.
"""

import asyncio
from collections.abc import Sequence
from typing import Protocol, cast

from app.retrieval.rerank import RerankProvider


class _CrossEncoderModel(Protocol):
    """Structural type for the lazily imported cross-encoder."""

    def predict(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
    ) -> Sequence[float]:
        """Score query/document pairs in caller order."""
        ...


class CrossEncoderReranker(RerankProvider):
    """Rerank with a cross-encoder that reads the query and document together.

    The vector path in M2.3 is a bi-encoder: it embeds the query and the chunk
    separately and compares the two vectors afterwards, so the two texts never meet
    inside the model. That separation is what makes it cheap enough to run over the
    whole corpus, and also what limits its accuracy.

    A cross-encoder concatenates the query and one document into a single input and
    returns one relevance score. It reads both together, which is more accurate and
    costs one forward pass per candidate. That price is only affordable on a short
    list, which is why reranking runs after fusion rather than instead of it.

    The returned scores are raw logits. They are not probabilities, they are not
    bounded, and they are not comparable with cosine similarity or with BM25.
    """

    def __init__(
        self,
        *,
        model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        batch_size: int = 32,
    ) -> None:
        if not model:
            raise ValueError("reranker model must be nonempty")
        if batch_size <= 0:
            raise ValueError("reranker batch size must be positive")
        self.model = model
        self.batch_size = batch_size
        self._encoder: _CrossEncoderModel | None = None

    def _load(self) -> _CrossEncoderModel:
        """Import and construct the cross-encoder once, then reuse it."""
        if self._encoder is not None:
            return self._encoder

        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; run one of "
                "`uv sync --extra cpu`, `--extra rocm`, or `--extra cu130`"
            ) from exc

        self._encoder = cast(_CrossEncoderModel, CrossEncoder(self.model))
        return self._encoder

    async def score(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        """Score every query/document pair off the event loop, in caller order."""
        pairs = [(query, document) for document in documents]
        if not pairs:
            return []

        encoder = self._load()

        def _predict() -> list[float]:
            """Run the synchronous, CPU-bound forward passes in a worker thread."""
            return [float(value) for value in encoder.predict(pairs, batch_size=self.batch_size)]

        return await asyncio.to_thread(_predict)
```

Run the checkpoint:

```bash
uv run pytest tests/retrieval/test_11_cross_encoder.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

<!-- complete-files:end -->
