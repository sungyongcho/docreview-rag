"""The cross-lingual parity command: corpus profiles, arguments, and the isolated run."""

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, get_settings
from app.evals.cli import positive_int, unit_ratio
from app.evals.execution.evaluator import PersistedEvaluation, persist_evaluation
from app.evals.execution.retrievers import LEXICAL_RANKERS, RETRIEVAL_STRATEGIES, make_retriever
from app.evals.experiments.corpus import build_chunking_batch, temporary_corpus_session
from app.evals.experiments.crosslingual import (
    CROSSLINGUAL_SUITE,
    HANDLING_CHOICES,
    LANGUAGE_CHOICES,
    PROVIDER_CHOICES,
    CrosslingualArm,
    LanguageRun,
    TranslationLog,
    embedding_identity,
    run_arm,
)
from app.evals.experiments.diagnostics import (
    DEFAULT_MIN_RECALL_RATIO,
    LANGUAGE_REGRESSION_TOLERANCES,
    LexicalCoverage,
    arm_comparison_markdown,
    gate_verdict,
    gateable_matrix,
    gated_assessments,
    language_category_markdown,
    lexical_candidate_coverage,
    parity_markdown,
    parity_pairs,
    twin_query_alignment,
)
from app.evals.golden.bilingual import KO_GOLDEN_PATH, load_bilingual_suites
from app.evals.golden.loading import DEFAULT_GOLDEN_PATH
from app.ingestion.parsing.registry import registry_for
from app.ingestion.pipeline import DEFAULT_MANIFEST_NAME, embedding_chunk_config
from app.ingestion.progress import OperationProgress, OperationProgressCallback, operation_bar
from app.ingestion.tokens import TARGET_INPUT_TOKENS
from app.llm.completion import LLMProvider
from app.llm.schemas import ProviderBudget
from app.retrieval.embedding.provider import get_embedding_provider
from app.retrieval.ranking.fusion import DEFAULT_RRF_K
from app.retrieval.types import RetrievalFilters

DART_CROSSLINGUAL_SUITE: Final[str] = "m10-dart-crosslingual-v1"

DART_GOLDEN_PATH: Final[Path] = DEFAULT_GOLDEN_PATH.parent / "dart_retrieval.json"
DART_KO_GOLDEN_PATH: Final[Path] = DEFAULT_GOLDEN_PATH.parent / "dart_retrieval_ko.json"


@dataclass(frozen=True, slots=True)
class CorpusProfile:
    """One measured corpus per command run.

    A profile binds everything that changes with the corpus — suite, golden twins,
    and manifest. The registry supplies the corpus language; the shared ingestion
    contract supplies the token target for every corpus.
    """

    registry: str
    suite: str
    golden: Path
    ko_golden: Path
    manifest_name: str
    selection_id: str

    @property
    def language(self) -> str:
        """Return the corpus language the registry publishes in."""
        return registry_for(self.registry).language

    @property
    def target_tokens(self) -> int:
        """Return the shared ingestion token target."""
        return TARGET_INPUT_TOKENS


CORPUS_PROFILES: Final[dict[str, CorpusProfile]] = {
    "edgar": CorpusProfile(
        registry="sec",
        suite=CROSSLINGUAL_SUITE,
        golden=DEFAULT_GOLDEN_PATH,
        ko_golden=KO_GOLDEN_PATH,
        manifest_name=DEFAULT_MANIFEST_NAME,
        selection_id="sec-evaluation",
    ),
    "dart": CorpusProfile(
        registry="dart",
        suite=DART_CROSSLINGUAL_SUITE,
        golden=DART_GOLDEN_PATH,
        ko_golden=DART_KO_GOLDEN_PATH,
        manifest_name=DEFAULT_MANIFEST_NAME,
        selection_id="dart-evaluation",
    ),
}


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the cross-lingual measurement command."""
    parser = argparse.ArgumentParser(
        description="Measure retrieval on Korean and English twin queries and gate parity."
    )
    parser.add_argument(
        "--corpus",
        choices=tuple(CORPUS_PROFILES),
        default="edgar",
        help="Corpus cell to measure; suite, goldens, manifest, and chunk target follow it.",
    )
    parser.add_argument("--suite", default=None)
    parser.add_argument("--golden", type=Path, default=None)
    parser.add_argument("--ko-golden", type=Path, default=None)
    parser.add_argument("--artifact-dir", type=Path, default=Path("data/eval_runs"))
    parser.add_argument("--provider", choices=PROVIDER_CHOICES, default="deterministic")
    parser.add_argument(
        "--languages",
        choices=LANGUAGE_CHOICES,
        nargs="+",
        default=list(LANGUAGE_CHOICES),
    )
    parser.add_argument(
        "--strategies",
        choices=RETRIEVAL_STRATEGIES,
        nargs="+",
        default=list(RETRIEVAL_STRATEGIES),
    )
    parser.add_argument(
        "--handling",
        choices=HANDLING_CHOICES,
        nargs="+",
        default=["direct"],
        help="Query-path variants to cross with every hybrid arm.",
    )
    parser.add_argument("--lexical-ranker", choices=LEXICAL_RANKERS, default="ts_rank_cd")
    parser.add_argument("--translator-model", default="gpt-5.6-luna")
    parser.add_argument("-k", type=positive_int, default=5)
    parser.add_argument("--candidate-k", type=positive_int, default=20)
    parser.add_argument("--rrf-k", type=positive_int, default=DEFAULT_RRF_K)
    parser.add_argument("--min-recall-ratio", type=unit_ratio, default=DEFAULT_MIN_RECALL_RATIO)
    parser.add_argument("--persist-results", action="store_true")
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Exit nonzero when a shipping arm fails the ko/en recall parity floor.",
    )
    parser.add_argument(
        "--require-baseline",
        action="store_true",
        help="Fail the gate when a persisted arm has no comparable stored baseline.",
    )
    parsed = parser.parse_args(argv)
    # Rejected here rather than inside CrosslingualArm, so an inconsistent depth cannot
    # fail after the provider is built and both golden suites are loaded.
    if parsed.candidate_k < parsed.k:
        parser.error("--candidate-k must be at least -k")
    profile = CORPUS_PROFILES[parsed.corpus]
    if parsed.suite is None:
        parsed.suite = profile.suite
    if parsed.golden is None:
        parsed.golden = profile.golden
    if parsed.ko_golden is None:
        parsed.ko_golden = profile.ko_golden
    return parsed


def build_arms(
    args: argparse.Namespace,
    embedding_model: str,
    *,
    target_tokens: int,
    settings: Settings | None = None,
) -> tuple[CrosslingualArm, ...]:
    """Expand parsed axes into sorted arms with explicit BM25 provenance."""
    resolved = settings if settings is not None else get_settings()
    profile = CORPUS_PROFILES[args.corpus]
    languages = list(dict.fromkeys(args.languages))
    strategies = list(dict.fromkeys(args.strategies))
    handlings = list(dict.fromkeys(args.handling))
    arms: list[CrosslingualArm] = []
    for strategy in strategies:
        ranker = None if strategy == "vector" else args.lexical_ranker
        bm25 = (
            (resolved.bm25_k1, resolved.bm25_b, resolved.bm25_idf)
            if ranker == "bm25"
            else (None, None, None)
        )
        for handling in handlings:
            if handling != "direct" and strategy != "hybrid":
                continue
            for language in languages:
                arms.append(
                    CrosslingualArm(
                        embedding_provider=args.provider,
                        embedding_model=embedding_model,
                        strategy=strategy,
                        language=language,
                        corpus_registry=profile.registry,
                        handling=handling,
                        lexical_ranker=ranker,
                        bm25_k1=bm25[0],
                        bm25_b=bm25[1],
                        bm25_idf=bm25[2],
                        translator_model=(
                            args.translator_model if handling == "translated" else None
                        ),
                        target_tokens=target_tokens,
                        k=args.k,
                        candidate_k=args.candidate_k,
                        rrf_k=args.rrf_k,
                    )
                )
    if not arms:
        raise ValueError("the requested matrix contains no arms")
    return tuple(sorted(arms, key=lambda arm: arm.sort_key))


TRANSLATION_MAX_INPUT_TOKENS: Final[int] = 2_000
TRANSLATION_MAX_OUTPUT_TOKENS: Final[int] = 400


def translation_boundary(model_name: str, settings: Settings) -> tuple[LLMProvider, ProviderBudget]:
    """Build the paid translation provider and the budget one query may spend.

    The SDK is imported here rather than at module scope so a matrix with no translated
    arm never loads it. The key travels through ``Settings`` exactly as it does for the
    embedding provider, which keeps a configured-but-unexported ``.env`` key working and
    keeps every paid boundary in this command sourced the same way.
    """
    from app.llm.openai import OpenAILLMProvider
    from app.openai_models import resolve_openai_model

    selection = resolve_openai_model("translation", model_name)
    provider = OpenAILLMProvider(
        model_name=selection.model,
        role="translation",
        api_key=(settings.openai_api_key.get_secret_value() if settings.openai_api_key else None),
    )
    budget = ProviderBudget(
        max_input_tokens=TRANSLATION_MAX_INPUT_TOKENS,
        max_output_tokens=TRANSLATION_MAX_OUTPUT_TOKENS,
        max_cost_usd=Decimal("0.05"),
        pricing=selection.pricing,
    )
    return provider, budget


async def _run_cli(
    args: argparse.Namespace,
    *,
    on_progress: OperationProgressCallback | None = None,
) -> dict[str, Any]:
    """Measure the requested matrix in one isolated corpus and assess parity.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command carrying the provider, matrix axes, artifact directory, and
        gate selection.

    Returns
    -------
    dict[str, Any]
        Rendered tables plus the JSON-ready diagnostics, artifacts, persistence rows,
        and gate verdict printed by ``main``.

    Raises
    ------
    RuntimeError
        If ``--gate`` is requested for a matrix that measured no hybrid arm with
        routed or translated handling in both languages.
    """
    from app.db.bootstrap import bootstrap_schema

    settings_provider, embedding_model = embedding_identity(args.provider, get_settings())
    settings = get_settings().model_copy(
        update={"embedding_provider": settings_provider, "sbert_model": embedding_model}
        if settings_provider == "sbert"
        else {"embedding_provider": settings_provider}
    )
    profile = CORPUS_PROFILES[args.corpus]
    requested_arms = build_arms(
        args, embedding_model, target_tokens=profile.target_tokens, settings=settings
    )
    if args.gate and not gateable_matrix(requested_arms):
        raise ValueError(
            "--gate requires a hybrid arm with routed or translated handling in both languages"
        )
    provider = get_embedding_provider(settings)
    manifest_path = settings.corpus_dir / profile.manifest_name
    suite = load_bilingual_suites(
        args.golden, args.ko_golden, manifest_path=manifest_path, selection_id=profile.selection_id
    )
    target_tokens = embedding_chunk_config(
        provider, target_tokens=profile.target_tokens
    ).target_tokens
    arms = build_arms(args, embedding_model, target_tokens=target_tokens, settings=settings)
    recorded_at = datetime.now(UTC)

    llm_provider = None
    provider_budget = None
    if any(arm.handling == "translated" for arm in arms):
        llm_provider, provider_budget = translation_boundary(args.translator_model, settings)

    if on_progress is not None:
        on_progress(OperationProgress("alignment", 0, 1, "Comparing bilingual query twins"))
    alignment = await twin_query_alignment(provider, suite, provider_name=args.provider)
    if on_progress is not None:
        on_progress(OperationProgress("alignment", 1, 1, "Query twins compared"))
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    runs: list[LanguageRun] = []
    coverage: list[LexicalCoverage] = []
    translations = TranslationLog()
    try:
        batch = build_chunking_batch(
            target_tokens,
            provider=provider,
            settings=settings,
            manifest_name=profile.manifest_name,
            selection_id=profile.selection_id,
            on_progress=on_progress,
        )
        async with temporary_corpus_session(
            engine,
            batch,
            provider,
            target_tokens=target_tokens,
            embedding_provider=args.provider,
            on_progress=on_progress,
        ) as (session, indexing):
            probe_bm25 = args.lexical_ranker == "bm25"
            lexical_probe = make_retriever(
                session,
                strategy="lexical",
                provider=None,
                lexical_ranker=args.lexical_ranker,
                bm25_k1=settings.bm25_k1 if probe_bm25 else None,
                bm25_b=settings.bm25_b if probe_bm25 else None,
                bm25_idf=settings.bm25_idf if probe_bm25 else None,
                candidate_k=args.candidate_k,
                # The probe pins the corpus language exactly as the measured arms
                # do: the filter selects the lexical tokenization the rows were
                # indexed with.
                filters=RetrievalFilters(languages=(profile.language,)),
            )
            for language in dict.fromkeys(args.languages):
                coverage.append(
                    await lexical_candidate_coverage(
                        lexical_probe,
                        suite.cases(language),
                        language=language,
                        candidate_k=args.candidate_k,
                    )
                )
            for arm in arms:

                def publish_case(
                    progress: OperationProgress,
                    arm_name: str = arm.name,
                ) -> None:
                    """Name the active cross-lingual arm on each case update."""
                    if on_progress is not None:
                        on_progress(
                            OperationProgress(
                                f"evaluate:{arm_name}",
                                progress.current,
                                progress.total,
                                f"{arm_name} · {progress.message}",
                            )
                        )

                runs.append(
                    await run_arm(
                        session,
                        arm,
                        suite,
                        provider=provider,
                        suite_name=args.suite,
                        artifact_dir=args.artifact_dir,
                        recorded_at=recorded_at,
                        llm_provider=llm_provider,
                        provider_budget=provider_budget,
                        translation_log=translations,
                        **({"on_progress": publish_case} if on_progress is not None else {}),
                    )
                )

        assessments = parity_pairs(runs, min_recall_ratio=args.min_recall_ratio)
        gated = gated_assessments(assessments)

        persisted: list[tuple[CrosslingualArm, PersistedEvaluation]] = []
        if args.persist_results:
            await bootstrap_schema(engine)
            async with AsyncSession(engine, expire_on_commit=False) as db_session:
                for run in runs:
                    if run.artifact_path is None:
                        continue
                    result = await persist_evaluation(
                        db_session,
                        run.evaluation,
                        raw_artifact_path=run.artifact_path,
                        tolerances=LANGUAGE_REGRESSION_TOLERANCES,
                    )
                    persisted.append((run.arm, result))
                await db_session.commit()

        return {
            "comparison_table": arm_comparison_markdown(runs),
            "category_table": language_category_markdown(runs),
            "parity_tables": [parity_markdown(assessment) for _, assessment in assessments],
            "twin_alignment": {
                "provider": alignment.provider,
                "pair_count": alignment.pair_count,
                "mean_cosine": alignment.mean_cosine,
                "min_cosine": alignment.min_cosine,
                "max_cosine": alignment.max_cosine,
            },
            "lexical_coverage": [asdict(item) for item in coverage],
            "indexing": asdict(indexing),
            "translations": translations.payload(),
            "artifacts": [str(run.artifact_path) for run in runs if run.artifact_path],
            # ``to_dict`` rather than ``asdict``: the regression verdict lives on
            # properties, so ``asdict`` would report a comparison with no decision.
            # The arm name is carried alongside it, so a failing verdict names the
            # slice that failed instead of leaving a positional join to the reader.
            "persisted": [{"arm": arm.name} | result.to_dict() for arm, result in persisted],
            "gate": gate_verdict(
                gated,
                persisted,
                enabled=bool(args.gate),
                require_baseline=bool(args.require_baseline),
            ),
        }
    finally:
        await engine.dispose()


def main() -> None:
    """Run the cross-lingual measurement command and honour the parity gate."""
    args = arguments()
    with operation_bar("Cross-lingual evaluation") as progress:
        result = asyncio.run(_run_cli(args, on_progress=progress))
    print(result["comparison_table"])
    print()
    print(result["category_table"])
    for table in result["parity_tables"]:
        print()
        print(table)
    print()
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"comparison_table", "category_table", "parity_tables"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.gate and not result["gate"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
