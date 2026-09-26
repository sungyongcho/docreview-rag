"""Bind one validated experiment arm to a session as a callable retriever."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import get_args

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BM25Idf, LexicalRanker
from app.evals.execution.models import EvaluationRetrieval
from app.query.language import lexical_corpus_language, lexical_plan
from app.retrieval.embedding.provider import EmbeddingProvider
from app.retrieval.ranking.fusion import DEFAULT_RRF_K
from app.retrieval.search.bm25 import bm25_search, validate_bm25_parameters
from app.retrieval.search.lexical import lexical_search
from app.retrieval.search.plan import RetrievalStrategy, SearchPlan
from app.retrieval.search.service import normalize_query, retrieve
from app.retrieval.search.vector import vector_search
from app.retrieval.types import RetrievalFilters

type Retriever = Callable[[str, int], Awaitable[EvaluationRetrieval]]
type BM25Parameters = tuple[float, float, BM25Idf]

RETRIEVAL_STRATEGIES: tuple[RetrievalStrategy, ...] = ("lexical", "vector", "hybrid")
LEXICAL_RANKERS: tuple[LexicalRanker, ...] = get_args(LexicalRanker)


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
    k1, b = validate_bm25_parameters(bm25_k1, bm25_b, bm25_idf, parameter_prefix="bm25_")
    return (k1, b, bm25_idf)


def experiment_search_plan(
    *,
    strategy: RetrievalStrategy,
    lexical_ranker: LexicalRanker | None,
    bm25_k1: float | None = None,
    bm25_b: float | None = None,
    bm25_idf: BM25Idf | None = None,
    candidate_k: int = 20,
    rrf_k: int = DEFAULT_RRF_K,
    route_by_language: bool = False,
) -> SearchPlan:
    """Validate measured-arm provenance and use the runtime's canonical search settings."""
    if strategy not in RETRIEVAL_STRATEGIES:
        raise ValueError(f"unsupported retrieval strategy: {strategy}")
    if strategy == "vector":
        if lexical_ranker is not None:
            raise ValueError("vector retrieval must not name a lexical ranker")
    elif lexical_ranker not in LEXICAL_RANKERS:
        raise ValueError(f"{strategy} retrieval requires an explicit lexical ranker")
    if route_by_language and strategy != "hybrid":
        raise ValueError("language routing requires the hybrid strategy")
    bm25 = resolve_bm25_parameters(lexical_ranker, bm25_k1, bm25_b, bm25_idf)
    return SearchPlan(
        strategy=strategy,
        lexical_ranker=lexical_ranker,
        candidate_k=candidate_k,
        rrf_k=rrf_k,
        route_by_language=route_by_language,
        **({} if bm25 is None else {"bm25_k1": bm25[0], "bm25_b": bm25[1], "bm25_idf": bm25[2]}),
    )


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
    """Bind one validated arm, preserving each lane's native score semantics.

    Lexical-only arms retain raw lexical scores; hybrid arms use the runtime's fused
    search. Every lane normalizes its query and checks depth before I/O.
    """
    plan = experiment_search_plan(
        strategy=strategy,
        lexical_ranker=lexical_ranker,
        bm25_k1=bm25_k1,
        bm25_b=bm25_b,
        bm25_idf=bm25_idf,
        candidate_k=candidate_k,
        rrf_k=rrf_k,
        route_by_language=route_by_language,
    )
    if strategy != "lexical" and provider is None:
        raise ValueError(f"{strategy} retrieval requires an embedding provider")
    lexical = lexical_plan(lexical_corpus_language(filters)) if strategy == "lexical" else None

    async def run(query: str, k: int) -> EvaluationRetrieval:
        """Execute the bound lane over one normalized query."""
        plan.candidate_limit(k)
        query = normalize_query(query)
        if strategy == "lexical":
            assert lexical is not None
            query = lexical.query_transform(query)
            if not query.strip():
                return EvaluationRetrieval(hits=())
            if plan.lexical_ranker == "bm25":
                hits = await bm25_search(
                    session,
                    query,
                    k,
                    filters,
                    k1=plan.bm25_k1,
                    b=plan.bm25_b,
                    idf=plan.bm25_idf,
                    text_search_config=lexical.text_search_config,
                )
            else:
                hits = await lexical_search(
                    session,
                    query,
                    k,
                    filters,
                    text_search_config=lexical.text_search_config,
                )
            return EvaluationRetrieval(hits=tuple(hits))
        assert provider is not None
        if strategy == "vector":
            vector = await provider.embed_query(query)
            hits = await vector_search(
                session, vector, k=k, filters=filters, identity=provider.identity
            )
            return EvaluationRetrieval(hits=tuple(hits))
        result = await retrieve(session, query, provider=provider, k=k, filters=filters, plan=plan)
        return EvaluationRetrieval(hits=result.hits)

    return run
