"""Deterministic PostgreSQL BM25 retrieval over stored full-text lexemes."""

from __future__ import annotations

from typing import Any, get_args

from sqlalchemy import (
    Float,
    Integer,
    Select,
    SQLColumnExpression,
    String,
    bindparam,
    cast,
    func,
    select,
    true,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1, BM25Idf
from app.db.models import (
    BM25CorpusStat,
    Chunk,
    ChunkLength,
    ChunkTerm,
    LexemeStat,
    SnapshotBM25CorpusStat,
    SnapshotChunk,
    SnapshotChunkLength,
    SnapshotChunkTerm,
    SnapshotLexemeStat,
)
from app.retrieval.search.sql import (
    TEXT_SEARCH_CONFIG,
    apply_filters,
    hit_columns,
    hit_order_by,
    positive_websearch_text,
    provenance_tie_breakers,
    relaxed_websearch_query,
)
from app.retrieval.types import ChunkHit, RetrievalFilters, finite_float

BM25_IDF_VARIANTS: tuple[BM25Idf, ...] = get_args(BM25Idf)
# Column that carries the corpus-statistics count beside the ranked hits.
READINESS_COLUMN = "corpus_stats"


def _idf_expression(
    variant: BM25Idf,
    corpus_size: SQLColumnExpression[Any],
    document_frequency: SQLColumnExpression[Any],
) -> ColumnElement[Any]:
    """Return the selected SQL inverse-document-frequency expression.

    Parameters
    ----------
    variant : BM25Idf
        Lucene's nonnegative variant or Robertson's signed variant.
    corpus_size : SQLColumnExpression[Any]
        Total number of chunks in the rebuilt corpus snapshot.
    document_frequency : SQLColumnExpression[Any]
        Chunks containing the current lexeme.

    Returns
    -------
    ColumnElement[Any]
        SQL logarithm expression for the selected variant.

    Notes
    -----
    Robertson can score corpus-wide terms negatively; Lucene remains nonnegative.
    ``bm25_statement`` has already rejected unknown variants through
    ``validate_bm25_parameters`` before it builds this expression.
    """
    size = cast(corpus_size, Float)
    df = cast(document_frequency, Float)
    ratio = (size - df + 0.5) / (df + 0.5)
    if variant == "lucene":
        return func.ln(1.0 + ratio)
    return func.ln(ratio)


def validate_bm25_parameters(
    k1: float, b: float, idf: BM25Idf, *, parameter_prefix: str = ""
) -> tuple[float, float]:
    """Check BM25 tuning values and return ``k1`` and ``b`` as built-in floats.

    The SQL builder, the retrieval service and experiment arms all validate through
    this one function, so they accept exactly the same values. Only the parameter
    names in the messages differ: a caller whose arguments are named ``bm25_k1``,
    ``bm25_b`` and ``bm25_idf`` passes ``parameter_prefix="bm25_"`` so the error names
    the argument that caller actually received.

    Parameters
    ----------
    k1 : float
        Term-frequency saturation; must be finite and positive.
    b : float
        Length normalization; must be finite and within ``[0, 1]``.
    idf : BM25Idf
        Inverse-document-frequency variant; must be ``"lucene"`` or ``"robertson"``.
    parameter_prefix : str, optional
        Prefix added to each parameter name in error messages.

    Returns
    -------
    tuple[float, float]
        The validated ``(k1, b)`` pair.

    Raises
    ------
    ValueError
        If a value is a ``bool``, not a real number, not finite, out of range, or an
        unknown idf variant. ``k1`` is checked first, then ``b``, then ``idf``.
    """
    k1_message = f"{parameter_prefix}k1 must be a finite positive number"
    normalized_k1 = finite_float(k1, nonnumeric=k1_message, nonfinite=k1_message)
    if normalized_k1 <= 0:
        raise ValueError(k1_message)
    b_message = f"{parameter_prefix}b must be a finite number between 0 and 1"
    normalized_b = finite_float(b, nonnumeric=b_message, nonfinite=b_message)
    if not 0 <= normalized_b <= 1:
        raise ValueError(b_message)
    if idf not in BM25_IDF_VARIANTS:
        raise ValueError(f"{parameter_prefix}idf must be 'lucene' or 'robertson'")
    return normalized_k1, normalized_b


def bm25_statement(
    query: str,
    k: int,
    filters: RetrievalFilters | None = None,
    *,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
    idf: BM25Idf = DEFAULT_BM25_IDF,
    text_search_config: str = TEXT_SEARCH_CONFIG,
) -> Select[Any]:
    """Build a bound BM25 query with shared filters and deterministic ordering.

    Parameters
    ----------
    query : str
        Raw user query used for matching and positive score terms.
    k : int
        Maximum number of ranked chunks to return.
    filters : RetrievalFilters | None
        Optional shared evidence restrictions.
    k1 : float
        Positive term-frequency saturation value.
    b : float
        Length normalization in the inclusive range ``[0, 1]``.
    idf : BM25Idf
        Inverse-document-frequency variant.

    Returns
    -------
    Select[Any]
        Projected, filtered, and deterministically ordered SQL statement.

    Raises
    ------
    ValueError
        If query, limit, numeric parameters, or idf variant is invalid.

    Notes
    -----
    Scores use the atomically rebuilt per-language corpus-size and average-length rows:
    every chunk is scored against the statistics of its own corpus language.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    normalized_k1, normalized_b = validate_bm25_parameters(k1, b, idf)
    active_filters = filters or RetrievalFilters()

    parsed = func.websearch_to_tsquery(
        text_search_config,
        bindparam(
            "bm25_match_query",
            value=relaxed_websearch_query(query),
            type_=String(),
        ),
    ).label("tsquery")
    query_cte = select(parsed).cte("bm25_query").prefix_with("MATERIALIZED")
    tsquery = query_cte.c.tsquery
    query_terms = select(
        func.unnest(
            func.tsvector_to_array(
                func.to_tsvector(
                    text_search_config,
                    bindparam(
                        "bm25_positive_query",
                        value=positive_websearch_text(query),
                        type_=String(),
                    ),
                )
            )
        ).label("lexeme")
    ).subquery("bm25_query_terms")
    if active_filters.snapshot_id is None:
        source = Chunk
        term_table = ChunkTerm
        length_table = ChunkLength
        length_join = ChunkLength.chunk_id == ChunkTerm.chunk_id
        corpus = select(
            BM25CorpusStat.language,
            BM25CorpusStat.n,
            BM25CorpusStat.avgdl,
        ).subquery("bm25_corpus")
        lexeme_df = LexemeStat.df
        lexeme_join = (LexemeStat.lexeme == term_table.lexeme) & (
            LexemeStat.language == source.language
        )
        lexeme_table = LexemeStat
        scope_predicates = ()
    else:
        source = SnapshotChunk
        term_table = SnapshotChunkTerm
        length_table = SnapshotChunkLength
        length_join = (SnapshotChunkLength.chunk_id == SnapshotChunkTerm.chunk_id) & (
            SnapshotChunkLength.snapshot_id == SnapshotChunkTerm.snapshot_id
        )
        corpus = (
            select(
                SnapshotBM25CorpusStat.language,
                SnapshotBM25CorpusStat.n,
                SnapshotBM25CorpusStat.avgdl,
            )
            .where(SnapshotBM25CorpusStat.snapshot_id == active_filters.snapshot_id)
            .subquery("bm25_corpus")
        )
        lexeme_df = SnapshotLexemeStat.df
        lexeme_join = (
            (SnapshotLexemeStat.snapshot_id == active_filters.snapshot_id)
            & (SnapshotLexemeStat.lexeme == term_table.lexeme)
            & (SnapshotLexemeStat.language == source.language)
        )
        lexeme_table = SnapshotLexemeStat
        scope_predicates = (
            source.snapshot_id == active_filters.snapshot_id,
            term_table.snapshot_id == active_filters.snapshot_id,
            length_table.snapshot_id == active_filters.snapshot_id,
        )

    k1_param = bindparam("bm25_k1", value=normalized_k1, type_=Float())
    b_param = bindparam("bm25_b", value=normalized_b, type_=Float())
    document_length = cast(length_table.dl, Float)
    idf_term = _idf_expression(idf, corpus.c.n, lexeme_df)
    length_norm = 1.0 - b_param + b_param * document_length / corpus.c.avgdl
    saturation = (term_table.tf * (k1_param + 1.0)) / (term_table.tf + k1_param * length_norm)
    score = cast(func.sum(idf_term * saturation), Float).label("score")

    scores = (
        select(term_table.chunk_id.label("chunk_id"), score)
        .select_from(term_table)
        .join(
            source,
            (Chunk.id if source is Chunk else SnapshotChunk.chunk_id) == term_table.chunk_id,
        )
        .join(query_cte, true())
        .join(query_terms, query_terms.c.lexeme == term_table.lexeme)
        # Statistics join on the chunk's own language, so every chunk is scored
        # within its corpus even when the table hosts more than one.
        .join(
            lexeme_table,
            lexeme_join,
        )
        .join(
            length_table,
            length_join,
        )
        .join(corpus, corpus.c.language == source.language)
        .where(source.content_tsv.op("@@")(tsquery), *scope_predicates)
        .group_by(term_table.chunk_id)
        .subquery("bm25_scores")
    )

    statement = (
        select(*hit_columns(scores.c.score, source))
        .select_from(source)
        .join(
            scores, scores.c.chunk_id == (Chunk.id if source is Chunk else SnapshotChunk.chunk_id)
        )
    )
    statement = apply_filters(statement, active_filters, source)
    return statement.order_by(*hit_order_by(scores.c.score.desc(), source)).limit(
        bindparam("bm25_k", value=k, type_=Integer())
    )


async def bm25_search(
    session: AsyncSession,
    query: str,
    k: int = 5,
    filters: RetrievalFilters | None = None,
    *,
    k1: float = DEFAULT_BM25_K1,
    b: float = DEFAULT_BM25_B,
    idf: BM25Idf = DEFAULT_BM25_IDF,
    text_search_config: str = TEXT_SEARCH_CONFIG,
) -> list[ChunkHit]:
    """Rank chunks with BM25 and return complete typed evidence.

    Parameters
    ----------
    session : AsyncSession
        Session used for the search and statistic-readiness check.
    query : str
        Raw user query.
    k : int
        Maximum number of ranked chunks to return.
    filters : RetrievalFilters | None
        Optional shared evidence restrictions.
    k1 : float
        Positive term-frequency saturation value.
    b : float
        Length normalization in the inclusive range ``[0, 1]``.
    idf : BM25Idf
        Inverse-document-frequency variant.

    Returns
    -------
    list[ChunkHit]
        Complete evidence records carrying native BM25 scores.

    Raises
    ------
    RuntimeError
        If corpus statistics are missing or were invalidated by chunk writes.
    ValueError
        If public BM25 parameters are invalid.

    Notes
    -----
    The statistics count is read in the same statement as the search, so both see one
    snapshot: a rebuild that commits while the search runs can neither turn a search
    made without statistics into an empty success nor fail a search that had them.
    """
    active_filters = filters or RetrievalFilters()
    statement = _with_readiness(
        bm25_statement(
            query, k, filters, k1=k1, b=b, idf=idf, text_search_config=text_search_config
        ),
        active_filters,
    )
    rows = (await session.execute(statement)).mappings().all()
    if not rows or not rows[0][READINESS_COLUMN]:
        raise RuntimeError("BM25 statistics are missing or stale; rebuild them before searching")
    return [
        ChunkHit.model_validate(
            {name: value for name, value in row.items() if name != READINESS_COLUMN}
        )
        for row in rows
        if row["chunk_id"] is not None
    ]


def _with_readiness(hits_statement: Select[Any], filters: RetrievalFilters) -> Select[Any]:
    """Attach the corpus-statistics count to the ranked hits in one statement.

    The count is the outer side of a left join, so the statement returns one
    NULL-extended row carrying the count even when the search finds nothing. The hit
    order is applied again on the subquery columns with the tie-breakers
    ``hit_order_by`` uses, because a subquery's order does not survive the join.
    """
    hits = hits_statement.subquery("bm25_hits")
    if filters.snapshot_id is None:
        readiness = select(func.count().label(READINESS_COLUMN)).select_from(BM25CorpusStat)
    else:
        readiness = (
            select(func.count().label(READINESS_COLUMN))
            .select_from(SnapshotBM25CorpusStat)
            .where(SnapshotBM25CorpusStat.snapshot_id == filters.snapshot_id)
        )
    counted = readiness.subquery("bm25_readiness")
    return (
        select(counted.c[READINESS_COLUMN], *hits.c)
        .select_from(counted.outerjoin(hits, true()))
        .order_by(hits.c.score.desc(), *provenance_tie_breakers(hits.c, hits.c.chunk_id))
    )
