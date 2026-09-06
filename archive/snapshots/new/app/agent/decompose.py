"""LLM query decomposition and the merged multi-hop retriever."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, StrictStr
from pydantic.functional_validators import model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.types import StrictAgentModel
from app.llm import LLMProvider, Prompt, ProviderBudget
from app.retrieval import (
    DEFAULT_RRF_K,
    ChunkHit,
    EmbeddingProvider,
    RetrievalFilters,
    retrieve,
)

MAX_SUB_QUESTIONS = 4

DECOMPOSE_SYSTEM_PROMPT = (
    "You split one retrieval question into independent sub-questions. "
    "Each sub-question must be answerable from a single passage of an SEC filing. "
    "Return between one and four sub-questions; return the original question "
    "unchanged when it already targets a single fact."
)


class QueryDecomposition(StrictAgentModel):
    """The structured decomposition contract returned by the LLM."""

    sub_questions: tuple[Annotated[StrictStr, Field(min_length=1)], ...]

    @model_validator(mode="after")
    def validate_sub_questions(self) -> Self:
        """Reject empty, oversized, blank, or duplicated decompositions."""
        if not 1 <= len(self.sub_questions) <= MAX_SUB_QUESTIONS:
            raise ValueError(f"decomposition requires 1 to {MAX_SUB_QUESTIONS} sub-questions")
        normalized = [" ".join(question.split()).casefold() for question in self.sub_questions]
        if any(not question for question in normalized):
            raise ValueError("sub-questions must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("sub-questions must be unique")
        return self


async def decompose_query(
    question: str,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
) -> tuple[str, ...]:
    """Return validated sub-questions, falling back to the original on failure.

    The fallback is deliberate: decomposition is an optimization, and an
    unavailable or refusing provider must degrade to the measured single-query
    baseline instead of failing the retrieval request outright.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must not be blank")
    prompt = Prompt(system=DECOMPOSE_SYSTEM_PROMPT, user=question)
    result = await llm_provider.complete(prompt, QueryDecomposition, provider_budget)
    if result.status != "ok" or result.parsed is None:
        return (question,)
    return result.parsed.sub_questions


def merge_ranked_lists(
    ranked_lists: tuple[tuple[ChunkHit, ...], ...],
    k: int,
    *,
    rrf_k: int = DEFAULT_RRF_K,
) -> tuple[ChunkHit, ...]:
    """Fuse per-sub-question rankings with reciprocal-rank scores over n lists.

    This is the M2.5 fusion rule generalized from two fixed components to one
    list per sub-question: only ranks contribute, so sub-questions with
    incomparable native scores still merge deterministically.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    scores: dict[int, float] = {}
    first_seen: dict[int, ChunkHit] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
            first_seen.setdefault(hit.chunk_id, hit)
    fused = sorted(
        first_seen.values(),
        key=lambda hit: (
            -scores[hit.chunk_id],
            hit.doc_id,
            hit.source_sha256,
            hit.start_char,
            hit.end_char,
            hit.chunk_id,
        ),
    )
    return tuple(hit.model_copy(update={"score": scores[hit.chunk_id]}) for hit in fused[:k])


def make_decomposed_retriever(
    session: AsyncSession,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
    embedding_provider: EmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    filters: RetrievalFilters | None = None,
):
    """Return an M3-compatible ``Retriever`` that decomposes before retrieving.

    The callable signature matches ``evaluate_retriever``'s ``Retriever``
    contract exactly, so the decomposed strategy plugs into the existing
    evaluation harness without modifying any M3 file.
    """

    async def retrieve_decomposed(question: str, k: int) -> tuple[ChunkHit, ...]:
        sub_questions = await decompose_query(
            question,
            llm_provider=llm_provider,
            provider_budget=provider_budget,
        )
        ranked_lists = []
        for sub_question in sub_questions:
            result = await retrieve(
                session,
                sub_question,
                provider=embedding_provider,
                k=k,
                candidate_k=candidate_k,
                filters=filters,
                rrf_k=rrf_k,
            )
            ranked_lists.append(result.hits)
        return merge_ranked_lists(tuple(ranked_lists), k, rrf_k=rrf_k)

    return retrieve_decomposed
