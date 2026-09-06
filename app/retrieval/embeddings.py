"""Async embedding providers and resumable PostgreSQL embedding backfill."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import math
import re
from typing import Literal, Protocol, cast
import unicodedata

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, column, literal, select, values
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import Settings, get_settings
from app.db.models import Chunk, ChunkEmbedding
from app.ingestion.tokens import MAX_REQUEST_INPUTS, MAX_REQUEST_TOKENS, tokenizer, validate_request
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


@dataclass(frozen=True, slots=True)
class EmbeddingIdentity:
    """Provider, model, and dimensions defining one vector space."""

    provider: str
    model: str
    dimensions: int
    tokenizer: str

    def __post_init__(self) -> None:
        """Reject incomplete identities before querying or persisting vector spaces."""
        if not self.provider.strip() or not self.model.strip() or not self.tokenizer.strip():
            raise ValueError("embedding configuration fields must be nonblank")
        if self.dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")


class EmbeddingProvider(ABC):
    """Async provider boundary shared by query and document embeddings."""

    dimensions: int

    @property
    @abstractmethod
    def max_input_tokens(self) -> int:
        """Declare the model's maximum complete input, including special tokens."""

    @abstractmethod
    def count_input_tokens(self, text: str) -> int:
        """Count complete model input without truncating it."""

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch in caller order."""

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query through the same model and validation path."""
        return (await self.embed_documents([text]))[0]

    @property
    @abstractmethod
    def identity(self) -> EmbeddingIdentity:
        """Declare the complete provider, model, dimension, and tokenizer configuration."""


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Stable token-hashing vectors for tests and local exercises."""

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        self.dimensions = dimensions

    @property
    def max_input_tokens(self) -> int:
        """Apply the shared hard ceiling to the explicit deterministic tokenizer."""
        return 8192

    def count_input_tokens(self, text: str) -> int:
        """Count the exact normalized Unicode words used by deterministic embedding."""
        validate_texts([text])
        return max(1, len(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())))

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Hash normalized alphanumeric tokens into unit-length bag-of-words vectors."""
        inputs = validate_texts(texts)
        if any(self.count_input_tokens(text) > self.max_input_tokens for text in inputs):
            raise ValueError("deterministic input exceeds its 8192-token limit")
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

    @property
    def identity(self) -> EmbeddingIdentity:
        """Return the deterministic token-hash identity."""
        return EmbeddingIdentity(
            "deterministic",
            f"token-hash-{self.dimensions}",
            self.dimensions,
            "unicode-alnum:nfkc:casefold:v1",
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
        model: str = "text-embedding-3-large",
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

    @property
    def max_input_tokens(self) -> int:
        """Return the supported complete-input OpenAI embedding limit."""
        return 8192

    def count_input_tokens(self, text: str) -> int:
        """Count literal source text with the actual embedding model encoding."""
        validate_texts([text])
        return len(tokenizer(self.model).encode(text, disallowed_special=()))

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Preflight all complete inputs, then issue safely bounded provider requests."""
        inputs = validate_texts(texts)
        counts = [validate_request([text], model=self.model)[0] for text in inputs]
        batches: list[list[str]] = []
        current: list[str] = []
        total = 0
        for text, count in zip(inputs, counts, strict=True):
            if current and (
                len(current) == MAX_REQUEST_INPUTS or total + count > MAX_REQUEST_TOKENS
            ):
                batches.append(current)
                current = []
                total = 0
            current.append(text)
            total += count
        if current:
            batches.append(current)
        vectors: list[list[float]] = []
        for batch in batches:
            vectors.extend(await self._embed_request(batch))
        return vectors

    async def _embed_request(self, inputs: list[str]) -> list[list[float]]:
        """Issue one preflighted request and restore its exact input order."""
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

    @property
    def identity(self) -> EmbeddingIdentity:
        """Return the configured OpenAI embedding identity."""
        return EmbeddingIdentity(
            "openai",
            self.model,
            self.dimensions,
            f"tiktoken:{tokenizer(self.model).name}:literal-special:v1",
        )


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
    input_sha256: str

    def __post_init__(self) -> None:
        """Bind a pending vector to the exact indexed input it represents."""
        if hashlib.sha256(self.index_text.encode("utf-8")).hexdigest() != self.input_sha256:
            raise ValueError("pending embedding input hash disagrees with indexed text")


@dataclass(frozen=True, slots=True)
class EmbeddingBackfillResult:
    """Observable result of a resumable embedding backfill."""

    selected: int
    embedded: int
    skipped_stale: int
    batches: int


def matching_embedding(
    identity: EmbeddingIdentity, *, chunk: type[Chunk] = Chunk
) -> ColumnElement[bool]:
    """Bind reusable vectors to the current input hash and exact configuration."""
    return and_(
        ChunkEmbedding.chunk_id == chunk.id,
        ChunkEmbedding.input_sha256 == chunk.index_text_sha256,
        ChunkEmbedding.provider == identity.provider,
        ChunkEmbedding.model == identity.model,
        ChunkEmbedding.dimensions == identity.dimensions,
        ChunkEmbedding.tokenizer == identity.tokenizer,
    )


async def _missing_batch(
    session: AsyncSession,
    batch_size: int,
    *,
    identity: EmbeddingIdentity,
    after_chunk_id: int | None = None,
    document_ids: tuple[str, ...] | None = None,
) -> list[PendingEmbedding]:
    """Select exact missing configurations in a closed bounded read transaction."""
    exists = select(ChunkEmbedding.chunk_id).where(matching_embedding(identity)).exists()
    statement = select(Chunk.id, Chunk.index_text, Chunk.index_text_sha256).where(~exists)
    if after_chunk_id is not None:
        statement = statement.where(Chunk.id > after_chunk_id)
    if document_ids is not None:
        statement = statement.where(Chunk.doc_id.in_(document_ids))
    async with session.begin():
        rows = (await session.execute(statement.order_by(Chunk.id).limit(batch_size))).all()
    return [PendingEmbedding(row.id, row.index_text, row.index_text_sha256) for row in rows]


async def _store_batch(
    session: AsyncSession,
    pending: Sequence[PendingEmbedding],
    vectors: Sequence[Sequence[float]],
    identity: EmbeddingIdentity,
) -> int:
    """Insert vectors from locked current chunks, preserving all other configurations."""
    validated = validate_embeddings(
        vectors, expected_count=len(pending), dimensions=identity.dimensions
    )
    if not pending:
        return 0
    batch_values = values(
        column("chunk_id", ChunkEmbedding.__table__.c.chunk_id.type),
        column("input_sha256", ChunkEmbedding.__table__.c.input_sha256.type),
        column("index_text", Chunk.__table__.c.index_text.type),
        column("embedding", ChunkEmbedding.__table__.c.embedding.type),
        name="pending_embeddings",
    ).data(
        [
            (item.chunk_id, item.input_sha256, item.index_text, vector)
            for item, vector in zip(pending, validated, strict=True)
        ]
    )
    current = (
        select(
            Chunk.id,
            Chunk.index_text_sha256,
            literal(identity.provider),
            literal(identity.model),
            literal(identity.dimensions),
            literal(identity.tokenizer),
            batch_values.c.embedding.cast(Vector(identity.dimensions)),
        )
        .select_from(Chunk)
        .join(
            batch_values,
            and_(
                Chunk.id == batch_values.c.chunk_id,
                Chunk.index_text_sha256 == batch_values.c.input_sha256,
                Chunk.index_text == batch_values.c.index_text,
            ),
        )
        .with_for_update(of=Chunk)
    )
    statement = (
        insert(ChunkEmbedding)
        .from_select(
            [
                "chunk_id",
                "input_sha256",
                "provider",
                "model",
                "dimensions",
                "tokenizer",
                "embedding",
            ],
            current,
        )
        .on_conflict_do_nothing()
        .returning(ChunkEmbedding.chunk_id)
    )
    async with session.begin():
        result = await session.execute(statement)
        return len(result.scalars().all())


async def embed_missing_chunks(
    session: AsyncSession,
    provider: EmbeddingProvider,
    *,
    batch_size: int | None = None,
    on_batch: Callable[[EmbeddingBackfillResult], None] | None = None,
    document_ids: tuple[str, ...] | None = None,
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
    which remain missing for this configuration until a later run.
    """
    effective_batch_size = get_settings().embedding_batch_size if batch_size is None else batch_size

    if effective_batch_size <= 0:
        raise ValueError("embedding batch size must be positive")
    if session.in_transaction():
        raise RuntimeError("embed_missing_chunks requires a session without an active transaction")

    if document_ids is not None and any(not doc_id for doc_id in document_ids):
        raise ValueError("embedding document selections require nonempty identities")
    if document_ids == ():
        return EmbeddingBackfillResult(0, 0, 0, 0)
    identity = provider.identity
    selected = embedded = skipped_stale = batches = 0
    last_seen_chunk_id: int | None = None

    while pending := await _missing_batch(
        session,
        effective_batch_size,
        after_chunk_id=last_seen_chunk_id,
        identity=identity,
        document_ids=document_ids,
    ):
        batches += 1
        selected += len(pending)
        last_seen_chunk_id = max(item.chunk_id for item in pending)
        vectors = await provider.embed_documents([item.index_text for item in pending])
        vectors = validate_embeddings(
            vectors, expected_count=len(pending), dimensions=provider.dimensions
        )
        stored = await _store_batch(session, pending, vectors, identity)
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
