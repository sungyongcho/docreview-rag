"""Database enforcement of filing identity, source provenance, and evaluation records."""

import asyncio
from pathlib import Path
import subprocess
import sys
from typing import get_args, get_type_hints

import pytest
from sqlalchemy import func, insert, null, select, update
from sqlalchemy.exc import IntegrityError

from app.config import EMBEDDING_DIMENSIONS
from app.db.models import (
    TABLE_CELL_STATUSES,
    TABLE_UNIT_STATUSES,
    BM25CorpusStat,
    Chunk,
    ChunkEmbedding,
    ChunkTableCell,
    Document,
    EvalResult,
    LexemeStat,
    ParsedStructure,
    ParsedTable,
    TableCell,
    TableSourceCell,
    TableSourceFact,
)
from app.figures.tables import CellStatus, TableUnit
from app.ingestion.persistence import persist_seed_batch
from app.retrieval.indexing.bm25 import backfill_term_stats
from tests.ingestion.seed.support import sample_batch, table_batch, tagged_table_batch
from tests.live_postgres import isolated_session


def test_model_import_does_not_require_provider_configuration(tmp_path):
    """Load the fixed schema while unrelated provider configuration is deliberately invalid."""
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.db.models import ChunkEmbedding; "
            "print(ChunkEmbedding.__table__.c.embedding.type.dim)",
        ],
        cwd=tmp_path,
        env={
            "PYTHONPATH": str(root),
            "EMBEDDING_PROVIDER": "openai",
            "REVIEW_MODEL": "invalid-provider-setting",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "384"


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
                            dimensions=EMBEDDING_DIMENSIONS,
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


@pytest.mark.live_postgres
def test_table_rows_reject_unknown_statuses_and_incomplete_readings():
    """Keep stored table cells inside their vocabulary and their readings all-or-nothing."""

    async def exercise():
        """Seed one real table, then try each invalid change inside a savepoint."""
        async with isolated_session() as session:
            await persist_seed_batch(session, table_batch())
            for model, values in (
                (TableCell, {"status": "guessed"}),
                (TableCell, {"status": "known", "value": None}),
                (TableCell, {"value_row": None}),
                (TableSourceCell, {"reading_years": None}),
                (TableSourceCell, {"rowspan": 0}),
                (ParsedTable, {"unit_status": "probable"}),
                (ChunkTableCell, {"text_end": -1}),
            ):
                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        statement = update(model).values(**values)
                        if model is TableSourceCell:
                            statement = statement.where(TableSourceCell.reading_values.is_not(None))
                        if model is TableCell and "value_row" in values:
                            statement = statement.where(TableCell.value_row.is_not(None))
                        await session.execute(statement)

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_source_facts_reject_bad_spans_and_unknown_contexts():
    """Keep each stored fact inside a real span and tied to a context of its own parse."""

    async def exercise():
        """Seed the tagged table, then try each invalid change inside a savepoint."""
        async with isolated_session() as session:
            await persist_seed_batch(session, tagged_table_batch())
            for values in (
                {"end_char": TableSourceFact.start_char},
                {"ordinal": -1},
                {"context_id": "missing"},
                {"unit_id": "missing"},
            ):
                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        await session.execute(update(TableSourceFact).values(**values))

    asyncio.run(exercise())


def test_stored_statuses_are_the_statuses_the_reader_assigns():
    """Allow in the database exactly the cell and unit statuses the table reader assigns."""
    assert get_args(CellStatus) == TABLE_CELL_STATUSES
    assert get_args(get_type_hints(TableUnit)["status"]) == TABLE_UNIT_STATUSES
