"""Incremental immutable embedding storage and indexing progress."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
import hashlib

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, column, literal, select, values
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.db.models import Chunk, ChunkEmbedding, SnapshotChunk
from app.observability.usage import (
    UsageSink,
    observe_embedding_usage,
    persist_embedding_usage,
    provider_identity,
    usage_record,
)
from app.retrieval.embedding.openai import OpenAIEmbeddingProvider
from app.retrieval.embedding.provider import (
    EmbeddingIdentity,
    EmbeddingProvider,
    validate_embeddings,
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


def matching_embedding(identity: EmbeddingIdentity) -> ColumnElement[bool]:
    """Bind reusable vectors to the current input hash and exact configuration."""
    return and_(
        ChunkEmbedding.chunk_id == Chunk.id,
        ChunkEmbedding.input_sha256 == Chunk.index_text_sha256,
        ChunkEmbedding.provider == identity.provider,
        ChunkEmbedding.model == identity.model,
        ChunkEmbedding.dimensions == identity.dimensions,
        ChunkEmbedding.tokenizer == identity.tokenizer,
    )


def matching_snapshot_embedding(identity: EmbeddingIdentity) -> ColumnElement[bool]:
    """Bind a snapshot's frozen vector to the exact configuration that must read it.

    A snapshot row stores its vector inline, so a row frozen without one never matches.
    """
    return and_(
        SnapshotChunk.embedding_provider == identity.provider,
        SnapshotChunk.embedding_model == identity.model,
        SnapshotChunk.embedding_dimensions == identity.dimensions,
        SnapshotChunk.embedding_tokenizer == identity.tokenizer,
        SnapshotChunk.embedding.is_not(None),
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
    on_usage: UsageSink | None = None,
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

    async def record_usage(record: dict[str, object]) -> None:
        """Record actual provider work before storing vectors, including direct CLI backfill."""
        if on_usage is not None:
            await on_usage(record)
        else:
            await persist_embedding_usage(session, record)

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
        texts = [item.index_text for item in pending]
        with observe_embedding_usage(record_usage):
            if isinstance(provider, OpenAIEmbeddingProvider):
                vectors = await provider.embed_documents(texts)
            else:
                # Local tokenizers describe an estimate, not provider-reported billing usage.
                token_estimate = await asyncio.to_thread(
                    sum, (provider.count_input_tokens(text) for text in texts)
                )
                try:
                    vectors = await provider.embed_documents(texts)
                finally:
                    await record_usage(
                        usage_record(
                            identity=provider_identity(
                                provider=identity.provider,
                                local=identity.provider in {"deterministic", "sbert", "ollama"},
                                credential_slot="none",
                            ),
                            model_name=identity.model,
                            role="embedding",
                            estimated_input_tokens=token_estimate,
                            estimated_cost_usd=Decimal(0)
                            if identity.provider in {"deterministic", "sbert", "ollama"}
                            else None,
                        )
                    )
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
