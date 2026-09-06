"""Category-sliced comparison of single-query and decomposed retrieval."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from app.evals.cli import positive_int
from app.evals.identity import artifact_filename
from app.evals.loader import DEFAULT_GOLDEN_PATH, load_golden_cases
from app.evals.retrieval_eval import (
    RetrievalEvaluation,
    evaluate_retriever,
    write_evaluation_artifact,
)
from app.evals.scoring import CaseScore, score_suite
from app.retrieval.hybrid import DEFAULT_RRF_K

if TYPE_CHECKING:
    from app.evals.arms import Retriever
    from app.evals.types import GoldenCase
    from app.llm.provider import OpenAILLMProvider
    from app.llm.schemas import ProviderBudget

DECOMPOSITION_MAX_INPUT_TOKENS: Final[int] = 1_000
DECOMPOSITION_MAX_OUTPUT_TOKENS: Final[int] = 300


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
    :func:`~app.evals.scoring.score_suite` — the single implementation of macro
    averaging — so the split shows whether decomposition moves ``multi_hop``
    without regressing ``simple_lookup``, on exactly the suite-level arithmetic.
    """
    grouped: dict[str, list[CaseScore]] = {}
    for case in evaluation.cases:
        if case.score is None:
            continue
        grouped.setdefault(case.golden.category, []).append(case.score)
    metrics: dict[str, dict[str, float]] = {}
    for category in sorted(grouped):
        suite_score = score_suite(grouped[category])
        metrics[category] = {
            "scored_case_count": float(suite_score.case_count),
            "recall_at_k": suite_score.recall_at_k,
            "hit_rate_at_k": suite_score.hit_rate_at_k,
            "mrr": suite_score.mrr,
        }
    return metrics


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


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the decomposition-comparison command line."""
    parser = argparse.ArgumentParser(
        description=(
            "Compare single-query and LLM-decomposed retrieval on one golden "
            "suite over the populated application corpus."
        )
    )
    parser.add_argument("--suite", default="m9-decomposition-v1")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/eval_runs"))
    parser.add_argument("--model", default="gpt-5.6-terra")
    parser.add_argument("-k", type=positive_int, default=5)
    parser.add_argument("--candidate-k", type=positive_int, default=20)
    parser.add_argument("--rrf-k", type=positive_int, default=DEFAULT_RRF_K)
    parsed = parser.parse_args(argv)
    if parsed.candidate_k < parsed.k:
        parser.error("--candidate-k must be at least -k")
    return parsed


def decomposition_boundary(model_name: str) -> tuple[OpenAILLMProvider, ProviderBudget]:
    """Build the paid decomposition provider and the budget one question may spend.

    The SDK is imported here rather than at module scope so importing this module
    for its pure comparison helpers never loads it. The key travels through
    ``Settings`` exactly as it does for the embedding provider.
    """
    from app.config import get_settings
    from app.llm.provider import OpenAILLMProvider
    from app.llm.schemas import ProviderBudget, TokenPricing
    from app.openai_models import resolve_openai_model

    settings = get_settings()
    selection = resolve_openai_model("decomposition", model_name)
    provider = OpenAILLMProvider(
        model_name=selection.model,
        role="decomposition",
        api_key=(settings.openai_api_key.get_secret_value() if settings.openai_api_key else None),
    )
    budget = ProviderBudget(
        max_input_tokens=DECOMPOSITION_MAX_INPUT_TOKENS,
        max_output_tokens=DECOMPOSITION_MAX_OUTPUT_TOKENS,
        max_cost_usd=Decimal("0.05"),
        pricing=TokenPricing(
            input_per_million_usd=selection.pricing.input_per_million_usd,
            output_per_million_usd=selection.pricing.output_per_million_usd,
            cached_input_per_million_usd=selection.pricing.cached_input_per_million_usd,
            cache_write_input_per_million_usd=(selection.pricing.cache_write_input_per_million_usd),
        ),
    )
    return provider, budget


async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    """Bind both arms to the live corpus and run the comparison once.

    Database and provider modules load only here, so ``--help`` and the pure
    comparison helpers stay independent of runtime configuration.
    """
    from app.agent.decompose import make_decomposed_retriever
    from app.config import get_settings
    from app.db.session import Session
    from app.retrieval.embeddings import get_embedding_provider
    from app.retrieval.service import retrieve
    from app.retrieval.types import ChunkHit

    cases = load_golden_cases(args.golden)
    embedding_provider = get_embedding_provider()
    settings = get_settings()

    async def baseline_retriever(question: str, k: int) -> Sequence[ChunkHit]:
        """Retrieve one question without decomposition, over its own session."""
        async with Session() as session:
            result = await retrieve(
                session,
                question,
                provider=embedding_provider,
                k=k,
                candidate_k=args.candidate_k,
                rrf_k=args.rrf_k,
            )
            return result.hits

    llm_provider, provider_budget = decomposition_boundary(args.model)
    shared_config = {
        "k": args.k,
        "candidate_k": args.candidate_k,
        "rrf_k": args.rrf_k,
        "embedding_provider": settings.embedding_provider,
    }
    try:
        decomposed_retriever = make_decomposed_retriever(
            Session,
            llm_provider=llm_provider,
            provider_budget=provider_budget,
            embedding_provider=embedding_provider,
            candidate_k=args.candidate_k,
            rrf_k=args.rrf_k,
        )
        return await run_decomposition_comparison(
            cases,
            baseline_retriever=baseline_retriever,
            decomposed_retriever=decomposed_retriever,
            baseline_config={**shared_config, "strategy": "single_query"},
            decomposed_config={
                **shared_config,
                "strategy": "decomposed",
                "decomposition_model": args.model,
            },
            suite=args.suite,
            artifact_dir=args.artifact_dir,
            k=args.k,
        )
    finally:
        await llm_provider.aclose()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the decomposition comparison and print its machine-readable result."""
    result = asyncio.run(_run_cli(arguments(argv)))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
