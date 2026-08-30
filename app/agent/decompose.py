"""LLM query decomposition and the merged multi-hop retriever."""

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Annotated, Protocol, Self

from pydantic import Field, StrictStr
from pydantic.functional_validators import model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.provider import LLMProvider
from app.llm.schemas import Prompt, ProviderBudget, StrictSchema

if TYPE_CHECKING:
    from app.retrieval.embeddings import EmbeddingProvider
    from app.retrieval.service import RetrievalResult
    from app.retrieval.types import ChunkHit, RetrievalFilters
else:
    EmbeddingProvider = object
    ChunkHit = object
    RetrievalFilters = object

DEFAULT_RRF_K = 60

type Retriever = Callable[[str, int], Awaitable[Sequence[ChunkHit]]]


class _RetrievalResult(Protocol):
    """Materialized retrieval result consumed by decomposition."""

    @property
    def hits(self) -> tuple[ChunkHit, ...]:
        """Return immutable ranked hits."""
        ...


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    provider: EmbeddingProvider | None = None,
    k: int = 5,
    candidate_k: int | None = None,
    filters: RetrievalFilters | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> _RetrievalResult:
    """Load production retrieval only when the decomposed path actually runs."""
    from app.retrieval.service import retrieve as retrieve_service

    result: RetrievalResult = await retrieve_service(
        session,
        query,
        provider=provider,
        k=k,
        candidate_k=candidate_k,
        filters=filters,
        rrf_k=rrf_k,
    )
    return result


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


async def decompose_query(
    question: str,
    *,
    llm_provider: LLMProvider,
    provider_budget: ProviderBudget,
) -> tuple[str, ...]:
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
    tuple[str, ...]
        Validated sub-questions, or the original question as a one-item fallback.

    Raises
    ------
    ValueError
        If the original question is blank.

    Notes
    -----
    Decomposition is an optimization. Provider refusal or schema failure degrades to
    the measured single-query baseline rather than failing retrieval.
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

    Parameters
    ----------
    ranked_lists : tuple[tuple[ChunkHit, ...], ...]
        Ranked results from each independently retrieved sub-question.
    k : int
        Positive number of fused hits to return.
    rrf_k : int
        Positive reciprocal-rank constant.

    Returns
    -------
    tuple[ChunkHit, ...]
        Deterministically ordered hits carrying accumulated RRF scores.

    Raises
    ------
    ValueError
        If limits are invalid or one chunk id carries conflicting source identity.

    Notes
    -----
    Each input list contributes at most one rank per chunk id, matching the M2 RRF
    contract and preventing duplicate rows from amplifying one sub-question.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    def identity(hit: ChunkHit) -> tuple[object, ...]:
        """Return immutable source identity, excluding the lane-specific score."""
        return (
            hit.doc_id,
            hit.citation,
            hit.start_char,
            hit.end_char,
            hit.source_sha256,
            hit.body,
        )

    scores: dict[int, float] = {}
    first_seen: dict[int, ChunkHit] = {}
    for hits in ranked_lists:
        seen_in_list: set[int] = set()
        rank = 0
        for hit in hits:
            previous = first_seen.get(hit.chunk_id)
            if previous is not None and identity(previous) != identity(hit):
                raise ValueError(f"chunk {hit.chunk_id} has conflicting source identity")
            if hit.chunk_id in seen_in_list:
                continue
            seen_in_list.add(hit.chunk_id)
            rank += 1
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
) -> Retriever:
    """Return an M3-compatible ``Retriever`` that decomposes before retrieving.

    Parameters
    ----------
    session : AsyncSession
        Caller-owned session used by sequential retrieval reads.
    llm_provider : LLMProvider
        Explicit provider used only for decomposition.
    provider_budget : ProviderBudget
        Budget applied to the decomposition call.
    embedding_provider : EmbeddingProvider | None
        Optional explicit query embedding provider.
    candidate_k : int | None
        Optional retrieval candidate depth.
    rrf_k : int
        Reciprocal-rank constant for sub-question fusion.
    filters : RetrievalFilters | None
        Optional immutable filing restrictions shared across sub-questions.

    Returns
    -------
    Retriever
        M3-compatible callable that decomposes, retrieves, closes reads, and fuses.

    Notes
    -----
    The callable plugs into the unchanged M3 harness. Every retrieval transaction is
    rolled back before a later invocation can wait on the provider.
    """

    async def close_read_transaction() -> None:
        """Release retrieval reads before a later query invokes the provider."""
        if session.in_transaction():
            await session.rollback()

    async def retrieve_decomposed(question: str, k: int) -> tuple[ChunkHit, ...]:
        """Decompose one question, retrieve each sub-question, and fuse the rankings."""
        sub_questions = await decompose_query(
            question,
            llm_provider=llm_provider,
            provider_budget=provider_budget,
        )
        ranked_lists = []
        for sub_question in sub_questions:
            try:
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
            finally:
                await close_read_transaction()
        return merge_ranked_lists(tuple(ranked_lists), k, rrf_k=rrf_k)

    return retrieve_decomposed
