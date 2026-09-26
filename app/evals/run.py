"""Command-line runner for isolated retrieval ablations and latency budgets.

The runner builds isolated PostgreSQL corpora, binds explicit retrieval strategies,
and emits comparable JSON evidence without modifying the populated application corpus.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
import json
from pathlib import Path
from typing import Final, Literal

from app.evals.cli import positive_int
from app.evals.execution.measurement import QUERY_BUDGET_COUNT
from app.evals.execution.retrievers import LEXICAL_RANKERS, RETRIEVAL_STRATEGIES
from app.evals.experiments.matrix import run_matrix
from app.evals.golden.loading import DEFAULT_GOLDEN_PATH
from app.ingestion.progress import operation_bar
from app.retrieval.ranking.fusion import DEFAULT_RRF_K

MatrixEmbeddingProvider = Literal["deterministic", "openai"]
MATRIX_EMBEDDING_PROVIDERS: Final[tuple[MatrixEmbeddingProvider, ...]] = ("deterministic", "openai")


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse and normalize command-line arguments for the isolated ablation runner.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Explicit argument tokens, or process arguments when omitted.

    Returns
    -------
    argparse.Namespace
        Parsed experiment matrix, artifact, provider, budget, and persistence options.

    Raises
    ------
    SystemExit
        If help is requested or supplied arguments fail parser validation.

    Notes
    -----
    Every matrix axis is deduplicated and sorted into its canonical order here, so a
    repeated flag value cannot fail deep inside the run and two invocations that name
    the same axes in different orders produce the same experiment and the same budget
    arm. Cross-argument limits are rejected before any corpus is read.
    """
    parser = argparse.ArgumentParser(
        description="Run isolated source-span retrieval ablations and latency budgets."
    )
    parser.add_argument("--suite", default="m3-retrieval-v1")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--manifest-name", default="manifest.json")
    parser.add_argument("--selection-id", default="sec-evaluation")
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/eval_runs"))
    parser.add_argument("--provider", choices=MATRIX_EMBEDDING_PROVIDERS, default="deterministic")
    parser.add_argument("--target-tokens", type=positive_int, nargs="+", default=[1024, 2048])
    parser.add_argument(
        "--strategies",
        choices=RETRIEVAL_STRATEGIES,
        nargs="+",
        default=list(RETRIEVAL_STRATEGIES),
    )
    parser.add_argument(
        "--lexical-rankers",
        choices=LEXICAL_RANKERS,
        nargs="+",
        default=list(LEXICAL_RANKERS),
        help="Lexical rankers to cross with every lexical and hybrid arm.",
    )
    parser.add_argument("-k", type=positive_int, default=5)
    parser.add_argument("--candidate-k", type=positive_int, default=20)
    parser.add_argument("--rrf-k", type=positive_int, default=DEFAULT_RRF_K)
    parser.add_argument("--bm25-k1", type=float, default=None)
    parser.add_argument("--bm25-b", type=float, default=None)
    parser.add_argument("--bm25-idf", choices=("lucene", "robertson"), default=None)
    parser.add_argument("--budget-queries", type=positive_int, default=QUERY_BUDGET_COUNT)
    parser.add_argument("--persist-results", action="store_true")
    parsed = parser.parse_args(argv)

    parsed.target_tokens = sorted(set(parsed.target_tokens))
    parsed.strategies = [name for name in RETRIEVAL_STRATEGIES if name in parsed.strategies]
    parsed.lexical_rankers = [name for name in LEXICAL_RANKERS if name in parsed.lexical_rankers]
    if parsed.candidate_k < parsed.k:
        parser.error("--candidate-k must be at least -k")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    """Run the complete isolated evaluation command and report its verdict.

    Returns
    -------
    int
        ``0`` when every indexing arm, the repeated-query budget, and every persisted
        regression comparison stayed within its limit, and ``1`` otherwise. A measured
        budget or quality regression must fail the process; printing it is not enough.
    """
    with operation_bar("Evaluation") as progress:
        result = asyncio.run(run_matrix(**vars(arguments(argv)), on_progress=progress))
    print(result["comparison_table"])
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "comparison_table"}, indent=2
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
