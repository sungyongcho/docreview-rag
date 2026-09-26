"""Define deterministic ablation arms, ordering, and artifact orchestration."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import time
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import (
    DEFAULT_BM25_B,
    DEFAULT_BM25_IDF,
    DEFAULT_BM25_K1,
    BM25Idf,
    LexicalRanker,
    Settings,
    get_settings,
)
from app.db.bootstrap import bootstrap_schema
from app.evals.execution.evaluator import (
    PersistedEvaluation,
    RetrievalEvaluation,
    evaluate_retriever,
    persist_evaluation,
    write_evaluation_artifact,
)
from app.evals.execution.measurement import (
    QUERY_BUDGET_COUNT,
    IndexingBudgetMeasurement,
    QueryBudgetArm,
    QueryBudgetMeasurement,
    SharedPreparationMeasurement,
    budget_artifact_payload,
    budgets_passed,
    measure_query_budget,
)
from app.evals.execution.retrievers import (
    LEXICAL_RANKERS,
    BM25Parameters,
    experiment_search_plan,
    make_retriever,
)
from app.evals.experiments.corpus import (
    build_chunking_batch,
    load_chunking_filings,
    temporary_corpus_session,
)
from app.evals.golden.loading import load_golden_cases
from app.evals.results.artifacts import write_json_artifact
from app.evals.results.identity import (
    ARM_NAME,
    RANKER_ORDER,
    RANKER_SLUG,
    STRATEGY_ORDER,
    artifact_filename,
)
from app.evals.results.reporting import markdown_table
from app.ingestion.pipeline import embedding_chunk_config
from app.ingestion.progress import OperationProgress, OperationProgressCallback
from app.retrieval.embedding.provider import get_embedding_provider
from app.retrieval.ranking.fusion import DEFAULT_RRF_K
from app.retrieval.search.plan import RetrievalStrategy

MatrixEmbeddingProvider = Literal["deterministic", "openai"]

type ExperimentEvaluator = Callable[["ExperimentConfig"], Awaitable[RetrievalEvaluation]]


def experiment_name(
    target_tokens: int,
    strategy: RetrievalStrategy,
    lexical_ranker: LexicalRanker | None,
) -> str:
    """Compose the kebab-case artifact-name stem for one experiment arm.

    The stem encodes the supplied dimensions only. ``ExperimentConfig`` performs the
    complete name and cross-field validation.

    Raises
    ------
    KeyError
        If ``lexical_ranker`` has no registered filename slug.
    """
    stem = f"structure-{target_tokens}-{strategy}"
    return stem if lexical_ranker is None else f"{stem}-{RANKER_SLUG[lexical_ranker]}"


def sort_key(config: ExperimentConfig) -> tuple[int, int, int, str]:
    """Return the deterministic ordering key for an experiment arm.

    Arms sort by chunk target, then retrieval path in the fixed order lexical, vector,
    hybrid; within lexical and hybrid arms ``ts_rank_cd`` precedes BM25, and the arm
    name breaks final ties.
    """
    return (
        config.target_tokens,
        STRATEGY_ORDER[config.strategy],
        -1 if config.lexical_ranker is None else RANKER_ORDER[config.lexical_ranker],
        config.name,
    )


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Represent one validated chunking and retrieval experiment arm.

    Raises
    ------
    ValueError
        If the name is malformed, the chunk target or dimensions are nonpositive, the
        provider is blank, retrieval limits conflict, or strategy, ranker, and BM25
        values form an invalid combination.

    Notes
    -----
    Vector arms cannot declare a lexical ranker, while lexical and hybrid arms must
    declare one. BM25 arms must carry a complete valid parameter set, and other arms
    cannot carry BM25 parameters.
    """

    name: str
    target_tokens: int
    strategy: RetrievalStrategy
    embedding_provider: str
    dimensions: int
    lexical_ranker: LexicalRanker | None = None
    bm25_k1: float | None = None
    bm25_b: float | None = None
    bm25_idf: BM25Idf | None = None
    k: int = 5
    candidate_k: int = 20
    rrf_k: int = DEFAULT_RRF_K

    def __post_init__(self) -> None:
        """Reject contradictory or incomplete experiment provenance."""
        if ARM_NAME.fullmatch(self.name) is None:
            raise ValueError("experiment name must be lowercase kebab-case")
        if self.target_tokens <= 0 or self.dimensions <= 0:
            raise ValueError("chunk target and embedding dimensions must be positive")
        if not self.embedding_provider.strip():
            raise ValueError("embedding_provider must be nonblank")
        experiment_search_plan(
            strategy=self.strategy,
            lexical_ranker=self.lexical_ranker,
            bm25_k1=self.bm25_k1,
            bm25_b=self.bm25_b,
            bm25_idf=self.bm25_idf,
            candidate_k=self.candidate_k,
            rrf_k=self.rrf_k,
        ).candidate_limit(self.k)

    def to_dict(self) -> dict[str, object]:
        """Build nested experiment provenance for artifacts and baselines.

        Returns
        -------
        dict[str, object]
            JSON-compatible chunking, retrieval, embedding, and measurement metadata.

        Notes
        -----
        Each call creates a new nested mapping. BM25 parameters appear only for an arm
        that actually uses the BM25 lexical ranker, and the paid-API flag is derived
        from ``embedding_provider``.
        """
        retrieval: dict[str, object] = {
            "strategy": self.strategy,
            "lexical_ranker": self.lexical_ranker,
            "k": self.k,
            "candidate_k": self.candidate_k,
            "rrf_k": self.rrf_k,
        }
        if self.lexical_ranker == "bm25":
            retrieval["bm25"] = {
                "k1": self.bm25_k1,
                "b": self.bm25_b,
                "idf": self.bm25_idf,
            }
        return {
            "name": self.name,
            "chunking": {
                "strategy": "structure-aware",
                "target_tokens": self.target_tokens,
                "golden_identity": "source-sha256-and-half-open-span",
            },
            "retrieval": retrieval,
            "embedding": {
                "provider": self.embedding_provider,
                "dimensions": self.dimensions,
            },
            "measurement": {
                "environment": "isolated-temporary-postgresql",
                "corpus_preparation": "parse-once-per-run",
                "paid_api_calls": self.embedding_provider != "deterministic",
                "populated_corpus_embeddings_modified": False,
            },
        }


@dataclass(frozen=True, slots=True)
class AblationOutcome:
    """Associate one experiment arm with its evaluation and artifact path.

    Notes
    -----
    This record does not validate cross-field consistency or path existence.
    ``run_ablation`` verifies the evaluation provenance and writes the artifact before
    constructing an outcome.
    """

    config: ExperimentConfig
    evaluation: RetrievalEvaluation
    artifact_path: Path


@dataclass(frozen=True, slots=True)
class AblationReport:
    """Preserve experiment outcomes for deterministic comparison rendering.

    Notes
    -----
    Direct construction preserves the supplied tuple order. ``run_ablation`` is the
    boundary that sorts outcomes before creating a report.
    """

    outcomes: tuple[AblationOutcome, ...]

    def comparison_markdown(self) -> str:
        """Render in-memory metrics with links to their raw artifacts.

        Returns
        -------
        str
            Markdown table containing quality metrics, latency, and artifact links.

        Notes
        -----
        Rows retain ``outcomes`` order and artifact paths are rendered as stored; this
        method does not sort outcomes or verify that their paths exist.
        """
        return markdown_table(
            [
                "Config",
                "Chunk target (tokens)",
                "Retrieval",
                "Lexical ranker",
                "Recall@k",
                "Hit rate@k",
                "MRR",
                "P95 ms",
                "Raw",
            ],
            ["left", "right", "left", "left", "right", "right", "right", "right", "left"],
            [
                [
                    outcome.config.name,
                    str(outcome.config.target_tokens),
                    outcome.config.strategy,
                    outcome.config.lexical_ranker or "-",
                    f"{outcome.evaluation.score.recall_at_k:.6f}",
                    f"{outcome.evaluation.score.hit_rate_at_k:.6f}",
                    f"{outcome.evaluation.score.mrr:.6f}",
                    f"{outcome.evaluation.latency.p95_ms:.3f}",
                    f"[{outcome.artifact_path.name}]({outcome.artifact_path.as_posix()})",
                ]
                for outcome in self.outcomes
            ],
        )


def experiment_matrix(
    *,
    target_tokens: Sequence[int] = (1024, 2048),
    strategies: Sequence[RetrievalStrategy] = ("lexical", "vector", "hybrid"),
    lexical_rankers: Sequence[LexicalRanker] = LEXICAL_RANKERS,
    bm25_k1: float = DEFAULT_BM25_K1,
    bm25_b: float = DEFAULT_BM25_B,
    bm25_idf: BM25Idf = DEFAULT_BM25_IDF,
    embedding_provider: str = "deterministic",
    dimensions: int = 384,
    k: int = 5,
    candidate_k: int = 20,
    rrf_k: int = DEFAULT_RRF_K,
) -> tuple[ExperimentConfig, ...]:
    """Build the sorted chunking-by-retrieval-by-ranker matrix.

    Parameters
    ----------
    target_tokens : Sequence[int]
        Unique token-count targets to evaluate.
    strategies : Sequence[RetrievalStrategy]
        Unique retrieval paths to cross with each chunk target.
    lexical_rankers : Sequence[LexicalRanker]
        Unique rankers crossed only with strategies that perform lexical retrieval.
    bm25_k1 : float
        Term-frequency saturation parameter recorded on BM25 arms.
    bm25_b : float
        Document-length normalization parameter recorded on BM25 arms.
    bm25_idf : BM25Idf
        Inverse-document-frequency formula recorded on BM25 arms.
    embedding_provider : str
        Nonblank provider identifier recorded for every arm.
    dimensions : int
        Positive embedding dimensionality recorded for every arm.
    k : int
        Positive final hit count requested from retrieval.
    candidate_k : int
        Candidate count, which must be at least ``k``.
    rrf_k : int
        Positive reciprocal-rank-fusion constant.

    Returns
    -------
    tuple[ExperimentConfig, ...]
        Validated arms in the canonical comparison order.

    Raises
    ------
    ValueError
        If an axis is empty or duplicated, a lexical strategy has no ranker, or any
        generated arm violates ``ExperimentConfig`` invariants.
    KeyError
        If a supplied lexical ranker has no registered filename slug.

    Notes
    -----
    The ranker axis crosses only strategies that execute a lexical query. Vector
    retrieval therefore contributes one arm per chunk target regardless of the
    number of lexical rankers.
    """
    if not target_tokens or not strategies:
        raise ValueError("experiment matrix axes must not be empty")
    if len(set(target_tokens)) != len(target_tokens):
        raise ValueError("chunk targets must be unique")
    if len(set(strategies)) != len(strategies):
        raise ValueError("retrieval strategies must be unique")
    lexical_strategies = [strategy for strategy in strategies if strategy != "vector"]
    if lexical_strategies:
        if not lexical_rankers:
            raise ValueError(f"{lexical_strategies[0]} retrieval requires a lexical ranker")
        if len(set(lexical_rankers)) != len(lexical_rankers):
            raise ValueError("lexical rankers must be unique")

    configs: list[ExperimentConfig] = []
    for target in target_tokens:
        for strategy in strategies:
            rankers: tuple[LexicalRanker | None, ...] = (
                (None,) if strategy == "vector" else tuple(lexical_rankers)
            )

            for ranker in rankers:
                configs.append(
                    ExperimentConfig(
                        name=experiment_name(target, strategy, ranker),
                        target_tokens=target,
                        strategy=strategy,
                        embedding_provider=embedding_provider,
                        dimensions=dimensions,
                        lexical_ranker=ranker,
                        bm25_k1=bm25_k1 if ranker == "bm25" else None,
                        bm25_b=bm25_b if ranker == "bm25" else None,
                        bm25_idf=bm25_idf if ranker == "bm25" else None,
                        k=k,
                        candidate_k=candidate_k,
                        rrf_k=rrf_k,
                    )
                )
    return tuple(sorted(configs, key=sort_key))


async def run_ablation(
    configs: Sequence[ExperimentConfig],
    evaluator: ExperimentEvaluator,
    *,
    artifact_dir: str | Path,
    recorded_at: datetime,
) -> AblationReport:
    """Evaluate unique arms sequentially and persist their raw artifacts.

    Parameters
    ----------
    configs : Sequence[ExperimentConfig]
        Nonempty collection of arms with unique names.
    evaluator : ExperimentEvaluator
        Asynchronous evaluator that returns one result with matching config provenance.
    artifact_dir : str | Path
        Directory in which raw JSON artifacts are written.
    recorded_at : datetime
        Timezone-aware recording time used in every artifact filename.

    Returns
    -------
    AblationReport
        Outcomes ordered by the canonical experiment sort key.

    Raises
    ------
    ValueError
        If configs are empty or names repeat, ``recorded_at`` is naive, or an
        evaluation's config does not carry its arm provenance. Extra keys, such as
        the corpus and golden identity the admin surface records, are allowed.
    OSError
        If an artifact directory or file cannot be created or written.

    Notes
    -----
    Arms are awaited one at a time in canonical order and each artifact is written
    immediately. Evaluator and serialization failures propagate without rollback, so
    artifacts completed before a later failure remain on disk. Timestamp validation
    occurs after the corresponding evaluator returns, when its filename is built.
    """
    if not configs:
        raise ValueError("ablation configs must not be empty")
    names = [config.name for config in configs]
    if len(names) != len(set(names)):
        raise ValueError("ablation config names must be unique")
    ordered = sorted(configs, key=sort_key)
    directory = Path(artifact_dir)
    outcomes: list[AblationOutcome] = []
    for config in ordered:
        evaluation = await evaluator(config)
        provenance = config.to_dict()
        missing = object()
        if any(evaluation.config.get(key, missing) != value for key, value in provenance.items()):
            raise ValueError(f"evaluation config does not carry arm {config.name}")

        path = directory / artifact_filename(recorded_at, config.name)
        write_evaluation_artifact(path, evaluation)
        outcomes.append(
            AblationOutcome(
                config=config,
                evaluation=evaluation,
                artifact_path=path,
            )
        )
    return AblationReport(outcomes=tuple(outcomes))


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
