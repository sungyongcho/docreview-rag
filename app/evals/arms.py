"""Bind one validated experiment arm to a session as a callable retriever."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
import math
from typing import Literal, get_args

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BM25Idf, LexicalRanker
from app.retrieval.bm25 import bm25_search
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.hybrid import DEFAULT_RRF_K
from app.retrieval.korean import lexical_corpus_language, lexical_plan
from app.retrieval.lexical import lexical_search
from app.retrieval.service import normalize_query, retrieve
from app.retrieval.types import ChunkHit, RetrievalFilters
from app.retrieval.vector import vector_search

type RetrievalStrategy = Literal["lexical", "vector", "hybrid"]
type Retriever = Callable[[str, int], Awaitable[Sequence[ChunkHit]]]
type BM25Parameters = tuple[float, float, BM25Idf]

RETRIEVAL_STRATEGIES: tuple[RetrievalStrategy, ...] = ("lexical", "vector", "hybrid")
LEXICAL_RANKERS: tuple[LexicalRanker, ...] = get_args(LexicalRanker)
BM25_IDF_VARIANTS: tuple[BM25Idf, ...] = get_args(BM25Idf)


def _is_finite_number(value: object) -> bool:
    """Accept only a real finite number, rejecting ``bool`` and non-numeric values."""
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def resolve_bm25_parameters(
    lexical_ranker: LexicalRanker | None,
    bm25_k1: float | None,
    bm25_b: float | None,
    bm25_idf: BM25Idf | None,
) -> BM25Parameters | None:
    """Validate BM25 values against an arm's ranker and return the resolved set.

    Both the experiment matrix and the retriever binder narrow BM25 provenance
    through this function, so an artifact can never label a run with parameters
    that run did not use.

    Parameters
    ----------
    lexical_ranker : LexicalRanker | None
        Ranker declared by the arm, or ``None`` for an arm with no lexical query.
    bm25_k1, bm25_b, bm25_idf : float | float | BM25Idf | None
        Candidate parameter set, complete for a BM25 arm and absent otherwise.

    Returns
    -------
    BM25Parameters | None
        ``(k1, b, idf)`` for a BM25 arm, or ``None`` when the arm runs no BM25
        query and therefore carries no parameters.

    Raises
    ------
    ValueError
        If a BM25 arm is missing a value or supplies one that is non-finite, a
        ``bool``, out of range, or an unknown idf variant, or if a non-BM25 arm
        supplies any BM25 value at all.
    """
    if lexical_ranker != "bm25":
        if bm25_k1 is not None or bm25_b is not None or bm25_idf is not None:
            raise ValueError("BM25 parameters are valid only for bm25 arms")
        return None
    if bm25_k1 is None or bm25_b is None or bm25_idf is None:
        raise ValueError("bm25 arms require explicit k1, b, and idf values")
    if not _is_finite_number(bm25_k1) or bm25_k1 <= 0:
        raise ValueError("bm25_k1 must be a finite positive number")
    if not _is_finite_number(bm25_b) or not 0 <= bm25_b <= 1:
        raise ValueError("bm25_b must be a finite number between 0 and 1")
    if bm25_idf not in BM25_IDF_VARIANTS:
        raise ValueError("bm25_idf must be 'lucene' or 'robertson'")
    return (float(bm25_k1), float(bm25_b), bm25_idf)


def _require_depth(candidate_k: int, k: int) -> None:
    """Reject a per-call hit count deeper than the bound candidate depth."""
    if candidate_k < k:
        raise ValueError("candidate_k must be at least k")


def _lexical_retriever(
    session: AsyncSession,
    bm25: BM25Parameters | None,
    *,
    candidate_k: int,
    filters: RetrievalFilters | None,
) -> Retriever:
    """Bind the lexical-only lane, using BM25 when the arm resolved parameters.

    The corpus language named by ``filters`` selects the lexical plan, so this
    lane tokenizes and parses queries exactly the way the target rows were
    indexed — the same contract the hybrid lane applies inside the service.
    """
    plan = lexical_plan(lexical_corpus_language(filters))

    async def run(query: str, k: int) -> Sequence[ChunkHit]:
        """Search the lexical index for one normalized query."""
        _require_depth(candidate_k, k)
        lexical_query = plan.query_transform(normalize_query(query))
        if not lexical_query.strip():
            return []
        if bm25 is None:
            return await lexical_search(
                session,
                lexical_query,
                k,
                filters,
                text_search_config=plan.text_search_config,
            )
        k1, b, idf = bm25
        return await bm25_search(
            session,
            lexical_query,
            k,
            filters,
            k1=k1,
            b=b,
            idf=idf,
            text_search_config=plan.text_search_config,
        )

    return run


def _vector_retriever(
    session: AsyncSession,
    provider: EmbeddingProvider,
    *,
    candidate_k: int,
    filters: RetrievalFilters | None,
) -> Retriever:
    """Bind the vector-only lane, embedding each normalized query before search."""

    async def run(query: str, k: int) -> Sequence[ChunkHit]:
        """Embed one normalized query and search by vector distance."""
        _require_depth(candidate_k, k)
        query_vector = await provider.embed_query(normalize_query(query))
        return await vector_search(
            session, query_vector, k=k, filters=filters, identity=provider.identity
        )

    return run


def _hybrid_retriever(
    session: AsyncSession,
    provider: EmbeddingProvider,
    lexical_ranker: LexicalRanker,
    bm25: BM25Parameters | None,
    *,
    candidate_k: int,
    rrf_k: int,
    route_by_language: bool,
    filters: RetrievalFilters | None,
) -> Retriever:
    """Bind the fused lane; BM25 values are forwarded only for a BM25 arm."""

    async def run(query: str, k: int) -> Sequence[ChunkHit]:
        """Fuse the vector and lexical lanes for one normalized query."""
        _require_depth(candidate_k, k)
        bm25_arguments = (
            {} if bm25 is None else {"bm25_k1": bm25[0], "bm25_b": bm25[1], "bm25_idf": bm25[2]}
        )
        result = await retrieve(
            session,
            normalize_query(query),
            provider=provider,
            k=k,
            candidate_k=candidate_k,
            filters=filters,
            rrf_k=rrf_k,
            route_by_language=route_by_language,
            lexical_ranker=lexical_ranker,
            **bm25_arguments,
        )
        return result.hits

    return run


def make_retriever(
    session: AsyncSession,
    *,
    strategy: RetrievalStrategy,
    provider: EmbeddingProvider | None,
    lexical_ranker: LexicalRanker | None = None,
    bm25_k1: float | None = None,
    bm25_b: float | None = None,
    bm25_idf: BM25Idf | None = None,
    candidate_k: int = 20,
    rrf_k: int = DEFAULT_RRF_K,
    route_by_language: bool = False,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Bind one explicit retrieval strategy and ranker configuration to a session.

    Parameters
    ----------
    session : AsyncSession
        SQLAlchemy session used by every invocation of the returned callable.
    strategy : RetrievalStrategy
        Retrieval lane to execute: lexical, vector, or hybrid.
    provider : EmbeddingProvider | None
        Query embedding provider required by vector-bearing strategies.
    lexical_ranker : LexicalRanker | None, optional
        Explicit lexical algorithm required by lexical-bearing strategies and forbidden
        for a vector-only strategy.
    bm25_k1, bm25_b, bm25_idf : float | float | BM25Idf | None, optional
        Complete BM25 parameter set required for a BM25 arm and forbidden otherwise;
        see :func:`resolve_bm25_parameters`.
    candidate_k : int, optional
        Positive hybrid candidate depth, which must also cover each requested ``k``.
    rrf_k : int, optional
        Positive reciprocal-rank-fusion constant used by hybrid retrieval.
    route_by_language : bool, optional
        Skip the English lexical component for a Korean query. Only a fused arm can
        route, because routing decides between two components; naming it on a
        single-lane arm would label a query path that arm never takes.
    filters : RetrievalFilters | None, optional
        Canonical evidence restrictions passed to every active retrieval component.

    Returns
    -------
    Retriever
        Awaitable callable bound to the supplied session and explicit experiment arm.

    Raises
    ------
    ValueError
        If the strategy, provider, ranker, BM25 values, routing selection, or retrieval
        limits form an invalid or mislabeled experiment arm.

    Notes
    -----
    Every lane receives the same public query normalization, and each rejects a
    per-call ``k`` greater than ``candidate_k`` before touching the provider or the
    database. Arm validity is decided here, once, so the per-query path carries no
    optional provenance. The bound session's concurrency constraints remain the
    caller's responsibility.
    """
    if strategy not in RETRIEVAL_STRATEGIES:
        raise ValueError(f"unsupported retrieval strategy: {strategy}")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if route_by_language and strategy != "hybrid":
        raise ValueError("language routing requires the hybrid strategy")

    if strategy == "vector":
        if lexical_ranker is not None:
            raise ValueError("vector retrieval must not name a lexical ranker")
        resolve_bm25_parameters(None, bm25_k1, bm25_b, bm25_idf)
        if provider is None:
            raise ValueError("vector retrieval requires an embedding provider")
        return _vector_retriever(session, provider, candidate_k=candidate_k, filters=filters)

    if lexical_ranker not in LEXICAL_RANKERS:
        raise ValueError(f"{strategy} retrieval requires an explicit lexical ranker")
    bm25 = resolve_bm25_parameters(lexical_ranker, bm25_k1, bm25_b, bm25_idf)
    if strategy == "lexical":
        return _lexical_retriever(session, bm25, candidate_k=candidate_k, filters=filters)
    if provider is None:
        raise ValueError("hybrid retrieval requires an embedding provider")
    return _hybrid_retriever(
        session,
        provider,
        lexical_ranker,
        bm25,
        candidate_k=candidate_k,
        rrf_k=rrf_k,
        route_by_language=route_by_language,
        filters=filters,
    )
