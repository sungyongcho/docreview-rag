"""Safe PostgreSQL full-text lexical retrieval tests."""

import asyncio
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.search import lexical
from tests.retrieval.support import RecordingSession, hit_values, normalized_sql


def test_statement_binds_untrusted_query_text():
    """Keep user query text in bound parameters rather than executable SQL."""
    query = 'R&D OR "capital expense"; DROP TABLE chunks'
    statement = lexical.lexical_statement(query, 7)
    sql, params = normalized_sql(statement)
    relaxed_query = lexical._relaxed_websearch_query(query)

    assert query not in sql
    assert relaxed_query not in sql
    assert relaxed_query in params.values()
    assert 7 in params.values()


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
    _sql, params = normalized_sql(lexical.lexical_statement(query, 5))

    assert lexical._relaxed_websearch_query(query) == query
    assert query in params.values()


@pytest.mark.parametrize(("query", "k"), [("   ", 1), ("valid", 0)])
def test_statement_rejects_blank_queries_and_nonpositive_limits(query, k):
    """Reject blank queries and nonpositive result limits."""
    with pytest.raises(ValueError):
        lexical.lexical_statement(query, k)


def test_search_executes_once_and_validates_database_mappings():
    """Execute one statement and validate mappings as typed hits."""
    mapping = hit_values(score=0.625)

    class Result:
        """Expose one deterministic lexical mapping result."""

        def mappings(self):
            """Return the recorded hit mapping."""
            return SimpleNamespace(all=lambda: [mapping])

    session = RecordingSession(Result())
    hits = asyncio.run(lexical.lexical_search(cast(AsyncSession, session), "research expense", 4))

    assert len(session.statements) == 1
    assert [hit.model_dump() for hit in hits] == [mapping]
