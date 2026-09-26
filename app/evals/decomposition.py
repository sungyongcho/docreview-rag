"""Category-sliced comparison of single-query and decomposed retrieval."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from decimal import Decimal
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from app.evals.cli import positive_int
from app.evals.execution.models import EvaluationRetrieval
from app.evals.experiments.decomposition import run_decomposition_comparison
from app.evals.golden.loading import DEFAULT_GOLDEN_PATH, load_golden_cases
from app.retrieval.ranking.fusion import DEFAULT_RRF_K

if TYPE_CHECKING:
    from app.llm.openai import OpenAILLMProvider
    from app.llm.schemas import ProviderBudget

DECOMPOSITION_MAX_INPUT_TOKENS: Final[int] = 1_000
DECOMPOSITION_MAX_OUTPUT_TOKENS: Final[int] = 300


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
    parser.add_argument(
        "--model",
        default=None,
        help="Policy-approved decomposition model; defaults to the role's policy default.",
    )
    parser.add_argument("-k", type=positive_int, default=5)
    parser.add_argument("--candidate-k", type=positive_int, default=20)
    parser.add_argument("--rrf-k", type=positive_int, default=DEFAULT_RRF_K)
    parsed = parser.parse_args(argv)
    if parsed.candidate_k < parsed.k:
        parser.error("--candidate-k must be at least -k")
    return parsed


def decomposition_boundary(
    model_name: str | None,
) -> tuple[OpenAILLMProvider, ProviderBudget]:
    """Build the paid decomposition provider and the budget one question may spend.

    The SDK is imported here rather than at module scope so importing this module
    for its pure comparison helpers never loads it. The key travels through
    ``Settings`` exactly as it does for the embedding provider.
    """
    from app.config import get_settings
    from app.llm.openai import OpenAILLMProvider
    from app.llm.schemas import ProviderBudget
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
        pricing=selection.pricing,
    )
    return provider, budget


async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
    """Bind both arms to the live corpus and run the comparison once.

    Database and provider modules load only here, so ``--help`` and the pure
    comparison helpers stay independent of runtime configuration.
    """
    from app.config import get_settings
    from app.db.session import Session
    from app.evals.experiments.decomposition import make_decomposed_retriever
    from app.retrieval.embedding.provider import get_embedding_provider
    from app.retrieval.search.plan import SearchPlan
    from app.retrieval.search.service import retrieve

    cases = load_golden_cases(args.golden)
    embedding_provider = get_embedding_provider()
    settings = get_settings()

    async def baseline_retriever(question: str, k: int) -> EvaluationRetrieval:
        """Retrieve one question without decomposition, over its own session."""
        async with Session() as session:
            result = await retrieve(
                session,
                question,
                provider=embedding_provider,
                k=k,
                plan=SearchPlan(candidate_k=args.candidate_k, rrf_k=args.rrf_k),
            )
            return EvaluationRetrieval(hits=result.hits)

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
                "decomposition_model": llm_provider.model_name,
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
