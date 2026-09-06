"""Async embedding providers and resumable PostgreSQL embedding backfill."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import math
import re
from typing import Any, cast
import unicodedata

from openai import AsyncOpenAI
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Chunk
from app.retrieval.types import finite_float


def validate_texts(values: Sequence[str]) -> list[str]:
    """Return validated, materialized embedding inputs.

    Parameters
    ----------
    values : Sequence[str]
        Input texts supplied by a caller.

    Returns
    -------
    list[str]
        A materialized list that preserves caller order.

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
        Finite, dimensionally valid vectors materialized as floats.

    Raises
    ------
    ValueError
        If dimensions are invalid or provider output violates the count, shape,
        numeric-type, or finiteness contract.
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
        vectors.append(
            [
                finite_float(component, nonnumeric=nonnumeric, nonfinite=nonfinite)
                for component in value
            ]
        )
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
        inputs = validate_texts(texts)
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
    """Build the configured provider without doing work at import time.

    Parameters
    ----------
    settings : Settings | None
        Validated settings to use, or ``None`` to load the cached application settings.
    client : AsyncOpenAI | None
        Optional client override used by the OpenAI provider.

    Returns
    -------
    EmbeddingProvider
        The deterministic or OpenAI provider selected by configuration.
    """
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
    """Load one stable batch and close its transaction before provider I/O.

    Parameters
    ----------
    session : AsyncSession
        Session that owns the bounded read transaction.
    batch_size : int
        Maximum number of missing rows to select.

    Returns
    -------
    list[PendingEmbedding]
        Missing rows ordered by stable chunk id.

    Notes
    -----
    The read transaction closes before the caller starts provider I/O.
    """
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
    """Store current vectors and reject rows changed during provider I/O.

    Parameters
    ----------
    session : AsyncSession
        Session that owns the bounded write transaction.
    pending : Sequence[PendingEmbedding]
        Immutable row identities and indexed text selected before provider I/O.
    vectors : Sequence[Sequence[float]]
        Validated vectors corresponding to ``pending`` in the same order.

    Returns
    -------
    int
        Number of rows that still matched the null-vector and text-version guards.

    Raises
    ------
    ValueError
        If ``pending`` and ``vectors`` contain different numbers of entries.
    """
    embedded = 0
    async with session.begin():
        for item, vector in zip(pending, vectors, strict=True):
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(Chunk)
                    .where(
                        Chunk.id == item.chunk_id,
                        Chunk.embedding.is_(None),
                        Chunk.index_text == item.index_text,
                    )
                    .values(embedding=list(vector))
                ),
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
    """Embed all currently missing chunks in bounded, resumable batches.

    Parameters
    ----------
    session : AsyncSession
        Session reused across bounded read and write transactions.
    provider : EmbeddingProvider
        Provider used for both document and query compatible vectors.
    batch_size : int | None
        Batch size override, or ``None`` to use application settings.

    Returns
    -------
    EmbeddingBackfillResult
        Selected, stored, stale-skipped, and completed-batch counts.

    Raises
    ------
    ValueError
        If the effective batch size is not positive or provider output is invalid.
    RuntimeError
        If the supplied session already owns an active transaction.

    Notes
    -----
    Provider I/O occurs between the read and write transactions. A later run resumes
    from rows whose embedding remains null.
    """
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
            vectors, expected_count=len(pending), dimensions=provider.dimensions
        )
        stored = await _store_batch(session, pending, vectors)
        embedded += stored
        skipped_stale += len(pending) - stored

    return EmbeddingBackfillResult(
        selected=selected, embedded=embedded, skipped_stale=skipped_stale, batches=batches
    )
