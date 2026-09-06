"""Deterministic identity of the exact live index evaluated or frozen."""

from dataclasses import asdict
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, ChunkEmbedding, Document, ParsedStructure
from app.db.queries import join_current_parse
from app.retrieval.embeddings import EmbeddingIdentity, matching_embedding


def _encode(value: object) -> bytes:
    """Encode index evidence deterministically without lossy string fallbacks."""
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


async def index_fingerprint(session: AsyncSession, identity: EmbeddingIdentity) -> str:
    """Hash document sources, chunk inputs, structure, and exact selected vectors."""
    documents = (
        await session.execute(
            join_current_parse(select(Document.doc_id, ParsedStructure.source_sha256)).order_by(
                Document.doc_id
            )
        )
    ).all()
    if not documents:
        raise ValueError("evaluation requires an ingested corpus")
    digest = hashlib.sha256(_encode(asdict(identity)))
    for row in documents:
        digest.update(_encode(tuple(row)))
    rows = (
        await session.execute(
            select(
                Chunk.doc_id,
                Chunk.stable_key,
                Chunk.index_text_sha256,
                Chunk.ordinal,
                Chunk.language,
                Chunk.kind,
                Chunk.item,
                Chunk.table_fragment,
                Chunk.text_fragment,
                ChunkEmbedding.embedding,
            )
            .outerjoin(ChunkEmbedding, matching_embedding(identity))
            .order_by(Chunk.doc_id, Chunk.stable_key)
        )
    ).all()
    for row in rows:
        vector = None if row[-1] is None else [float(value) for value in row[-1]]
        digest.update(_encode((*row[:-1], vector)))
    return digest.hexdigest()
