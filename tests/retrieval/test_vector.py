"""Exact filtered pgvector cosine retrieval tests."""

import asyncio
import math
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk
from app.retrieval import vector
from app.retrieval.types import RetrievalFilters
from tests.retrieval.support import RecordingSession, hit_values, normalized_sql

VALID_QUERY_VECTOR = (1.0,) + (0.0,) * 383


def test_statement_uses_exact_cosine_excludes_nulls_and_fully_orders_ties():
    """Build an exact cosine query with complete deterministic ordering."""
    statement = vector.vector_search_statement(VALID_QUERY_VECTOR, k=7)
    sql, params = normalized_sql(statement)

    assert "chunks.embedding <=>" in sql
    assert "chunks.embedding IS NOT NULL" in sql
    assert "ORDER BY distance ASC" in sql
    assert (
        'chunks.doc_id COLLATE "C" ASC, chunks.source_sha256 COLLATE "C" ASC, '
        "chunks.start_char ASC, chunks.end_char ASC, chunks.id ASC"
    ) in sql
    assert list(params.values()).count(7) == 1
    assert "hnsw" not in sql.lower()
    assert set(statement.selected_columns.keys()) == {
        "chunk_id",
        "doc_id",
        "item",
        "kind",
        "citation",
        "start_char",
        "end_char",
        "source_sha256",
        "body",
        "context_header",
        "index_text",
        "distance",
    }


def test_statement_applies_every_shared_filter_with_and_semantics():
    """Apply chunk and issuer filters with shared AND semantics."""
    filters = RetrievalFilters(
        doc_ids=("NVDA-FY2024",),
        issuers=("NVDA",),
        fiscal_years=(2024,),
        forms=("10-K",),
        items=(None, "7"),
        kinds=("table",),
    )
    sql, params = normalized_sql(
        vector.vector_search_statement(VALID_QUERY_VECTOR, k=5, filters=filters)
    )

    assert "JOIN documents ON documents.doc_id = chunks.doc_id" in sql
    assert "chunks.doc_id IN" in sql
    assert "documents.issuer IN" in sql
    assert "documents.fiscal_year IN" in sql
    assert "documents.form IN" in sql
    assert "chunks.item IS NULL" in sql
    assert "chunks.item IN" in sql
    assert "chunks.kind IN" in sql
    assert ["NVDA-FY2024"] in params.values()
    assert ["NVDA"] in params.values()
    assert [2024] in params.values()
    assert ["10-K"] in params.values()
    assert ["7"] in params.values()
    assert ["table"] in params.values()


def test_item_null_filter_does_not_emit_an_empty_in_predicate():
    """Filter unnumbered sections without emitting an empty IN clause."""
    sql, _params = normalized_sql(
        vector.vector_search_statement(
            VALID_QUERY_VECTOR,
            k=3,
            filters=RetrievalFilters(items=(None,)),
        )
    )

    assert "chunks.item IS NULL" in sql
    assert "chunks.item IN" not in sql


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


@pytest.mark.parametrize("k", [0, -1])
def test_statement_rejects_nonpositive_limits(k):
    """Reject nonpositive statement limits."""
    with pytest.raises(ValueError, match="positive"):
        vector.vector_search_statement(VALID_QUERY_VECTOR, k=k)


def test_search_returns_complete_chunk_hits_and_similarity_scores():
    """Return complete typed evidence with cosine similarity scores."""
    values = hit_values()
    chunk = SimpleNamespace(
        id=values["chunk_id"],
        doc_id=values["doc_id"],
        item=values["item"],
        kind=values["kind"],
        citation=values["citation"],
        start_char=values["start_char"],
        end_char=values["end_char"],
        source_sha256=values["source_sha256"],
        body=values["body"],
        context_header=values["context_header"],
        index_text=values["index_text"],
    )

    class Result:
        def mappings(self):
            return SimpleNamespace(
                all=lambda: [
                    {
                        "chunk_id": chunk.id,
                        "doc_id": chunk.doc_id,
                        "item": chunk.item,
                        "kind": chunk.kind,
                        "citation": chunk.citation,
                        "start_char": chunk.start_char,
                        "end_char": chunk.end_char,
                        "source_sha256": chunk.source_sha256,
                        "body": chunk.body,
                        "context_header": chunk.context_header,
                        "index_text": chunk.index_text,
                        "distance": 0.25,
                    }
                ]
            )

    session = RecordingSession(Result())
    hits = asyncio.run(vector.vector_search(cast(AsyncSession, session), VALID_QUERY_VECTOR, k=4))

    assert len(session.statements) == 1
    assert len(hits) == 1
    assert hits[0].model_dump() == {**values, "score": 0.75}


def test_zero_limit_returns_without_database_access_and_negative_limit_fails():
    """Skip database access for zero limits and reject negative limits."""

    class Session:
        async def execute(self, _statement):
            raise AssertionError("zero-limit search must not execute SQL")

    session = cast(AsyncSession, Session())
    assert asyncio.run(vector.vector_search(session, VALID_QUERY_VECTOR, k=0)) == []
    with pytest.raises(ValueError, match="negative"):
        asyncio.run(vector.vector_search(session, VALID_QUERY_VECTOR, k=-1))


def test_model_has_no_approximate_vector_index_without_measurement():
    """Keep approximate vector indexes disabled until measurements justify one."""
    chunk_table = Chunk.__table__
    assert isinstance(chunk_table, Table)
    index_names = {index.name for index in chunk_table.indexes}

    assert "ix_chunks_embedding_hnsw" not in index_names
    assert not any(
        index.dialect_options["postgresql"].get("using") == "hnsw" for index in chunk_table.indexes
    )
