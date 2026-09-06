"""L3: exact filtered pgvector cosine retrieval."""

import asyncio
import importlib
import math
import os
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models import Chunk
from app.retrieval.types import RetrievalFilters
from tests.retrieval.test_01_contract import hit_values
from tests.support import need

VECTOR_MODULE_NAME = os.getenv("RETRIEVAL_VECTOR_MODULE", "app.retrieval.vector")
V = importlib.import_module(VECTOR_MODULE_NAME)


def normalized_sql(statement) -> tuple[str, dict[str, object]]:
    """Compile a statement with PostgreSQL placeholders and normalized whitespace."""
    compiled = statement.compile(dialect=postgresql.dialect())
    return " ".join(str(compiled).split()), compiled.params


def test_statement_uses_exact_cosine_excludes_nulls_and_fully_orders_ties():
    need(V, "vector_search_statement")
    statement = V.vector_search_statement([0.0] * 384, k=7)
    sql, params = normalized_sql(statement)

    assert "chunks.embedding <=>" in sql
    assert "chunks.embedding IS NOT NULL" in sql
    assert "ORDER BY distance ASC" in sql
    assert (
        "chunks.doc_id ASC, chunks.source_sha256 ASC, chunks.start_char ASC, "
        "chunks.end_char ASC, chunks.id ASC"
    ) in sql
    assert list(params.values()).count(7) == 1
    assert "hnsw" not in sql.lower()


def test_statement_applies_every_shared_filter_with_and_semantics():
    need(V, "vector_search_statement")
    filters = RetrievalFilters(
        doc_ids=["NVDA-FY2024"],
        tickers=["NVDA"],
        fiscal_years=[2024],
        forms=["10-K"],
        items=[None, "7"],
        kinds=["table"],
    )
    sql, params = normalized_sql(V.vector_search_statement([0.0] * 384, k=5, filters=filters))

    assert "JOIN documents ON documents.doc_id = chunks.doc_id" in sql
    assert "chunks.doc_id IN" in sql
    assert "documents.ticker IN" in sql
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
    need(V, "vector_search_statement")
    sql, _params = normalized_sql(
        V.vector_search_statement(
            [0.0] * 384,
            k=3,
            filters=RetrievalFilters(items=[None]),
        )
    )

    assert "chunks.item IS NULL" in sql
    assert "chunks.item IN" not in sql


@pytest.mark.parametrize(
    "vector",
    [
        [0.0] * 383,
        [0.0] * 383 + [math.nan],
        [0.0] * 383 + [True],
    ],
)
def test_query_vector_requires_exactly_384_finite_numeric_values(vector):
    need(V, "validate_query_vector")
    with pytest.raises(ValueError):
        V.validate_query_vector(vector)


@pytest.mark.parametrize("k", [0, -1])
def test_statement_rejects_nonpositive_limits(k):
    need(V, "vector_search_statement")
    with pytest.raises(ValueError, match="positive"):
        V.vector_search_statement([0.0] * 384, k=k)


def test_search_returns_complete_chunk_hits_and_similarity_scores():
    need(V, "vector_search")
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
        def all(self):
            return [(chunk, 0.25)]

    class Session:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            return Result()

    session = Session()
    hits = asyncio.run(V.vector_search(session, [0.0] * 384, k=4))

    assert len(session.statements) == 1
    assert len(hits) == 1
    assert hits[0].model_dump() == {**values, "score": 0.75}


def test_zero_limit_returns_without_database_access_and_negative_limit_fails():
    need(V, "vector_search")

    class Session:
        async def execute(self, _statement):
            raise AssertionError("zero-limit search must not execute SQL")

    assert asyncio.run(V.vector_search(Session(), [0.0] * 384, k=0)) == []
    with pytest.raises(ValueError, match="negative"):
        asyncio.run(V.vector_search(Session(), [0.0] * 384, k=-1))


def test_model_has_no_approximate_vector_index_before_m3_measurement():
    index_names = {index.name for index in Chunk.__table__.indexes}

    assert "ix_chunks_embedding_hnsw" not in index_names
    assert not any(
        index.dialect_options["postgresql"].get("using") == "hnsw"
        for index in Chunk.__table__.indexes
    )
