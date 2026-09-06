"""L4: safe PostgreSQL full-text lexical retrieval."""

import asyncio
import importlib
import os
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.retrieval.types import RetrievalFilters
from tests.retrieval.test_01_contract import hit_values
from tests.support import need

LEXICAL_MODULE_NAME = os.getenv("RETRIEVAL_LEXICAL_MODULE", "app.retrieval.lexical")
L = importlib.import_module(LEXICAL_MODULE_NAME)


def normalized_sql(statement) -> tuple[str, dict[str, object]]:
    """Compile a statement with PostgreSQL placeholders and normalized whitespace."""
    compiled = statement.compile(dialect=postgresql.dialect())
    return " ".join(str(compiled).split()), compiled.params


def test_statement_uses_safe_websearch_cover_density_and_complete_hit_projection():
    need(L, "lexical_statement")
    query = 'R&D OR "capital expense"; DROP TABLE chunks'
    statement = L.lexical_statement(query, 7)
    sql, params = normalized_sql(statement)

    assert "websearch_to_tsquery(" in sql
    assert "ts_rank_cd(chunks.content_tsv," in sql
    assert "chunks.content_tsv @@ to_tsquery(" in sql
    assert query not in sql
    assert query in params.values()
    assert list(params.values()).count(query) == 1
    assert "ORDER BY score DESC" in sql
    assert (
        "chunks.doc_id ASC, chunks.source_sha256 ASC, chunks.start_char ASC, "
        "chunks.end_char ASC, chunks.id ASC"
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


def test_statement_relaxes_the_parsed_conjunction_to_a_disjunction():
    """Matching any query term must be enough to become a candidate.

    ``websearch_to_tsquery`` alone joins every content lexeme with ``&``, so a
    five-word question matches only a chunk containing all five stems, and on the
    real corpus that is recall zero across the whole golden suite. The statement
    must rewrite the parsed tsquery's text form from ``&`` to ``|`` and reparse it,
    which relaxes the conjunction while leaving quoted phrases intact.
    """
    need(L, "lexical_statement")
    sql, params = normalized_sql(L.lexical_statement("total revenue reported fiscal 2024", 5))

    assert "to_tsquery(" in sql
    assert "replace(CAST(websearch_to_tsquery(" in sql
    assert "AS TEXT)" in sql
    assert "&" in params.values()
    assert "|" in params.values()
    # The match predicate and the ranking must consume the same relaxed query.
    assert sql.count("websearch_to_tsquery(") == 2
    assert "chunks.content_tsv @@ to_tsquery(" in sql
    assert "ts_rank_cd(chunks.content_tsv, to_tsquery(" in sql


def test_ranking_normalizes_by_extent_distance_and_document_length():
    """Rank must not degenerate into occurrence counting.

    With the default normalization of 0, a long chunk repeating one common query
    term outranks a short chunk where most of the query co-occurs, and measured
    recall@5 on the golden suite is exactly zero. Bit 4 divides by the mean
    harmonic distance between extents and bit 1 by ``1 + log(length)``.
    """
    need(L, "lexical_statement", "TS_RANK_NORMALIZATION")
    assert L.TS_RANK_NORMALIZATION == 4 | 1

    _sql, params = normalized_sql(L.lexical_statement("gross margin percentage", 7))
    assert L.TS_RANK_NORMALIZATION in params.values()


def test_statement_applies_every_shared_filter_with_and_semantics():
    need(L, "lexical_statement")
    filters = RetrievalFilters(
        doc_ids=("NVDA-FY2024",),
        tickers=("NVDA",),
        fiscal_years=(2024,),
        forms=("10-K",),
        items=(None, "7"),
        kinds=("table",),
    )
    sql, params = normalized_sql(L.lexical_statement("research expense", 5, filters))

    assert "JOIN documents ON documents.doc_id = chunks.doc_id" in sql
    assert "chunks.doc_id IN" in sql
    assert "documents.ticker IN" in sql
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
    need(L, "lexical_statement")
    sql, _params = normalized_sql(
        L.lexical_statement("governance", 3, RetrievalFilters(items=(None,)))
    )
    assert "chunks.item IS NULL" in sql
    assert "chunks.item IN" not in sql


@pytest.mark.parametrize(("query", "k"), [("", 1), ("   ", 1), ("valid", 0), ("valid", -1)])
def test_statement_rejects_blank_queries_and_nonpositive_limits(query, k):
    need(L, "lexical_statement")
    with pytest.raises(ValueError):
        L.lexical_statement(query, k)


def test_search_executes_once_and_validates_database_mappings():
    need(L, "lexical_search")
    mapping = hit_values(score=0.625)

    class Result:
        def mappings(self):
            return SimpleNamespace(all=lambda: [mapping])

    class Session:
        def __init__(self):
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            return Result()

    session = Session()
    hits = asyncio.run(L.lexical_search(session, "research expense", 4))

    assert len(session.statements) == 1
    assert len(hits) == 1
    assert hits[0].chunk_id == mapping["chunk_id"]
    assert hits[0].score == 0.625


def test_module_docstring_names_the_baseline_without_calling_it_bm25():
    doc = L.__doc__ or ""
    assert "PostgreSQL full-text" in doc
    assert "not literal BM25" in doc
