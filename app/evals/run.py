"""Command-line runner for isolated retrieval ablations and latency budgets.

The runner builds isolated PostgreSQL corpora, binds explicit retrieval strategies,
and emits comparable JSON evidence without modifying the populated application corpus.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import json
from pathlib import Path
import time
from typing import Any, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import BM25Idf, LexicalRanker, Settings, get_settings
from app.db.bootstrap import bootstrap_schema
from app.evals.ablation import (
    AblationOutcome,
    AblationReport,
    ExperimentConfig,
    experiment_matrix,
    run_ablation,
)
from app.evals.arms import (
    LEXICAL_RANKERS,
    RETRIEVAL_STRATEGIES,
    BM25Parameters,
    RetrievalStrategy,
    make_retriever,
)
from app.evals.artifacts import write_json_artifact
from app.evals.cli import positive_int
from app.evals.corpus import build_chunking_batch, load_chunking_filings, temporary_corpus_session
from app.evals.identity import RANKER_ORDER, STRATEGY_ORDER, artifact_filename
from app.evals.loader import DEFAULT_GOLDEN_PATH, load_golden_cases
from app.evals.measurement import (
    QUERY_BUDGET_COUNT,
    IndexingBudgetMeasurement,
    QueryBudgetArm,
    QueryBudgetMeasurement,
    SharedPreparationMeasurement,
    budget_artifact_payload,
    budgets_passed,
    measure_query_budget,
)
from app.evals.retrieval_eval import (
    PersistedEvaluation,
    RetrievalEvaluation,
    evaluate_retriever,
    persist_evaluation,
)
from app.ingestion.progress import OperationProgress, OperationProgressCallback, operation_bar
from app.ingestion.seed import embedding_chunk_config
from app.retrieval.embeddings import get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K

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


def budget_arm_selection(
    strategies: Sequence[RetrievalStrategy],
    lexical_rankers: Sequence[LexicalRanker],
) -> tuple[RetrievalStrategy, LexicalRanker | None]:
    """Choose the one arm the repeated-query budget is measured on.

    The choice follows the matrix's canonical order rather than the order the axes were
    typed, so the reported budget is a property of the requested experiment and not of
    the command line that requested it. The deepest retrieval path wins, because it
    bounds the others.

    Raises
    ------
    ValueError
        If no strategy is supplied, or a lexical-bearing strategy has no ranker.
    """
    if not strategies:
        raise ValueError("budget arm selection requires at least one strategy")
    strategy = max(strategies, key=lambda name: STRATEGY_ORDER[name])
    if strategy == "vector":
        return strategy, None
    if not lexical_rankers:
        raise ValueError(f"{strategy} retrieval requires a lexical ranker")
    return strategy, min(lexical_rankers, key=lambda name: RANKER_ORDER[name])


async def run_matrix(
    *,
    suite: str,
    golden: Path,
    manifest_name: str,
    selection_id: str,
    artifact_dir: Path,
    provider: MatrixEmbeddingProvider,
    target_tokens: Sequence[int],
    strategies: Sequence[RetrievalStrategy],
    lexical_rankers: Sequence[LexicalRanker],
    k: int,
    candidate_k: int,
    rrf_k: int,
    bm25_k1: float | None,
    bm25_b: float | None,
    bm25_idf: BM25Idf | None,
    persist_results: bool,
    budget_queries: int = QUERY_BUDGET_COUNT,
    admin_metadata: Mapping[str, object] | None = None,
    on_progress: OperationProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the isolated experiment matrix and its repeated-query budget once.

    Parameters
    ----------
    suite : str
        Evaluation suite name recorded on every arm.
    golden : Path
        Golden case file evaluated by every arm.
    manifest_name : str
        Corpus manifest, resolved against the configured corpus directory.
    selection_id : str
        Manifest selection whose filings are chunked and indexed.
    artifact_dir : Path
        Destination directory for the raw arm artifacts and the budget artifact.
    provider : MatrixEmbeddingProvider
        Embedding provider used by every arm and by the budget measurement.
    target_tokens : Sequence[int]
        Chunk targets, each indexed into its own temporary corpus.
    strategies : Sequence[RetrievalStrategy]
        Unique retrieval strategies crossed with every chunk target.
    lexical_rankers : Sequence[LexicalRanker]
        Unique lexical rankers crossed with every lexical and hybrid arm.
    k : int
        Final hit count requested from retrieval.
    candidate_k : int
        Candidate depth, at least ``k``.
    rrf_k : int
        Reciprocal-rank-fusion constant.
    bm25_k1 : float | None
        BM25 ``k1`` override, or ``None`` to keep the configured value.
    bm25_b : float | None
        BM25 ``b`` override, or ``None`` to keep the configured value.
    bm25_idf : BM25Idf | None
        BM25 IDF formula override, or ``None`` to keep the configured value.
    persist_results : bool
        Whether every arm is persisted and compared with its stored baseline.
    budget_queries : int, optional
        Number of repeated queries in the latency budget measurement.
    admin_metadata : Mapping[str, object] | None, optional
        Extra provenance merged into every arm's recorded config.
    on_progress : OperationProgressCallback | None, optional
        Receiver of stage and golden-case progress updates.

    Returns
    -------
    dict[str, Any]
        Comparison table, raw artifact paths, budget evidence, optional persisted-result
        identities, and the single ``passed`` verdict :func:`main` exits on.

    Raises
    ------
    ValueError
        If the requested matrix or retrieval limits are invalid.
    RuntimeError
        If indexing, query-budget measurement, or result persistence is incomplete.
    OSError
        If corpus or artifact files cannot be read or written.

    Notes
    -----
    The manifest is parsed once, while each chunk target receives a fresh ``SeedBatch``
    and temporary PostgreSQL corpus. The repeated-query budget runs on the last chunk
    target and the canonical budget arm, and that arm is recorded in the artifact. The
    engine is disposed on every exit path.
    """
    updates: dict[str, Any] = {"embedding_provider": provider}
    if bm25_k1 is not None:
        updates["bm25_k1"] = bm25_k1
    if bm25_b is not None:
        updates["bm25_b"] = bm25_b
    if bm25_idf is not None:
        updates["bm25_idf"] = bm25_idf
    current_settings = get_settings()
    settings = Settings.model_validate(current_settings.model_dump() | updates)
    embedding_provider = get_embedding_provider(settings)
    targets = sorted(
        {
            embedding_chunk_config(embedding_provider, target_tokens=value).target_tokens
            for value in target_tokens
        }
    )
    cases = load_golden_cases(
        golden,
        manifest_path=settings.corpus_dir / manifest_name,
        selection_id=selection_id,
    )
    recorded_at = datetime.now(UTC)

    budget_strategy, budget_ranker = budget_arm_selection(strategies, lexical_rankers)
    budget_bm25: BM25Parameters | None = (
        (settings.bm25_k1, settings.bm25_b, settings.bm25_idf) if budget_ranker == "bm25" else None
    )

    preparation_started_at_ns = time.perf_counter_ns()
    parsed_filings = load_chunking_filings(
        settings=settings,
        manifest_name=manifest_name,
        selection_id=selection_id,
        on_progress=on_progress,
    )
    shared_preparation = SharedPreparationMeasurement(
        operation="manifest-load-and-parse",
        document_count=len(parsed_filings),
        total_seconds=(time.perf_counter_ns() - preparation_started_at_ns) / 1_000_000_000,
    )

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    all_outcomes: list[AblationOutcome] = []
    indexing_measurements: list[IndexingBudgetMeasurement] = []
    query_budget: QueryBudgetMeasurement | None = None
    try:
        for target in targets:
            indexing_started_at_ns = time.perf_counter_ns()
            batch = build_chunking_batch(
                target,
                provider=embedding_provider,
                parsed_filings=parsed_filings,
                selection_id=selection_id,
                settings=settings,
                on_progress=on_progress,
            )
            configs = experiment_matrix(
                target_tokens=(target,),
                strategies=tuple(strategies),
                lexical_rankers=tuple(lexical_rankers),
                embedding_provider=provider,
                dimensions=embedding_provider.dimensions,
                k=k,
                candidate_k=candidate_k,
                rrf_k=rrf_k,
                bm25_k1=settings.bm25_k1,
                bm25_b=settings.bm25_b,
                bm25_idf=settings.bm25_idf,
            )
            async with temporary_corpus_session(
                engine,
                batch,
                embedding_provider,
                target_tokens=target,
                embedding_provider=provider,
                shared_preparation_seconds=shared_preparation.total_seconds,
                started_at_ns=indexing_started_at_ns,
                on_progress=on_progress,
            ) as (session, indexing):
                indexing_measurements.append(indexing)

                async def evaluator(config: ExperimentConfig) -> RetrievalEvaluation:
                    """Evaluate one matrix configuration against the active corpus."""
                    retriever = make_retriever(
                        session,
                        strategy=config.strategy,
                        provider=embedding_provider,
                        lexical_ranker=config.lexical_ranker,
                        bm25_k1=config.bm25_k1,
                        bm25_b=config.bm25_b,
                        bm25_idf=config.bm25_idf,
                        candidate_k=config.candidate_k,
                        rrf_k=config.rrf_k,
                    )

                    def publish_case(progress: OperationProgress) -> None:
                        """Name the active matrix arm on each golden-case update."""
                        if on_progress is not None:
                            on_progress(
                                OperationProgress(
                                    f"evaluate:{config.name}",
                                    progress.current,
                                    progress.total,
                                    f"{config.name} · {progress.message}",
                                )
                            )

                    return await evaluate_retriever(
                        cases,
                        retriever,
                        suite=suite,
                        config=config.to_dict() | dict(admin_metadata or {}),
                        k=config.k,
                        recorded_at=recorded_at,
                        on_progress=publish_case if on_progress is not None else None,
                    )

                report = await run_ablation(
                    configs,
                    evaluator,
                    artifact_dir=artifact_dir,
                    recorded_at=recorded_at,
                )
                all_outcomes.extend(report.outcomes)

                if target == targets[-1]:
                    budget_retriever = make_retriever(
                        session,
                        strategy=budget_strategy,
                        provider=embedding_provider,
                        lexical_ranker=budget_ranker,
                        bm25_k1=None if budget_bm25 is None else budget_bm25[0],
                        bm25_b=None if budget_bm25 is None else budget_bm25[1],
                        bm25_idf=None if budget_bm25 is None else budget_bm25[2],
                        candidate_k=candidate_k,
                        rrf_k=rrf_k,
                    )
                    query_budget = await measure_query_budget(
                        [case.question for case in cases],
                        budget_retriever,
                        k=k,
                        query_count=budget_queries,
                    )

        if query_budget is None:
            raise RuntimeError("query budget was not measured")

        budget_payload = budget_artifact_payload(
            recorded_at=recorded_at,
            embedding_provider=provider,
            shared_preparation=shared_preparation,
            indexing=indexing_measurements,
            query_budget=query_budget,
            query_budget_arm=QueryBudgetArm(
                target_tokens=targets[-1],
                strategy=budget_strategy,
                lexical_ranker=budget_ranker,
                bm25=budget_bm25,
                k=k,
                candidate_k=candidate_k,
                rrf_k=rrf_k,
            ),
        )
        budget_path = write_json_artifact(
            artifact_dir / artifact_filename(recorded_at, "budgets"), budget_payload
        )

        persisted: list[PersistedEvaluation] = []
        if persist_results:
            await bootstrap_schema(engine)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                for outcome in all_outcomes:
                    persisted.append(
                        await persist_evaluation(
                            session,
                            outcome.evaluation,
                            raw_artifact_path=outcome.artifact_path,
                        )
                    )
                await session.commit()

        combined = AblationReport(outcomes=tuple(all_outcomes))
        return {
            "passed": budgets_passed(indexing_measurements, query_budget)
            and all(result.passed for result in persisted),
            "comparison_table": combined.comparison_markdown(),
            "artifacts": [str(outcome.artifact_path) for outcome in all_outcomes],
            "budget_artifact": str(budget_path),
            "indexing": budget_payload["indexing"],
            "query_budget": budget_payload["query_budget"],
            "persisted": [result.to_dict() for result in persisted],
        }
    finally:
        await engine.dispose()


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
