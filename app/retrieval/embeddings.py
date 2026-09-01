"""Async embedding providers and resumable PostgreSQL embedding backfill."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import math
import re
from typing import Any, Literal, Protocol, cast
import unicodedata

from sqlalchemy import select, update, values
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Chunk
from app.openai_models import resolve_openai_model
from app.retrieval.types import finite_float


class _EmbeddingData(Protocol):
    """One indexed embedding returned by an SDK-compatible client."""

    @property
    def index(self) -> int:
        """Return the input position represented by this embedding."""
        ...

    @property
    def embedding(self) -> Sequence[float]:
        """Return the embedding vector."""
        ...


class _EmbeddingResponse(Protocol):
    """Embedding response surface consumed by the provider."""

    @property
    def data(self) -> Sequence[_EmbeddingData]:
        """Return indexed embeddings from the provider response."""
        ...


class _EmbeddingsResource(Protocol):
    """Minimal async embeddings endpoint used by the provider."""

    async def create(
        self,
        *,
        input: Sequence[str],
        model: str,
        dimensions: int,
        encoding_format: Literal["float"],
    ) -> _EmbeddingResponse:
        """Create embeddings through an SDK-compatible endpoint."""
        ...


class EmbeddingClient(Protocol):
    """Structural client boundary for OpenAI and injected test clients."""

    @property
    def embeddings(self) -> _EmbeddingsResource:
        """Return the client's async embeddings endpoint."""
        ...


def validate_texts(values: Sequence[str]) -> list[str]:
    """Return validated, materialized embedding inputs.

    Parameters
    ----------
    values : Sequence[str]
        Input texts supplied by a caller.

    Returns
    -------
    list[str]
        Materialized list that preserves caller order.

    Raises
    ------
    ValueError
        If any input is empty or is not a string.
    """
    texts = list(values)
    if any(not isinstance(text, str) or not text for text in texts):
        raise ValueError("embedding inputs must be nonempty strings")
    return texts


def validate_embeddings(
    values: Sequence[Sequence[float]], *, expected_count: int, dimensions: int
) -> list[list[float]]:
    """Validate provider output before it crosses the database boundary.

    Parameters
    ----------
    values : Sequence[Sequence[float]]
        Provider vectors in caller order.
    expected_count : int
        Number of vectors requested by the caller.
    dimensions : int
        Required number of components in each vector.

    Returns
    -------
    list[list[float]]
        Finite, nonzero vectors materialized as built-in floats.

    Raises
    ------
    ValueError
        If dimensions, count, shape, numeric type, finiteness, or vector norm is invalid.
    """
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
        nonnumeric = f"embedding {position} contains a nonnumeric component"
        nonfinite = f"embedding {position} contains a non-finite component"
        vector = [
            finite_float(component, nonnumeric=nonnumeric, nonfinite=nonfinite)
            for component in value
        ]
        if not any(vector):
            raise ValueError(f"embedding {position} must have a nonzero norm")
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
        inputs = validate_texts(texts)
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


@dataclass(frozen=True, slots=True)
class EmbeddingUsage:
    """Cumulative OpenAI embedding usage and exact estimated cost."""

    requests: int = 0
    input_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0")


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider with explicit output dimensions."""

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        dimensions: int = 384,
        client: EmbeddingClient | None = None,
        api_key: str | None = None,
    ) -> None:
        selection = resolve_openai_model("embedding", model)
        if dimensions != selection.dimensions:
            raise ValueError(
                f"embedding dimensions must be {selection.dimensions} for {selection.model}"
            )
        self.model = selection.model
        self.dimensions = dimensions
        self._input_price = selection.pricing.input_per_million_usd
        self._usage = EmbeddingUsage()
        if client is None:
            from openai import AsyncOpenAI

            client = cast(EmbeddingClient, AsyncOpenAI(api_key=api_key))
        self._client = client

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed one batch and restore caller order from response indices."""
        inputs = validate_texts(texts)
        if not inputs:
            return []

        response = await self._client.embeddings.create(
            input=inputs,
            model=self.model,
            dimensions=self.dimensions,
            encoding_format="float",
        )
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None)
        if not isinstance(input_tokens, int) or input_tokens < 0:
            raise ValueError("OpenAI embedding response did not include token usage")
        by_index: dict[int, Sequence[float]] = {}
        for item in response.data:
            if not isinstance(item.index, int) or item.index in by_index:
                raise ValueError("embedding provider returned invalid response indices")
            by_index[item.index] = item.embedding
        if set(by_index) != set(range(len(inputs))):
            raise ValueError("embedding provider returned incomplete response indices")
        ordered = [by_index[index] for index in range(len(inputs))]
        vectors = validate_embeddings(
            ordered,
            expected_count=len(inputs),
            dimensions=self.dimensions,
        )
        self._usage = EmbeddingUsage(
            requests=self._usage.requests + 1,
            input_tokens=self._usage.input_tokens + input_tokens,
            estimated_cost_usd=self._usage.estimated_cost_usd
            + Decimal(input_tokens) * self._input_price / Decimal(1_000_000),
        )
        return vectors

    @property
    def usage(self) -> EmbeddingUsage:
        """Return cumulative usage for requests this provider instance issued."""
        return self._usage


def get_embedding_provider(
    settings: Settings | None = None, *, client: EmbeddingClient | None = None
) -> EmbeddingProvider:
    """Build the configured provider without work at module import time.

    Parameters
    ----------
    settings : Settings | None
        Validated settings, or ``None`` to load cached application settings.
    client : EmbeddingClient | None
        Optional SDK-compatible client for the OpenAI provider.

    Returns
    -------
    EmbeddingProvider
        Deterministic or OpenAI provider selected by configuration.
    """
    configured = settings or get_settings()
    if configured.embedding_provider == "deterministic":
        return DeterministicEmbeddingProvider(configured.embed_dim)
    if configured.embedding_provider == "sbert":
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


async def _missing_batch(
    session: AsyncSession,
    batch_size: int,
    *,
    after_chunk_id: int | None = None,
) -> list[PendingEmbedding]:
    """Load one keyset-paginated batch and close its read transaction.

    Parameters
    ----------
    session : AsyncSession
        Session that owns the bounded read transaction.
    batch_size : int
        Maximum number of missing rows to select.
    after_chunk_id : int | None
        Exclusive chunk-id cursor, or ``None`` to start from the first row.

    Returns
    -------
    list[PendingEmbedding]
        Missing rows in ascending chunk-id order.

    Notes
    -----
    The transaction closes before provider I/O, and the cursor prevents stale null rows
    from being selected repeatedly in the same run.
    """
    statement = select(Chunk.id, Chunk.index_text).where(Chunk.embedding.is_(None))
    if after_chunk_id is not None:
        statement = statement.where(Chunk.id > after_chunk_id)

    async with session.begin():
        rows = (await session.execute(statement.order_by(Chunk.id).limit(batch_size))).all()
    return [PendingEmbedding(chunk_id=row.id, index_text=row.index_text) for row in rows]


async def _store_batch(
    session: AsyncSession,
    pending: Sequence[PendingEmbedding],
    vectors: Sequence[Sequence[float]],
) -> int:
    """Bulk-store vectors guarded by null state and indexed-text identity.

    Parameters
    ----------
    session : AsyncSession
        Session that owns the bounded write transaction.
    pending : Sequence[PendingEmbedding]
        Row identities and indexed text selected before provider I/O.
    vectors : Sequence[Sequence[float]]
        Vectors corresponding to ``pending`` in the same order.

    Returns
    -------
    int
        Rows updated after both stale-write guards matched.

    Raises
    ------
    ValueError
        If pending rows and vectors have different lengths.
    """
    batch_values = values(
        Chunk.id,
        Chunk.index_text,
        Chunk.embedding,
        name="pending_embeddings",
    ).data(
        [
            (item.chunk_id, item.index_text, list(vector))
            for item, vector in zip(pending, vectors, strict=True)
        ]
    )

    async with session.begin():
        if not pending:
            return 0
        result = cast(
            CursorResult[Any],
            await session.execute(
                update(Chunk)
                .where(
                    Chunk.id == batch_values.c.id,
                    Chunk.embedding.is_(None),
                    Chunk.index_text == batch_values.c.index_text,
                )
                .values(embedding=batch_values.c.embedding.cast(Chunk.__table__.c.embedding.type))
                .returning(Chunk.id)
            ),
        )
        return len(result.scalars().all())


async def embed_missing_chunks(
    session: AsyncSession,
    provider: EmbeddingProvider,
    *,
    batch_size: int | None = None,
    on_batch: Callable[[EmbeddingBackfillResult], None] | None = None,
) -> EmbeddingBackfillResult:
    """Embed all currently missing chunks in bounded, resumable batches.

    Parameters
    ----------
    session : AsyncSession
        Session reused across bounded read and write transactions.
    provider : EmbeddingProvider
        Provider shared by document and query embeddings.
    batch_size : int | None
        Batch-size override, or ``None`` to use application settings.
    on_batch : Callable[[EmbeddingBackfillResult], None] | None
        Optional cumulative progress callback invoked after each stored batch.

    Returns
    -------
    EmbeddingBackfillResult
        Selected, stored, stale-skipped, and completed-batch counts.

    Raises
    ------
    ValueError
        If the batch size or provider output is invalid.
    RuntimeError
        If the session already owns an active transaction.

    Notes
    -----
    Provider I/O occurs between transactions. Keyset pagination advances past stale rows,
    which remain null for a later run.
    """
    effective_batch_size = get_settings().embedding_batch_size if batch_size is None else batch_size

    if effective_batch_size <= 0:
        raise ValueError("embedding batch size must be positive")
    if session.in_transaction():
        raise RuntimeError("embed_missing_chunks requires a session without an active transaction")

    selected = embedded = skipped_stale = batches = 0
    last_seen_chunk_id: int | None = None

    while pending := await _missing_batch(
        session,
        effective_batch_size,
        after_chunk_id=last_seen_chunk_id,
    ):
        batches += 1
        selected += len(pending)
        last_seen_chunk_id = max(item.chunk_id for item in pending)
        vectors = await provider.embed_documents([item.index_text for item in pending])
        vectors = validate_embeddings(
            vectors, expected_count=len(pending), dimensions=provider.dimensions
        )
        stored = await _store_batch(session, pending, vectors)
        embedded += stored
        skipped_stale += len(pending) - stored
        if on_batch is not None:
            on_batch(
                EmbeddingBackfillResult(
                    selected=selected,
                    embedded=embedded,
                    skipped_stale=skipped_stale,
                    batches=batches,
                )
            )

    return EmbeddingBackfillResult(
        selected=selected, embedded=embedded, skipped_stale=skipped_stale, batches=batches
    )
