"""Live immutable evaluation snapshot persistence and comparison."""

import asyncio
import hashlib
import json

import pytest
from sqlalchemy import select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.models import Chunk, Document, EvalResult, GoldenRevision, SnapshotChunk
from app.evals.snapshots import SnapshotService
from app.ingestion.chunk import compose_index_text
from app.retrieval.bm25 import backfill_term_stats, bm25_search
from app.retrieval.embeddings import EmbeddingIdentity
from app.retrieval.lexical import lexical_search
from app.retrieval.types import RetrievalFilters
from app.retrieval.vector import vector_search
from tests.live_postgres import live_postgres_unavailable


def _artifact(question: str, rank: int | None) -> dict[str, object]:
    """Build one minimal stored evaluation artifact with a common case."""
    return {
        "cases": [
            {
                "golden": {"id": "case-1", "question": question},
                "score": {"first_relevant_rank": rank},
                "hits": [],
            }
        ]
    }


async def _exercise(tmp_path) -> tuple[bool, str]:
    """Create and compare two snapshots inside one rolled-back connection."""
    engine = create_async_engine(make_url(get_settings().database_url), poolclass=NullPool)
    try:
        try:
            connection = await engine.connect()
        except Exception as error:
            return False, str(error)
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as session:
            mutable_id = await session.scalar(select(Chunk.id).order_by(Chunk.id).limit(1))
            assert mutable_id is not None
            context_header = await session.scalar(
                select(Chunk.context_header).where(Chunk.id == mutable_id)
            )
            assert context_header is not None
            snapshot_body = "uniquesnapshotterm evidence"
            await session.execute(
                update(Chunk)
                .where(Chunk.id == mutable_id)
                .values(
                    embedding=[1.0, *([0.0] * 383)],
                    embedding_provider="test",
                    embedding_model="allowed-before-snapshot",
                    embedding_dimensions=384,
                    body=snapshot_body,
                    index_text=compose_index_text(context_header, snapshot_body),
                )
            )
            await session.commit()
            await backfill_term_stats(session)
            assert (
                await session.scalar(select(Chunk.embedding_model).where(Chunk.id == mutable_id))
                == "allowed-before-snapshot"
            )
            documents = tuple(await session.scalars(select(Document).order_by(Document.doc_id)))
            digest = hashlib.sha256()
            for document in documents:
                digest.update(f"{document.doc_id}:{document.source_sha256}\n".encode())
            config = {
                "golden_sha256": "a" * 64,
                "strategy": "hybrid",
                "admin_identity": {"corpus_fingerprint": digest.hexdigest()},
            }
            baseline_path = tmp_path / "snapshot-first.json"
            candidate_path = tmp_path / "snapshot-second.json"
            changed_path = tmp_path / "snapshot-changed.json"
            baseline_path.write_text(json.dumps(_artifact("Original question?", 2)))
            candidate_path.write_text(json.dumps(_artifact("Original question?", 1)))
            changed_path.write_text(json.dumps(_artifact("Revised question?", None)))
            first = EvalResult(
                suite="snapshot-test",
                config=config,
                metrics={"mrr": 0.4},
                raw_artifact_path=str(baseline_path),
            )
            second = EvalResult(
                suite="snapshot-test",
                config=config,
                metrics={"mrr": 0.6},
                raw_artifact_path=str(candidate_path),
            )
            changed = EvalResult(
                suite="snapshot-test",
                config={**config, "golden_sha256": "c" * 64},
                metrics={"mrr": 0.5},
                raw_artifact_path=str(changed_path),
            )
            session.add_all((first, second, changed))
            await session.commit()
            await session.refresh(first)
            await session.refresh(second)
            await session.refresh(changed)
            mismatched_golden = GoldenRevision(
                suite_id="snapshot-mismatch-test",
                version=1,
                status="published",
                payload=[],
                sha256="b" * 64,
            )
            session.add(mismatched_golden)
            await session.commit()
            await session.refresh(mismatched_golden)
        service = SnapshotService(session_factory=factory, artifact_dir=tmp_path)
        try:
            with pytest.raises(ValueError, match="does not match"):
                await service.create(
                    label="Mismatched golden",
                    eval_result_id=first.id,
                    golden_revision_id=mismatched_golden.id,
                    public=False,
                )
            baseline = await service.create(
                label="Baseline",
                eval_result_id=first.id,
                golden_revision_id=None,
                public=True,
            )
            async with factory() as session:
                retained = (
                    await session.execute(
                        select(
                            SnapshotChunk.chunk_id,
                            SnapshotChunk.body,
                            SnapshotChunk.embedding_model,
                        ).where(
                            SnapshotChunk.snapshot_id == baseline.snapshot_id,
                            SnapshotChunk.chunk_id == mutable_id,
                        )
                    )
                ).one()
                await session.execute(
                    update(Chunk)
                    .where(Chunk.id == retained.chunk_id)
                    .values(
                        body="mutated live body",
                        index_text=compose_index_text(context_header, "mutated live body"),
                        embedding=[0.0, 1.0, *([0.0] * 382)],
                        embedding_model="changed-after-snapshot",
                    )
                )
                await session.commit()
                frozen = (
                    await session.execute(
                        select(SnapshotChunk.body, SnapshotChunk.embedding_model).where(
                            SnapshotChunk.snapshot_id == baseline.snapshot_id,
                            SnapshotChunk.chunk_id == retained.chunk_id,
                        )
                    )
                ).one()
                assert frozen.body == retained.body
                assert frozen.embedding_model == retained.embedding_model
                hits = await vector_search(
                    session,
                    [1.0, *([0.0] * 383)],
                    k=1,
                    filters=RetrievalFilters(snapshot_id=baseline.snapshot_id),
                    identity=EmbeddingIdentity("test", "allowed-before-snapshot", 384),
                )
                assert hits[0].chunk_id == retained.chunk_id
                lexical_hits = await lexical_search(
                    session,
                    "uniquesnapshotterm",
                    k=1,
                    filters=RetrievalFilters(snapshot_id=baseline.snapshot_id),
                )
                bm25_hits = await bm25_search(
                    session,
                    "uniquesnapshotterm",
                    k=1,
                    filters=RetrievalFilters(snapshot_id=baseline.snapshot_id),
                )
                assert lexical_hits[0].chunk_id == retained.chunk_id
                assert bm25_hits[0].chunk_id == retained.chunk_id
            candidate = await service.create(
                label="Candidate",
                eval_result_id=second.id,
                golden_revision_id=None,
                public=True,
            )
            comparison = await service.compare(
                baseline.snapshot_id,
                candidate.snapshot_id,
                public_only=True,
            )
            assert comparison.directly_comparable is True
            assert comparison.metrics[0].delta == pytest.approx(0.2)
            assert comparison.cases[0].transition == "stable_hit"
            assert comparison.cases[0].rank_delta == -1
            changed_snapshot = await service.create(
                label="Changed golden",
                eval_result_id=changed.id,
                golden_revision_id=None,
                public=True,
            )
            side_by_side = await service.compare(
                baseline.snapshot_id,
                changed_snapshot.snapshot_id,
                public_only=True,
            )
            assert side_by_side.directly_comparable is False
            assert side_by_side.metrics[0].delta is None
            assert side_by_side.common_case_count == 1
            assert side_by_side.cases[0].baseline_question == "Original question?"
            assert side_by_side.cases[0].candidate_question == "Revised question?"
            assert side_by_side.cases[0].rank_delta is None
            assert len(await service.list(public_only=True)) >= 2
        finally:
            await transaction.rollback()
            await connection.close()
        return True, ""
    finally:
        await engine.dispose()


@pytest.mark.live_postgres
def test_snapshot_comparison_reads_only_persisted_results(tmp_path):
    """Require live PostgreSQL for snapshot creation and metric comparison."""
    reachable, detail = asyncio.run(_exercise(tmp_path))
    if not reachable:
        live_postgres_unavailable(detail)
