"""PostgreSQL full-text lexical retrieval.

This is the project's mandatory lexical baseline. It uses PostgreSQL full-text
search with cover-density ranking; ``ts_rank_cd`` is not literal BM25.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk
from app.retrieval._sql import (
    TEXT_SEARCH_CONFIG,
    apply_filters,
    hit_columns,
    hit_order_by,
    relaxed_websearch_query as _relaxed_websearch_query,
)
from app.retrieval.types import ChunkHit, RetrievalFilters

TS_RANK_NORMALIZATION = 4 | 1


def lexical_statement(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
    *,
    text_search_config: str = TEXT_SEARCH_CONFIG,
) -> Select[Any]:
    """Build a safe PostgreSQL FTS statement ranked by cover density.

    Parameters
    ----------
    query : str
        Raw user text parsed by ``websearch_to_tsquery``.
    k : int
        Maximum number of ranked chunks to return.
    filters : RetrievalFilters | None
        Optional exact-match restrictions.
    text_search_config : str
        Configuration the query is parsed with. It must match the configuration the
        target rows were indexed with — English rows use the default, Korean rows
        are indexed under ``simple`` over pre-tokenized text.

    Returns
    -------
    Select[Any]
        Projected, filtered, and deterministically ordered FTS statement.

    Raises
    ------
    ValueError
        If ``query`` is blank or ``k`` is not positive.

    Notes
    -----
    A materialized CTE parses the relaxed query once for both matching and ranking.
    The native score is ``ts_rank_cd``, not BM25 or a probability.
    """
    if not query.strip():
        raise ValueError("query must not be blank")
    if k <= 0:
        raise ValueError("k must be positive")

    active_filters = filters or RetrievalFilters()
    parsed = func.websearch_to_tsquery(text_search_config, _relaxed_websearch_query(query)).label(
        "tsquery"
    )
    query_cte = select(parsed).cte("lexical_query").prefix_with("MATERIALIZED")
    tsquery = query_cte.c.tsquery
    score = func.ts_rank_cd(Chunk.content_tsv, tsquery, TS_RANK_NORMALIZATION).label("score")
    statement = (
        select(*hit_columns(score))
        .select_from(Chunk)
        .join(query_cte, true())
        .where(Chunk.content_tsv.op("@@")(tsquery))
    )
    statement = apply_filters(statement, active_filters)
    return statement.order_by(*hit_order_by(score.desc())).limit(k)


async def lexical_search(
    session: AsyncSession,
    query: str,
    k: int = 5,
    filters: RetrievalFilters | None = None,
    *,
    text_search_config: str = TEXT_SEARCH_CONFIG,
) -> list[ChunkHit]:
    """Run the PostgreSQL FTS baseline and return typed hits.

    Parameters
    ----------
    session : AsyncSession
        Session used for the single lexical-search statement.
    query : str
        Raw user query.
    k : int
        Maximum number of ranked chunks to return.
    filters : RetrievalFilters | None
        Optional exact-match restrictions.

    Returns
    -------
    list[ChunkHit]
        Complete evidence records carrying native cover-density scores.

    Raises
    ------
    ValueError
        If ``query`` is blank or ``k`` is not positive.

    Notes
    -----
    Fusion must consume rank rather than compare this native score with another scale.
    """
    result = await session.execute(
        lexical_statement(query, k, filters, text_search_config=text_search_config)
    )
    return [ChunkHit.model_validate(row) for row in result.mappings().all()]
