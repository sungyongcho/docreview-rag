"""PostgreSQL full-text lexical retrieval.

This is the project's mandatory lexical baseline. It uses PostgreSQL full-text
search with cover-density ranking; ``ts_rank_cd`` is not literal BM25.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Chunk, Document
from app.retrieval.types import ChunkHit, RetrievalFilters

TEXT_SEARCH_CONFIG = "english"

# ``ts_rank_cd`` normalization bitmask (PostgreSQL, "Ranking Search Results").
# Bit 4 divides the rank by the mean harmonic distance between extents, so query
# terms that appear close together outrank the same terms scattered apart; bit 1
# divides by ``1 + log(document length)``, so a long chunk stuffed with one common
# term cannot outrank a short chunk that actually answers. With the default of 0,
# rank degenerates into occurrence counting and, measured on the golden suite,
# recall@5 is exactly zero; 4|1 is the best-scoring native combination.
TS_RANK_NORMALIZATION = 4 | 1


def _filter_predicates(filters: RetrievalFilters) -> tuple[ColumnElement[bool], ...]:
    """Translate the shared exact-match filters to composable SQL predicates."""
    predicates: list[ColumnElement[bool]] = []
    if filters.doc_ids:
        predicates.append(Chunk.doc_id.in_(filters.doc_ids))
    if filters.tickers:
        predicates.append(Document.ticker.in_(filters.tickers))
    if filters.fiscal_years:
        predicates.append(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        predicates.append(Document.form.in_(filters.forms))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates: list[ColumnElement[bool]] = []
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        predicates.append(or_(*item_predicates))
    if filters.kinds:
        predicates.append(Chunk.kind.in_(filters.kinds))
    return tuple(predicates)


def lexical_statement(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
) -> Select[Any]:
    """Build a safe PostgreSQL FTS statement ranked by cover density.

    ``websearch_to_tsquery`` accepts raw user text without exposing ``to_tsquery``
    syntax errors, and SQLAlchemy binds ``query`` as a value instead of interpolating
    it. But its output joins every content lexeme with ``&``: a natural-language
    question like "What was the total revenue reported for fiscal 2024?" becomes
    five AND-ed stems, and only a chunk containing all five matches. On this corpus
    that describes almost no chunk, and the baseline silently returns nothing.

    The statement therefore relaxes the parsed query before using it. The tsquery's
    text form quotes each lexeme and can never contain ``&`` inside one, so
    rewriting ``&`` to ``|`` and reparsing with ``to_tsquery`` turns the conjunction
    into a disjunction while leaving quoted phrases (``<->``) intact. Matching any
    query term is enough to become a candidate, and ``TS_RANK_NORMALIZATION`` makes
    the ranking prefer chunks where more of the query co-occurs closely over chunks
    that merely repeat one common term. One semantic is knowingly weakened: an
    explicit ``-term`` exclusion is relaxed along with everything else.

    PostgreSQL FTS is the lexical baseline here; this statement does not implement BM25.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")

    active_filters = filters or RetrievalFilters()
    parsed = func.websearch_to_tsquery(TEXT_SEARCH_CONFIG, query)
    tsquery = func.to_tsquery(TEXT_SEARCH_CONFIG, func.replace(cast(parsed, Text), "&", "|"))
    score = func.ts_rank_cd(Chunk.content_tsv, tsquery, TS_RANK_NORMALIZATION).label("score")
    return (
        select(
            Chunk.id.label("chunk_id"),
            Chunk.doc_id,
            Chunk.item,
            Chunk.kind,
            Chunk.citation,
            Chunk.start_char,
            Chunk.end_char,
            Chunk.source_sha256,
            Chunk.body,
            Chunk.context_header,
            Chunk.index_text,
            score,
        )
        .join(Document, Document.doc_id == Chunk.doc_id)
        .where(Chunk.content_tsv.op("@@")(tsquery), *_filter_predicates(active_filters))
        .order_by(
            score.desc(),
            Chunk.doc_id.asc(),
            Chunk.source_sha256.asc(),
            Chunk.start_char.asc(),
            Chunk.end_char.asc(),
            Chunk.id.asc(),
        )
        .limit(k)
    )


async def lexical_search(
    session: AsyncSession,
    query: str,
    k: int = 5,
    filters: RetrievalFilters | None = None,
) -> list[ChunkHit]:
    """Run the PostgreSQL FTS baseline and return typed, deterministically ordered hits.

    The returned score is the native ``ts_rank_cd`` cover-density score, not BM25
    and not a probability. Fusion must consume its rank instead of comparing this
    value directly with another retrieval strategy's score.
    """
    result = await session.execute(lexical_statement(query, k, filters))
    return [ChunkHit.model_validate(row) for row in result.mappings().all()]
