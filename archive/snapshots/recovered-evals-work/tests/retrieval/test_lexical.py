"""Safe PostgreSQL full-text lexical retrieval tests."""

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval import lexical
from app.retrieval.types import RetrievalFilters
from tests.retrieval.support import RecordingSession, hit_values, normalized_sql


def test_statement_uses_safe_websearch_cover_density_and_complete_hit_projection():
    """Bind raw queries and project complete deterministically ordered hits."""
    query = 'R&D OR "capital expense"; DROP TABLE chunks'
    statement = lexical.lexical_statement(query, 7)
    sql, params = normalized_sql(statement)

    relaxed_query = lexical._relaxed_websearch_query(query)
    assert sql.startswith("WITH lexical_query AS MATERIALIZED")
    assert sql.count("websearch_to_tsquery(") == 1
    assert "websearch_to_tsquery(" in sql
    assert "ts_rank_cd(chunks.content_tsv, lexical_query.tsquery" in sql
    assert "chunks.content_tsv @@ lexical_query.tsquery" in sql
    assert query not in sql
    assert relaxed_query not in sql
    assert relaxed_query in params.values()
    assert list(params.values()).count(relaxed_query) == 1
    assert "ORDER BY score DESC" in sql
    assert (
        'chunks.doc_id COLLATE "C" ASC, chunks.source_sha256 COLLATE "C" ASC, '
        "chunks.start_char ASC, chunks.end_char ASC, chunks.id ASC"
    ) in sql
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
        "score",
    }
    assert list(params.values()).count(7) == 1
    # zero-only assertion, restored: this learning build joins `documents` lazily —
    # only when a document-level filter needs it — so an unfiltered statement must
    # not carry the join. The canonical branch joins unconditionally and does not
    # assert either way, so this line pins the local optimization without
    # contradicting the shared contract.
    assert "JOIN documents" not in sql


def test_statement_parses_the_relaxed_query_once_and_shares_the_materialized_result():
    """Parse one relaxed query for both matching and cover-density ranking."""
    query = "total revenue reported fiscal 2024"
    sql, params = normalized_sql(lexical.lexical_statement(query, 5))

    assert lexical._relaxed_websearch_query(query) == (
        "total OR revenue OR reported OR fiscal OR 2024"
    )
    assert "WITH lexical_query AS MATERIALIZED" in sql
    assert sql.count("websearch_to_tsquery(") == 1
    assert "replace(" not in sql
    assert "CAST(" not in sql
    assert "chunks.content_tsv @@ lexical_query.tsquery" in sql
    assert "ts_rank_cd(chunks.content_tsv, lexical_query.tsquery" in sql
    assert lexical._relaxed_websearch_query(query) in params.values()


def test_relaxation_distributes_exclusions_and_preserves_phrases_and_explicit_or():
    """Keep phrases atomic and require every OR alternative to satisfy exclusions."""
    query = 'revenue OR "capital expense" reported -risk -"material weakness"'

    assert lexical._relaxed_websearch_query(query) == (
        'revenue -risk -"material weakness" OR '
        '"capital expense" -risk -"material weakness" OR '
        'reported -risk -"material weakness"'
    )


@pytest.mark.parametrize("query", ['"unterminated phrase -risk', "-risk OR -debt", "OR"])
def test_relaxation_leaves_queries_without_safe_positive_splits_to_websearch(query):
    """Retain PostgreSQL web-search tolerance for malformed or negative-only input."""
    sql, params = normalized_sql(lexical.lexical_statement(query, 5))

    assert lexical._relaxed_websearch_query(query) == query
    assert sql.count("websearch_to_tsquery(") == 1
    assert query in params.values()


def test_ranking_normalizes_by_extent_distance_and_document_length():
    """Normalize ranking by term proximity and document length."""
    assert lexical.TS_RANK_NORMALIZATION == 4 | 1

    _sql, params = normalized_sql(lexical.lexical_statement("gross margin percentage", 7))
    assert lexical.TS_RANK_NORMALIZATION in params.values()


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
    sql, params = normalized_sql(lexical.lexical_statement("research expense", 5, filters))

    assert "JOIN documents ON documents.doc_id = chunks.doc_id" in sql
    assert "chunks.doc_id IN" in sql
    assert "documents.issuer IN" in sql
    assert "documents.fiscal_year IN" in sql
    assert "documents.form IN" in sql
    assert "(chunks.item IN" in sql
    assert "OR chunks.item IS NULL" in sql
    assert "chunks.kind IN" in sql
    assert ["NVDA-FY2024"] in params.values()
    assert ["NVDA"] in params.values()
    assert [2024] in params.values()
    assert ["10-K"] in params.values()
    assert ["7"] in params.values()
    assert ["table"] in params.values()


def test_statement_handles_an_unnumbered_item_filter_without_an_empty_in_clause():
    """Filter unnumbered sections without emitting an empty IN clause."""
    sql, _params = normalized_sql(
        lexical.lexical_statement("governance", 3, RetrievalFilters(items=(None,)))
    )
    assert "chunks.item IS NULL" in sql
    assert "chunks.item IN" not in sql


@pytest.mark.parametrize(("query", "k"), [("", 1), ("   ", 1), ("valid", 0), ("valid", -1)])
def test_statement_rejects_blank_queries_and_nonpositive_limits(query, k):
    """Reject blank queries and nonpositive result limits."""
    with pytest.raises(ValueError):
        lexical.lexical_statement(query, k)


def test_search_executes_once_and_validates_database_mappings():
    """Execute one statement and validate mappings as typed hits."""
    mapping = hit_values(score=0.625)

    class Result:
        def mappings(self):
            return SimpleNamespace(all=lambda: [mapping])

    session = RecordingSession(Result())
    hits = asyncio.run(lexical.lexical_search(cast(AsyncSession, session), "research expense", 4))

    assert len(session.statements) == 1
    assert len(hits) == 1
    assert hits[0].chunk_id == mapping["chunk_id"]
    assert hits[0].score == 0.625


def test_module_docstring_names_the_baseline_without_calling_it_bm25():
    """Describe the lexical baseline accurately as PostgreSQL full-text search."""
    doc = lexical.__doc__ or ""
    assert "PostgreSQL full-text" in doc
    assert "not literal BM25" in doc
