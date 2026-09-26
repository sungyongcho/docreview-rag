"""Exact filtered pgvector cosine retrieval tests."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
import math
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BM25CorpusStat,
    Chunk,
    ChunkEmbedding,
    ChunkLength,
    ChunkTerm,
    EvalResult,
    EvaluationSnapshot,
    SnapshotBM25CorpusStat,
    SnapshotChunk,
    SnapshotChunkLength,
    SnapshotChunkTerm,
    SnapshotLexemeStat,
)
from app.ingestion.persistence import persist_seed_batch_with_stats
from app.ingestion.pipeline import build_seed_batch_from_filings
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from app.retrieval.indexing import bm25 as bm25_index
from app.retrieval.search import bm25, lexical, vector
from app.retrieval.types import RetrievalFilters
from tests.live_postgres import isolated_session
from tests.retrieval.support import retrieval_filing

IDENTITY = DeterministicEmbeddingProvider().identity

VALID_QUERY_VECTOR = (1.0,) + (0.0,) * 383


@asynccontextmanager
async def vector_corpus(tmp_path: Path):
    """Persist two filings with tied, orthogonal, and stale vectors."""
    filings = [retrieval_filing(tmp_path), retrieval_filing(tmp_path, other=True)]
    async with isolated_session() as session:
        await persist_seed_batch_with_stats(session, build_seed_batch_from_filings(filings))
        chunks = list(
            (await session.scalars(select(Chunk).order_by(Chunk.doc_id, Chunk.ordinal))).all()
        )
        other, first, second, third = chunks
        third.item = None
        for chunk, embedding in [
            (third, VALID_QUERY_VECTOR),
            (second, (0.0, 1.0) + (0.0,) * 382),
            (first, VALID_QUERY_VECTOR),
            (other, VALID_QUERY_VECTOR),
        ]:
            session.add(
                ChunkEmbedding(
                    chunk_id=chunk.id,
                    input_sha256=chunk.index_text_sha256,
                    embedding=list(embedding),
                    **asdict(IDENTITY),
                )
            )
        # A stale revision must not duplicate the other issuer's current hit.
        session.add(
            ChunkEmbedding(
                chunk_id=other.id,
                input_sha256="0" * 64,
                embedding=list(VALID_QUERY_VECTOR),
                **asdict(IDENTITY),
            )
        )
        await session.flush()
        yield session, chunks


@pytest.mark.live_postgres
def test_search_orders_cosine_ties_limits_results_and_preserves_evidence(tmp_path):
    """Execute pgvector ranking and return original evidence despite stale competing rows."""

    async def exercise():
        """Keep ranking and evidence assertions on one real query result."""
        async with vector_corpus(tmp_path) as (session, chunks):
            other, first, second, third = chunks
            hits = await vector.vector_search(session, VALID_QUERY_VECTOR, identity=IDENTITY, k=10)
            assert [hit.chunk_id for hit in hits] == [other.id, first.id, third.id, second.id]
            assert [hit.score for hit in hits] == pytest.approx([1.0, 1.0, 1.0, 0.0])
            assert hits[1].model_dump(exclude={"score"}) == {
                "chunk_id": first.id,
                "doc_id": first.doc_id,
                "item": first.item,
                "kind": first.kind,
                "citation": first.citation,
                "start_char": first.start_char,
                "end_char": first.end_char,
                "source_sha256": first.source_sha256,
                "body": first.body,
                "context_header": first.context_header,
                "index_text": first.index_text,
            }
            limited = await vector.vector_search(
                session, VALID_QUERY_VECTOR, identity=IDENTITY, k=1
            )
            assert [hit.chunk_id for hit in limited] == [other.id]

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_search_intersects_filters_and_includes_unnumbered_items(tmp_path):
    """Every filter restricts returned rows; None and a named Item are alternatives."""

    async def exercise():
        """Evaluate the same corpus against independent selector changes."""
        async with vector_corpus(tmp_path) as (session, chunks):
            _other, first, second, third = chunks
            filters = RetrievalFilters(
                doc_ids=(first.doc_id,),
                issuers=("NVDA",),
                fiscal_years=(2024,),
                forms=("10-K",),
                languages=("en",),
                registries=("sec",),
                items=(None, "7"),
                kinds=("text",),
            )
            hits = await vector.vector_search(
                session, VALID_QUERY_VECTOR, identity=IDENTITY, k=10, filters=filters
            )
            assert [hit.chunk_id for hit in hits] == [first.id, third.id, second.id]
            for field, values in {
                "doc_ids": ("missing",),
                "issuers": ("AMD",),
                "fiscal_years": (2023,),
                "forms": ("10-Q",),
                "languages": ("ko",),
                "registries": ("dart",),
                "items": ("8",),
                "kinds": ("table",),
            }.items():
                rejected = await vector.vector_search(
                    session,
                    VALID_QUERY_VECTOR,
                    identity=IDENTITY,
                    k=10,
                    filters=filters.model_copy(update={field: values}),
                )
                assert rejected == [], f"{field} must restrict the selected evidence"
            unnumbered = await vector.vector_search(
                session,
                VALID_QUERY_VECTOR,
                identity=IDENTITY,
                k=10,
                filters=RetrievalFilters(items=(None,)),
            )
            assert [hit.chunk_id for hit in unnumbered] == [third.id]

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "query_vector",
    [
        [0.0] * 383,
        [0.0] * 383 + [math.nan],
        [0.0] * 383 + [True],
    ],
)
def test_query_vector_requires_exactly_384_finite_numeric_values(query_vector):
    """Require query vectors to match database shape and numeric constraints."""
    with pytest.raises(ValueError):
        vector.validate_query_vector(query_vector)


def test_query_vector_rejects_zero_norm():
    """Reject a finite query vector whose norm is zero."""
    with pytest.raises(ValueError, match="nonzero norm"):
        vector.validate_query_vector([0.0] * 384)


def test_statement_rejects_nonpositive_limits():
    """Reject nonpositive statement limits."""
    with pytest.raises(ValueError, match="positive"):
        vector.vector_search_statement(VALID_QUERY_VECTOR, identity=IDENTITY, k=0)


def test_zero_limit_returns_without_database_access_and_negative_limit_fails():
    """Skip database access for zero limits and reject negative limits."""

    class Session:
        """Fail if a zero-limit vector search reaches the database."""

        async def execute(self, _statement):
            """Reject unexpected SQL execution."""
            raise AssertionError("zero-limit search must not execute SQL")

    session = cast(AsyncSession, Session())
    assert (
        asyncio.run(vector.vector_search(session, VALID_QUERY_VECTOR, identity=IDENTITY, k=0)) == []
    )
    with pytest.raises(ValueError, match="negative"):
        asyncio.run(vector.vector_search(session, VALID_QUERY_VECTOR, identity=IDENTITY, k=-1))


@pytest.mark.live_postgres
def test_snapshot_rankers_preserve_evidence_and_scores_after_live_data_changes(tmp_path):
    """All rankers retain frozen evidence after live deletion and statistics rebuild."""

    async def exercise():
        """Query a persisted snapshot using its original and mismatching identities."""
        async with vector_corpus(tmp_path) as (session, chunks):
            first = chunks[1]
            session.add(
                EvalResult(
                    id=7, suite="sec-en", config={}, metrics={}, raw_artifact_path="result.json"
                )
            )
            await session.flush()
            session.add(
                EvaluationSnapshot(
                    id=7,
                    label="Frozen evidence",
                    corpus_fingerprint="a" * 64,
                    profile={},
                    eval_result_id=7,
                )
            )
            await session.flush()
            snapshot = SnapshotChunk(
                snapshot_id=7,
                chunk_id=first.id,
                stable_key=first.stable_key,
                index_text_sha256=first.index_text_sha256,
                doc_id=first.doc_id,
                registry="sec",
                language="en",
                issuer="NVDA",
                fiscal_year=2024,
                form="10-K",
                item=first.item,
                kind=first.kind,
                ordinal=0,
                body=first.body,
                context_header=first.context_header,
                index_text=first.index_text,
                start_char=first.start_char,
                end_char=first.end_char,
                source_sha256=first.source_sha256,
                citation=first.citation,
                embedding=list(VALID_QUERY_VECTOR),
                embedding_provider=IDENTITY.provider,
                embedding_model=IDENTITY.model,
                embedding_dimensions=IDENTITY.dimensions,
                embedding_tokenizer=IDENTITY.tokenizer,
            )
            session.add(snapshot)
            await session.flush()
            terms = (
                await session.execute(
                    select(ChunkTerm.lexeme, ChunkTerm.tf).where(ChunkTerm.chunk_id == first.id)
                )
            ).all()
            length = await session.scalar(
                select(ChunkLength.dl).where(ChunkLength.chunk_id == first.id)
            )
            assert terms and length is not None
            session.add_all(
                SnapshotChunkTerm(snapshot_id=7, chunk_id=first.id, lexeme=term, tf=tf)
                for term, tf in terms
            )
            session.add_all(
                SnapshotLexemeStat(snapshot_id=7, language="en", lexeme=term, df=1)
                for term, _tf in terms
            )
            session.add(SnapshotChunkLength(snapshot_id=7, chunk_id=first.id, dl=length))
            session.add(
                SnapshotBM25CorpusStat(snapshot_id=7, language="en", n=1, avgdl=float(length))
            )
            await session.flush()
            filters = RetrievalFilters(snapshot_id=7)
            query = "research expense"
            frozen_bm25 = await bm25.bm25_search(session, query, 10, filters)
            frozen_lexical = await lexical.lexical_search(session, query, 10, filters)
            assert [hit.chunk_id for hit in frozen_bm25] == [first.id]
            assert [hit.chunk_id for hit in frozen_lexical] == [first.id]
            await session.execute(delete(Chunk).where(Chunk.id == first.id))
            await session.commit()
            await bm25_index.backfill_term_stats(session)
            assert await session.scalar(select(BM25CorpusStat.n)) == len(chunks) - 1
            assert await bm25.bm25_search(session, query, 10, filters) == frozen_bm25
            assert await lexical.lexical_search(session, query, 10, filters) == frozen_lexical
            hits = await vector.vector_search(
                session, VALID_QUERY_VECTOR, identity=IDENTITY, k=10, filters=filters
            )
            assert [(hit.chunk_id, hit.body, hit.source_sha256) for hit in hits] == [
                (snapshot.chunk_id, snapshot.body, snapshot.source_sha256)
            ]
            for field, value in {
                "provider": "other",
                "model": "other",
                "tokenizer": "other",
                "dimensions": 383,
            }.items():
                mismatched = replace(IDENTITY, **{field: value})
                query = (1.0,) + (0.0,) * (mismatched.dimensions - 1)
                assert (
                    await vector.vector_search(
                        session, query, identity=mismatched, k=10, filters=filters
                    )
                    == []
                ), field
            assert (
                await vector.vector_search(
                    session,
                    VALID_QUERY_VECTOR,
                    identity=IDENTITY,
                    k=10,
                    filters=RetrievalFilters(snapshot_id=8),
                )
                == []
            )

    asyncio.run(exercise())
