"""LLM query decomposition and the fused multi-question retriever."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Self

from pydantic import Field, StrictStr
from pydantic.functional_validators import model_validator

from app.contracts.validation import StrictSchema
from app.db.session_factory import SessionFactory
from app.evals.execution.evaluator import (
    RetrievalEvaluation,
    evaluate_retriever,
    write_evaluation_artifact,
)
from app.evals.execution.models import Decomposition, EvaluationRetrieval
from app.evals.golden.models import GoldenCase
from app.evals.results.identity import artifact_filename
from app.evals.results.scoring import group_scores_by_category
from app.llm.schemas import Prompt, ProviderBudget
from app.retrieval.embedding.provider import EmbeddingProvider, get_embedding_provider
from app.retrieval.ranking.fusion import DEFAULT_RRF_K, fuse_ranked_lists
from app.retrieval.search.plan import SearchPlan
from app.retrieval.search.service import retrieve
from app.retrieval.types import ChunkHit

if TYPE_CHECKING:
    from app.evals.execution.retrievers import Retriever
    from app.llm.completion import LLMProvider


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
                plan=SearchPlan(candidate_k=candidate_k, rrf_k=rrf_k),
            )
            return result.hits

    async def retrieve_decomposed(question: str, k: int) -> EvaluationRetrieval:
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
        return EvaluationRetrieval(
            hits=tuple(fuse_ranked_lists(ranked_lists, k, rrf_k=rrf_k)),
            decomposition=decomposition,
        )

    return retrieve_decomposed


def category_metrics(evaluation: RetrievalEvaluation) -> dict[str, dict[str, float]]:
    """Return macro retrieval metrics per golden category, scored cases only.

    Parameters
    ----------
    evaluation : RetrievalEvaluation
        Completed M3-compatible evaluation with optional per-case scores.

    Returns
    -------
    dict[str, dict[str, float]]
        Macro retrieval metrics keyed by golden category.

    Notes
    -----
    Absent cases remain unscored, matching M3. Each category's numbers come from
    :func:`~app.evals.results.scoring.group_scores_by_category` — the same per-category
    :func:`~app.evals.results.scoring.score_suite` the taxonomy breakdown uses — so the split
    shows whether decomposition moves ``multi_hop`` without regressing
    ``simple_lookup``, on exactly the suite-level arithmetic. Categories are keyed in
    name order.
    """
    groups = group_scores_by_category(
        [(case.golden.category, case.score) for case in evaluation.cases if case.score is not None]
    )
    return {
        group.group: {
            "scored_case_count": float(group.suite.case_count),
            "recall_at_k": group.suite.recall_at_k,
            "hit_rate_at_k": group.suite.hit_rate_at_k,
            "mrr": group.suite.mrr,
        }
        for group in sorted(groups, key=lambda group: group.group)
    }


def _arm_payload(
    evaluation: RetrievalEvaluation,
    categories: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Pair one arm's suite metrics with its already-computed category split."""
    return {
        "metrics": evaluation.metric_values(),
        "categories": categories,
    }


async def run_decomposition_comparison(
    cases: Sequence[GoldenCase],
    *,
    baseline_retriever: Retriever,
    decomposed_retriever: Retriever,
    baseline_config: Mapping[str, Any],
    decomposed_config: Mapping[str, Any],
    suite: str,
    artifact_dir: str | Path,
    k: int = 5,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate both retrievers on one golden suite and write paired artifacts.

    Parameters
    ----------
    cases : Sequence[GoldenCase]
        Shared golden cases evaluated by both arms.
    baseline_retriever : Retriever
        Single-query retrieval callable.
    decomposed_retriever : Retriever
        Query-decomposing retrieval callable.
    baseline_config : Mapping[str, Any]
        Complete provenance for the baseline arm.
    decomposed_config : Mapping[str, Any]
        Complete provenance for the decomposed arm.
    suite : str
        Stable kebab-case evaluation suite name; it becomes part of each
        artifact filename.
    artifact_dir : str | Path
        Destination directory for paired JSON artifacts.
    k : int
        Retrieval cutoff shared by both arms.
    recorded_at : datetime | None
        Optional timezone-aware timestamp shared by both artifacts.

    Returns
    -------
    dict[str, Any]
        Arm metrics, category deltas, and written artifact paths.

    Raises
    ------
    ValueError
        If the supplied timestamp is timezone-naive or the suite is not
        kebab-case. Both are checked before any retrieval runs, so an invalid
        run fails before it spends provider calls.
    FileExistsError
        If an artifact path already exists — two runs sharing one directory and
        one timestamp must fail loudly rather than silently replace evidence.

    Notes
    -----
    Both arms run through the unchanged M3 harness and share one timestamp, so their
    artifact schemas and category deltas remain directly comparable.
    """
    moment = recorded_at or datetime.now(UTC)
    paths = {
        label: Path(artifact_dir) / artifact_filename(moment, f"{suite}-decomposition-{label}")
        for label in ("baseline", "decomposed")
    }
    for path in paths.values():
        if path.exists():
            raise FileExistsError(f"evaluation artifact already exists: {path}")
    baseline = await evaluate_retriever(
        cases,
        baseline_retriever,
        suite=suite,
        config=baseline_config,
        k=k,
        recorded_at=moment,
    )
    decomposed = await evaluate_retriever(
        cases,
        decomposed_retriever,
        suite=suite,
        config=decomposed_config,
        k=k,
        recorded_at=moment,
    )
    write_evaluation_artifact(paths["baseline"], baseline)
    write_evaluation_artifact(paths["decomposed"], decomposed)
    baseline_categories = category_metrics(baseline)
    decomposed_categories = category_metrics(decomposed)
    deltas = {
        category: {
            "recall_at_k": decomposed_categories[category]["recall_at_k"]
            - baseline_categories[category]["recall_at_k"],
            "mrr": decomposed_categories[category]["mrr"] - baseline_categories[category]["mrr"],
        }
        for category in sorted(set(baseline_categories) & set(decomposed_categories))
    }
    return {
        "suite": suite,
        "k": k,
        "baseline": _arm_payload(baseline, baseline_categories),
        "decomposed": _arm_payload(decomposed, decomposed_categories),
        "category_deltas": deltas,
        "artifacts": {label: str(path) for label, path in paths.items()},
    }
