"""Arm naming, ordering, and artifact identity shared by the evaluation commands."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import re
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.canonical_json import canonical_json
from app.db.models import Chunk, ChunkEmbedding, Document, ParsedStructure
from app.db.queries import join_current_parse
from app.retrieval.embedding.provider import EmbeddingIdentity
from app.retrieval.indexing.embeddings import matching_embedding

# Every evaluation command names its arms in lowercase kebab-case, orders them by the
# same retrieval path and ranker precedence, and writes artifacts under the same
# timestamped filename. Holding those three rules in one place is what keeps two
# commands from disagreeing about the order a matrix is reported in, or about what an
# artifact already sitting in ``data/eval_runs`` is called.
ARM_NAME: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STRATEGY_ORDER: Final[dict[str, int]] = {"lexical": 0, "vector": 1, "hybrid": 2}
RANKER_ORDER: Final[dict[str, int]] = {"ts_rank_cd": 0, "bm25": 1}
RANKER_SLUG: Final[dict[str, str]] = {"ts_rank_cd": "ts-rank-cd", "bm25": "bm25"}
EVALUATED_GOLDEN_KEY: Final[str] = "evaluated_golden_sha256"


def evaluated_golden_sha256(cases: Sequence[Mapping[str, Any]]) -> str:
    """Hash evaluated, source-bound cases independently of JSON key and case order.

    This identifies the exact questions and bound source spans used for scoring.
    The original dataset file digest remains separate provenance and is never rewritten.
    """
    payload = sorted(cases, key=lambda case: case["id"])
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def artifact_filename(recorded_at: datetime, arm_name: str) -> str:
    """Return a UTC-timestamped JSON filename for one arm.

    ``arm_name`` is re-checked here rather than trusted from the caller: it is
    interpolated straight into a path, so a name carrying a separator would place the
    artifact outside the directory the caller chose.

    Raises
    ------
    ValueError
        If ``recorded_at`` is timezone-naive or ``arm_name`` is not kebab-case.
    """
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    if ARM_NAME.fullmatch(arm_name) is None:
        raise ValueError("arm name must be lowercase kebab-case")
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{arm_name}.json"


def _encode(value: object) -> bytes:
    """Encode index evidence deterministically without lossy string fallbacks."""
    return canonical_json(value).encode()


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
