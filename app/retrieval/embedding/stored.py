"""Select the stored vectors that one embedding configuration may read."""

from sqlalchemy import and_
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Chunk, ChunkEmbedding, SnapshotChunk
from app.retrieval.embedding.provider import EmbeddingIdentity


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
