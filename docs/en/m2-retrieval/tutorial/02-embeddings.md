# M2.2 Tutorial 2 — Keep network calls and transactions from overlapping

Now fill in the 9,172 chunks where `embedding IS NULL`. Three constraints are tangled together in that job.

**First, documents and questions must live in the same embedding space.** That sounds obvious and is easy to get wrong. Embed documents with model A and questions with model B and cosine similarity becomes a meaningless number. So the query embedding is forced through **the same path**.

**Second, tests must not depend on the network.** A test that calls OpenAI is slow, costs money, and cannot run offline. That calls for a deterministic fake provider — but handing back random numbers would make retrieval tests meaningless. The deterministic provider has to **preserve lexical overlap**, so that texts sharing words end up close together.

**Third, slow network calls must not overlap database transactions.** That is the most important design point here, and it gets its own section below.

**Prerequisite:** Tutorial 1's `uv run pytest tests/retrieval/test_01_contract.py -q` passes.

## What to define, what to implement, and what to inspect

M2.2 builds `app/retrieval/embeddings.py` in seven steps. The file has two halves: a provider boundary that produces vectors, and a backfill that stores them.

Only two providers are built here, and both avoid loading a model: one calls an API, the other hashes text. A local model arrives in [Tutorial 8](08-local-embeddings.md) at M2.10, once there is a reason to take on the dependency it requires.

| Area | Learning action | What to take away |
|---|---|---|
| Module header | **Define the structure** | Which boundaries this file touches |
| `validate_embeddings` | **Implement** the output contract yourself | What every provider must satisfy before reaching the database |
| `EmbeddingProvider` | **Review the design decision** | How inheritance forces queries and documents onto one path |
| `DeterministicEmbeddingProvider` | **Implement** the hashing algorithm yourself | Why an offline provider must preserve lexical overlap |
| `OpenAIEmbeddingProvider` and `get_embedding_provider` | **Write the structure, then inspect boundary conversions** | Restoring caller order from response indices |
| `PendingEmbedding` and `EmbeddingBackfillResult` | **Write the record declarations** | What a resumable job must observe |
| `_missing_batch`, `_store_batch`, `embed_missing_chunks` | **Implement** the transaction split yourself | Where the I/O sits and what the stale guard blocks |

## 1. Module header

### Create `app/retrieval/embeddings.py` — module header

**Learning action — define the structure:** note which two worlds the imports span — hashing and text normalization on one side, SQLAlchemy and the ORM on the other.

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
```

## 2. One validator every provider must pass

A provider is remote code, or a fake, or a future replacement. Whatever it is, the vectors it returns cross into a PostgreSQL `Vector(384)` column. Validating at that boundary once means no provider can smuggle a wrong shape past it.

### Extend `app/retrieval/embeddings.py` — shared output validation

**Learning action — implement the output contract:** write `_texts` as given, then implement `validate_embeddings` yourself. Each `raise` marks one way a provider can be wrong.

<!-- src: app/retrieval/embeddings.py::_texts,validate_embeddings -->
```python
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
```

### `float` and `Real` are not interchangeable

Both `float` and `Real` survive in this code, and their roles do not overlap.

Both names remain in this validator, but they have different jobs.

- `Sequence[float]` is the **static type contract** for valid provider output. It is what lets `embed_query()` hand its `list[float]` to vector search without a Pylance argument-type error.
- `isinstance(component, Real)` is the **runtime check** that the object actually received is numeric. Type annotations do not stop a string or `bool` from arriving at runtime, so this check remains necessary.

Python reports `isinstance(1.0, Real)` as true at runtime, but the [official typeshed `numbers.pyi`](https://github.com/python/typeshed/blob/main/stdlib/numbers.pyi) explicitly notes that static type checkers do not see `float` as a subtype of `numbers.Real`. Annotating an argument as `Sequence[Real]` can therefore make Pylance reject a normal `list[float]`.

The project rule is simple: **use `float` in function signatures and normalized results, and reserve `isinstance` checks against `Real` for the values actually returned at runtime.** This is a type-contract correction, not a performance optimization.

**What to look for in the code**

- `list(values)` in `_texts` materializes the input. A generator would be consumed by the count check and arrive empty at the provider.
- `isinstance(component, bool)` is rejected explicitly. In Python `bool` is a subclass of `int`, so `True` would otherwise pass as a numeric component and become `1.0`.
- `math.isfinite` blocks NaN and infinity. A NaN inside a vector makes every distance comparison against it false, and the chunk silently stops being retrievable.
- The count check compares against `expected_count`, not against the provider's own idea of how many it returned. Callers state what they asked for.

## 3. The provider boundary

The first constraint at the top of this section — documents and questions in one space — is the kind of rule that gets written in a comment and then broken six months later.

Picture how it breaks. Someone adds a provider that caches document embeddings but wants queries to skip the cache, so they override a query path. Or a provider whose API has a separate, cheaper endpoint for short inputs, and queries are short. Each of those is a locally reasonable decision, and each one silently detaches queries from the space the documents live in. Cosine similarity keeps returning numbers. The numbers stop meaning anything.

The class below makes those changes impossible to write by accident rather than merely inadvisable.

### Extend `app/retrieval/embeddings.py` — the provider boundary

**Learning action — review the design decision:** this class is short. What matters is which method is abstract and which is not.

<!-- src: app/retrieval/embeddings.py::EmbeddingProvider -->
```python
class EmbeddingProvider(ABC):
    """Async provider boundary shared by query and document embeddings."""

    dimensions: int

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch in caller order."""

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query through the same model and validation path."""
        return (await self.embed_documents([text]))[0]
```

The abstract class marks only `embed_documents` as abstract and has `embed_query` call it. That turns the first constraint stated above — queries and documents must share a space — into **an inheritance guarantee**. A subclass cannot build a separate path for queries.

## 4. The deterministic provider

The offline provider must not return random numbers. If it did, "similar text ranks higher" would be untestable. Hashing tokens into signed buckets keeps texts that share words close together.

### Extend `app/retrieval/embeddings.py` — deterministic provider

**Learning action — implement the hashing algorithm:** follow the four stages — normalize, tokenize, hash into buckets, normalize the vector — and implement them yourself.

<!-- src: app/retrieval/embeddings.py::DeterministicEmbeddingProvider -->
```python
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
```

**What to look for in the code**

- `unicodedata.normalize("NFKC", text).casefold()` runs before tokenizing, so visually identical text from different filings hashes the same way.
- The `sign` drawn from `digest[8] & 1` is what makes this more than a word count. Without signs, every long text would drift toward the same direction and similarity would mostly measure length.
- The `norm == 0.0` branch is not dead code. Signed buckets can cancel exactly to zero, and dividing by that norm would produce NaN — which `validate_embeddings` would then reject.
- `tokens = ["<empty>"]` keeps a text with no alphanumeric characters from returning a zero vector instead of failing.

## 5. The OpenAI provider and provider selection

This is the one place in M2 where a bug would be genuinely hard to find, so it is worth slowing down.

A batch embedding API takes a list and returns a list. The obvious code reads the response in the order it arrives and zips it against the inputs. That works every time you test it, because responses usually do arrive in order.

Now suppose one day they do not. Chunk 40's vector attaches to chunk 41's text. Every vector is well-formed: right count, right dimension, all finite. `validate_embeddings` passes it without complaint, because nothing about a vector's *shape* reveals that it belongs to a different document. The corpus is now quietly wrong, retrieval returns confidently irrelevant evidence, and the only trace is a slight, unexplainable drop in evaluation scores.

The response carries an index for exactly this reason, and the code below refuses to proceed unless those indices cover every input position exactly once.

### Extend `app/retrieval/embeddings.py` — OpenAI provider and selection

**Learning action — write the structure, then inspect boundary conversions:** the constructor is mechanical. Look closely at how `embed_documents` restores caller order.

<!-- src: app/retrieval/embeddings.py::OpenAIEmbeddingProvider,get_embedding_provider -->
```python
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
```

**What to look for in the code**

- The response is rebuilt through `by_index` rather than read in arrival order. The API does not promise ordering, and a silent reordering here would attach every vector to the wrong chunk — a corruption no test of vector shape would catch.
- Two separate checks guard that map: duplicate or non-integer indices, and a set that does not cover every input position.
- `client` is injectable, which is what lets tests exercise this provider with no network.
- `get_embedding_provider` reads settings when called, not at import. The same reasoning kept `app.db.session` out of module scope in M1.4.

## 6. What a resumable job has to observe

A backfill over 9,172 chunks that costs real money should not report "done."

Consider what you actually need to know when it finishes. Did it look at everything it should have? Did every row it selected get written? If some did not, was that a failure or a legitimate skip? Answering those from logs after the fact is guesswork; the job should hand back the numbers.

The two records below exist to make the run inspectable rather than merely successful.

### Extend `app/retrieval/embeddings.py` — backfill records

**Learning action — write the record declarations:** four counters. Ask what question each one answers after a run.

<!-- src: app/retrieval/embeddings.py::PendingEmbedding,EmbeddingBackfillResult -->
```python
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
```

**What to look for in the code**

- `PendingEmbedding` carries `index_text` alongside `chunk_id`. That copy is what the stale guard in step 7 compares against.
- `selected` and `embedded` are separate counters. When they differ, `skipped_stale` explains the gap instead of leaving a silent loss.

## Do not call an API with a transaction open

The most natural backfill implementation is this.

```
begin transaction
  → read the null rows
  → call OpenAI          ← several seconds here
  → UPDATE with results
commit
```

It works. And **database rows stay locked for the entire network round trip.** Batch through 9,172 and that time accumulates while other seed work waits. One API timeout rolls back the whole transaction, discarding the successes before it.

So the transaction is **cut small with the I/O placed between the pieces.**

```
[transaction 1]  read one null batch and close immediately
                  ↓
[no transaction] request embeddings (slow, fallible, paid)
                  ↓
[transaction 2]  UPDATE only rows still null with unchanged index_text
```

Two things are gained at once.

**Resumability.** Die partway and the already-committed batches remain. Rerun and it picks up from the remaining nulls. This is where M1.4's decision to keep `embedding` nullable pays off.

**Race safety.** The final UPDATE carries the condition `still null and index_text unchanged`. If someone reseeded while the embedding was being computed and that chunk's text changed, **our vector is already stale.** The condition blocks that UPDATE.

Without it, a stale vector overwrites current text — a race that is hard to reproduce and whose only symptom is "retrieval is sometimes odd," making it exceptionally hard to find.

## 7. Two short transactions with the I/O between them

### Extend `app/retrieval/embeddings.py` — the two bounded transactions

**Learning action — implement the transaction split:** write both functions yourself. Each owns exactly one short transaction, and neither performs provider I/O.

<!-- src: app/retrieval/embeddings.py::_missing_batch,_store_batch -->
```python
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
```

**What to look for in the code**

- The `return` in `_missing_batch` sits outside `async with`, so the transaction closes before the caller starts provider I/O.
- `.order_by(Chunk.id)` makes each batch a stable window. Without it, repeated `LIMIT` queries could revisit or skip rows.
- The WHERE clause in `_store_batch` carries all three conditions. `Chunk.embedding.is_(None)` means someone else has not already filled it, and the `index_text` comparison means the text has not changed underneath.
- `result.rowcount == 1` is how a rejected write is detected. No exception is raised — a stale row simply matches nothing, and the counter records it.
- `strict=True` on `zip` fails loudly if the provider returned a different count than the batch held.

## 8. The backfill loop

### Complete `app/retrieval/embeddings.py` — the resumable loop

**Learning action — implement the loop invariants:** the counters and the loop condition are the whole function. Write it and check that a rerun does no duplicate work.

<!-- src: app/retrieval/embeddings.py::embed_missing_chunks -->
```python
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

**What to look for in the code**

- `session.in_transaction()` is rejected here for the same reason as in M1.4: an open outer transaction would turn every `session.begin()` into a savepoint and defeat the entire point of splitting the work.
- The loop condition re-queries for nulls each pass instead of counting down a fixed total. That is what makes the job resumable — and what makes it terminate, since successfully stored rows stop being null.
- `validate_embeddings` runs again here even though providers already call it. The loop does not trust that a provider it did not write honored the contract.
- A stale row is skipped, not retried. It stays null, so the next run picks it up with its current text.

Writing this much completes `app/retrieval/embeddings.py`. The eight blocks concatenated in order are the checkpoint file itself.

## Focused tests and the contracts they protect

```bash
uv run pytest tests/retrieval/test_02_embeddings.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| A vector count or dimension that disagrees | Every provider satisfies one output shape. |
| A NaN, infinite, or boolean component | No unusable vector reaches the database. |
| Shuffled OpenAI response indices | A vector never attaches to the wrong chunk. |
| A configured provider name | Selection follows settings without import-time work. |
| Text changed during provider I/O | A stale vector never overwrites current text. |
| A rerun after a partial failure | Committed batches are not recomputed. |

Done correctly, every embedding test passes offline, covering count, order, dimension, finiteness, provider selection, and stale-write protection.

The bar for moving on is simple: a single failure in the output-shape or stale-update tests means M2.2 is not complete.

On failure, a wrong vector count or dimension points at the shared validator first. A failing backfill means checking that provider I/O runs between the two short transactions and that the update condition includes both a null embedding and an unchanged `index_text`.

## What you should be able to explain now

- **Why is `embed_query` not abstract?**
  - **Answer:** `embed_query` provides a convenient default that delegates to `embed_documents`, so a simple subclass needs to implement only batch embedding. It is a convention, not an inheritance guarantee, because a subclass can override it.
- **What would a random offline provider make untestable?**
  - **Answer:** Random vectors do not preserve lexical overlap, so retrieval tests could not verify that related text ranks above unrelated text.
- **Which corruption does rebuilding order through `by_index` prevent?**
  - **Answer:** It prevents an API response returned out of order from assigning one text's vector to a different text or chunk.
- **What exactly is lost if the API call happens inside one long transaction?**
  - **Answer:** Locks remain held throughout the network wait, and one timeout can roll back every successful batch instead of preserving resumable progress.
- **Which two conditions must the final UPDATE carry, and what does each block?**
  - **Answer:** The embedding must still be null, which prevents overwriting concurrent work, and `index_text` must still match, which prevents storing a vector made from stale text.

---

[← Previous: Contracts](01-contracts.md) · [Module overview](../03-build.md) · [Next →: Retrieval paths](03-retrieval-paths.md)
