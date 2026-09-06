"""Live immutable evaluation snapshot persistence and comparison."""

import asyncio
import hashlib
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.models import Base, Chunk, ChunkEmbedding, EvalResult, GoldenRevision, SnapshotChunk
from app.evals.index_identity import index_fingerprint
from app.evals.snapshots import SnapshotService, _evaluated_embedding
from app.ingestion.chunk import compose_index_text
from app.ingestion.seed import persist_seed_batch
from app.retrieval.bm25 import backfill_term_stats, bm25_search
from app.retrieval.embeddings import EmbeddingIdentity
from app.retrieval.lexical import lexical_search
from app.retrieval.types import RetrievalFilters
from app.retrieval.vector import vector_search
from tests.ingestion.seed.support import sample_batch
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
    """Exercise independent snapshot transactions in an isolated copy of the corpus."""
    url = make_url(get_settings().database_url)
    setup_engine = create_async_engine(url, poolclass=NullPool)
    schema = f"snapshot_test_{uuid4().hex}"
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": f'"{schema}", public'}},
    )
    try:
        try:
            async with setup_engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
                await connection.run_sync(
                    lambda sync: Base.metadata.create_all(sync, checkfirst=False)
                )
        except OSError as error:
            return False, str(error)
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as session:
            await persist_seed_batch(session, sample_batch())
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
                    body=snapshot_body,
                    index_text=compose_index_text(context_header, snapshot_body),
                    index_text_sha256=hashlib.sha256(
                        compose_index_text(context_header, snapshot_body).encode()
                    ).hexdigest(),
                )
            )
            session.add(
                ChunkEmbedding(
                    chunk_id=mutable_id,
                    input_sha256=hashlib.sha256(
                        compose_index_text(context_header, snapshot_body).encode()
                    ).hexdigest(),
                    provider="test",
                    model="allowed-before-snapshot",
                    dimensions=384,
                    tokenizer="cl100k_base",
                    embedding=[1.0, *([0.0] * 383)],
                )
            )
            await session.commit()
            await backfill_term_stats(session)
            assert (
                await session.scalar(
                    select(ChunkEmbedding.model).where(
                        ChunkEmbedding.chunk_id == mutable_id,
                        ChunkEmbedding.model == "allowed-before-snapshot",
                    )
                )
                == "allowed-before-snapshot"
            )
            fingerprint = await index_fingerprint(
                session, EmbeddingIdentity("test", "allowed-before-snapshot", 384, "cl100k_base")
            )
            config = {
                "golden_sha256": "a" * 64,
                "strategy": "hybrid",
                "embedding": {
                    "provider": "test",
                    "model": "allowed-before-snapshot",
                    "dimensions": 384,
                    "tokenizer": "cl100k_base",
                },
                "admin_identity": {"corpus_fingerprint": fingerprint},
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
            candidate = await service.create(
                label="Candidate",
                eval_result_id=second.id,
                golden_revision_id=None,
                public=True,
            )
            changed_snapshot = await service.create(
                label="Changed golden",
                eval_result_id=changed.id,
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
                        index_text_sha256=hashlib.sha256(
                            compose_index_text(context_header, "mutated live body").encode()
                        ).hexdigest(),
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
                    identity=EmbeddingIdentity(
                        "test", "allowed-before-snapshot", 384, "cl100k_base"
                    ),
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
            with pytest.raises(ValueError, match="no longer matches"):
                await service.create(
                    label="Stale evaluation",
                    eval_result_id=first.id,
                    golden_revision_id=None,
                    public=False,
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
            await engine.dispose()
        return True, ""
    finally:
        await engine.dispose()
        async with setup_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await setup_engine.dispose()


@pytest.mark.live_postgres
def test_snapshot_comparison_reads_only_persisted_results(tmp_path):
    """Require live PostgreSQL for snapshot creation and metric comparison."""
    reachable, detail = asyncio.run(_exercise(tmp_path))
    if not reachable:
        live_postgres_unavailable(detail)


@pytest.mark.parametrize(
    "payload", [None, {}, {"provider": "test", "model": "model", "dimensions": 384}]
)
def test_snapshot_requires_exact_evaluated_embedding_identity(payload):
    """Reject results that cannot identify the exact vector configuration."""
    with pytest.raises(ValueError, match="embedding"):
        _evaluated_embedding({"embedding": payload})


def test_snapshot_uses_recorded_identity_including_tokenizer():
    """Resolve the evaluated tokenizer without guessing from current providers."""
    assert _evaluated_embedding(
        {
            "embedding": {
                "provider": "test",
                "model": "model",
                "dimensions": 384,
                "tokenizer": "cl100k_base",
            }
        }
    ) == EmbeddingIdentity("test", "model", 384, "cl100k_base")
