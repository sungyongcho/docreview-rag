"""Database enforcement of filing identity, source provenance, and evaluation records."""

import asyncio

import pytest
from sqlalchemy import func, insert, null, select, update
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    DIM,
    BM25CorpusStat,
    Chunk,
    ChunkEmbedding,
    Document,
    EvalResult,
    LexemeStat,
    ParsedStructure,
)
from app.ingestion.seed import persist_seed_batch
from app.retrieval.bm25 import backfill_term_stats
from tests.ingestion.seed.support import sample_batch
from tests.live_postgres import isolated_session


@pytest.mark.live_postgres
def test_source_rows_reject_incomplete_identity_and_provenance():
    """Reject mismatched registry metadata and missing persisted source identity."""

    async def exercise():
        """Start with a valid filing so each rejected update isolates one broken value."""
        async with isolated_session() as session:
            await persist_seed_batch(session, sample_batch())
            invalid_updates = (
                (Document, {"registry": "dart"}),
                (Document, {"language": "ENG"}),
                (Document, {"language": None}),
                (ParsedStructure, {"source_length": None}),
                (ParsedStructure, {"source_sha256": None}),
                (ParsedStructure, {"parse_status": None}),
                (ParsedStructure, {"item_index": null()}),
            )
            for model, values in invalid_updates:
                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        await session.execute(update(model).values(**values))

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_chunks_reject_invalid_evidence_and_duplicate_identity():
    """Enforce chunk evidence and identity while indexing each corpus language separately."""

    async def exercise():
        """Exercise actual PostgreSQL constraints against a valid seeded chunk."""
        batch = sample_batch()
        async with isolated_session() as session:
            await persist_seed_batch(session, batch)
            await session.execute(
                update(Chunk)
                .where(Chunk.ordinal == 0)
                .values(language="ko", lexical_text="context operating 매출")
            )
            matched = await session.scalar(
                select(
                    Chunk.content_tsv.op("@@")(func.plainto_tsquery("simple", "operating 매출"))
                ).where(Chunk.ordinal == 0)
            )
            assert matched is True
            await session.commit()
            await backfill_term_stats(session)
            corpus_sizes = (
                await session.execute(
                    select(BM25CorpusStat.language, BM25CorpusStat.n).order_by(
                        BM25CorpusStat.language
                    )
                )
            ).all()
            assert corpus_sizes == [("en", 1), ("ko", 1)]
            shared_lexeme_counts = (
                await session.execute(
                    select(LexemeStat.language, LexemeStat.df)
                    .where(LexemeStat.lexeme == "context")
                    .order_by(LexemeStat.language)
                )
            ).all()
            assert shared_lexeme_counts == [("en", 1), ("ko", 1)]
            for values in (
                {"ordinal": -1},
                {"kind": "image"},
                {"start_char": -1},
                {"start_char": 1000, "end_char": 999},
                {"source_sha256": "bad"},
                {"language": "ko", "lexical_text": None},
                {"language": "en", "lexical_text": "operating"},
            ):
                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        await session.execute(update(Chunk).values(**values))
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(insert(Chunk).values(**batch.chunks[0].values()))
            chunk_id = await session.scalar(select(Chunk.id).where(Chunk.ordinal == 0))
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(
                        insert(ChunkEmbedding).values(
                            chunk_id=chunk_id,
                            input_sha256="a" * 64,
                            provider="test",
                            model="test",
                            dimensions=DIM,
                            tokenizer="test",
                            embedding=None,
                        )
                    )

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_evaluation_rows_preserve_provenance_and_reject_invalid_values():
    """Store one complete evaluation and reject empty names, non-object JSON, and null data."""

    async def exercise():
        """Read back server-generated time and protect each persisted provenance field."""
        async with isolated_session() as session:
            row = EvalResult(
                suite="contract",
                config={"strategy": "lexical"},
                metrics={"mrr": 0.5},
                raw_artifact_path="evaluation.json",
            )
            session.add(row)
            await session.flush()
            session.expire_all()
            stored = (await session.execute(select(EvalResult.__table__))).mappings().one()
            assert stored["suite"] == "contract"
            assert stored["config"] == {"strategy": "lexical"}
            assert stored["metrics"] == {"mrr": 0.5}
            assert stored["raw_artifact_path"] == "evaluation.json"
            assert stored["created_at"].utcoffset() is not None
            for values in (
                {"suite": " "},
                {"config": []},
                {"metrics": []},
                {"raw_artifact_path": " "},
                {"suite": None},
                {"config": None},
                {"metrics": None},
                {"raw_artifact_path": None},
                {"created_at": None},
            ):
                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        await session.execute(update(EvalResult).values(**values))

    asyncio.run(exercise())
