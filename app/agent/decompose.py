"""LLM query decomposition and the fused multi-question retriever."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import logging
from typing import TYPE_CHECKING, Annotated, NamedTuple, Self

from pydantic import Field, StrictStr
from pydantic.functional_validators import model_validator

from app.llm.schemas import Prompt, ProviderBudget, StrictSchema
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K, fuse_ranked_lists
from app.retrieval.service import retrieve
from app.retrieval.types import ChunkHit, RetrievalFilters

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.llm.provider import LLMProvider

type Retriever = Callable[[str, int], Awaitable[Sequence[ChunkHit]]]
type SessionFactory = Callable[[], AsyncSession]

_LOGGER = logging.getLogger(__name__)

MAX_SUB_QUESTIONS = 4

DECOMPOSE_SYSTEM_PROMPT = (
    "You split one retrieval question into independent sub-questions. "
    "Each sub-question must be answerable from a single passage of an SEC filing. "
    "Return between one and four sub-questions; return the original question "
    "unchanged when it already targets a single fact."
)


class QueryDecomposition(StrictSchema):
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


class Decomposition(NamedTuple):
    """Sub-questions plus the provider status that produced them.

    ``fallback_status`` is ``None`` when the LLM decomposed the question, and the
    provider's failure status when the original question is being used unchanged
    — so a caller can tell an intended refusal-degradation from an outage instead
    of reading identical results from both.
    """

    sub_questions: tuple[str, ...]
    fallback_status: str | None


async def decompose_query(
    question: str,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
) -> Decomposition:
    """Return validated sub-questions, falling back to the original on failure.

    Parameters
    ----------
    question : str
        Nonblank retrieval question.
    llm_provider : LLMProvider
        Explicit structured-output provider.
    provider_budget : ProviderBudget
        Per-call token and estimated-cost boundary.

    Returns
    -------
    Decomposition
        Validated sub-questions with no fallback status, or the original question
        as a one-item fallback carrying the provider status that caused it.

    Raises
    ------
    ValueError
        If the original question is blank.

    Notes
    -----
    Decomposition is an optimization. Provider refusal or schema failure degrades to
    the measured single-query baseline rather than failing retrieval — but the
    degradation is reported, not hidden, so an evaluation run over a broken
    provider cannot masquerade as a genuine null result.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must not be blank")
    prompt = Prompt(system=DECOMPOSE_SYSTEM_PROMPT, user=question)
    result = await llm_provider.complete(prompt, QueryDecomposition, provider_budget)
    if result.status != "ok" or result.parsed is None:
        status = result.status if result.status != "ok" else "missing_parse"
        return Decomposition(sub_questions=(question,), fallback_status=status)
    return Decomposition(sub_questions=result.parsed.sub_questions, fallback_status=None)


def make_decomposed_retriever(
    session_factory: SessionFactory,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
    embedding_provider: EmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Return an M3-compatible ``Retriever`` that decomposes before retrieving.

    Parameters
    ----------
    session_factory : SessionFactory
        Callable producing one fresh ``AsyncSession`` per sub-question, e.g. the
        application ``async_sessionmaker``; independent sessions let the
        sub-question retrievals run concurrently.
    llm_provider : LLMProvider
        Explicit provider used only for decomposition.
    provider_budget : ProviderBudget
        Budget applied to the decomposition call.
    embedding_provider : EmbeddingProvider | None
        Explicit query embedding provider, or ``None`` to resolve the configured
        provider once here — never per retrieval.
    candidate_k : int | None
        Optional retrieval candidate depth.
    rrf_k : int
        Reciprocal-rank constant for sub-question fusion.
    filters : RetrievalFilters | None
        Optional immutable filing restrictions shared across sub-questions.

    Returns
    -------
    Retriever
        M3-compatible callable that decomposes, retrieves concurrently, and fuses.

    Notes
    -----
    A degraded decomposition (provider failure, schema rejection) is logged with
    its status before the single-query fallback runs, so an evaluation over a
    broken provider is visible in the run's own output. Each sub-question owns a
    session for the duration of one retrieval; closing it releases the read.
    """
    provider = embedding_provider if embedding_provider is not None else get_embedding_provider()

    async def retrieve_one(sub_question: str, k: int) -> tuple[ChunkHit, ...]:
        """Retrieve one sub-question over its own short-lived session."""
        async with session_factory() as session:
            result = await retrieve(
                session,
                sub_question,
                provider=provider,
                k=k,
                candidate_k=candidate_k,
                filters=filters,
                rrf_k=rrf_k,
            )
            return result.hits

    async def retrieve_decomposed(question: str, k: int) -> Sequence[ChunkHit]:
        """Decompose one question, retrieve each sub-question concurrently, and fuse."""
        decomposition = await decompose_query(
            question,
            llm_provider=llm_provider,
            provider_budget=provider_budget,
        )
        if decomposition.fallback_status is not None:
            _LOGGER.warning(
                "decomposition fell back to the original question (status=%s): %.120s",
                decomposition.fallback_status,
                question,
            )
        ranked_lists = await asyncio.gather(
            *(retrieve_one(sub_question, k) for sub_question in decomposition.sub_questions)
        )
        return fuse_ranked_lists(ranked_lists, k, rrf_k=rrf_k)

    return retrieve_decomposed
