"""Cross-lingual retrieval arms, query-path diagnostics, and the parity command."""

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
import json
import math
from pathlib import Path
import re
from typing import Any, Final, Literal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import LexicalRanker, Settings, get_settings
from app.evals.bilingual import KO_GOLDEN_PATH, BilingualSuite, load_bilingual_suites
from app.evals.breakdown import GroupScore, breakdown_by_category
from app.evals.loader import DEFAULT_GOLDEN_PATH
from app.evals.parity import (
    DEFAULT_MIN_RECALL_RATIO,
    ParityAssessment,
    assess_parity,
    parity_markdown,
)
from app.evals.retrieval_eval import (
    RetrievalEvaluation,
    RetrievalStrategy,
    Retriever,
    build_chunking_batch,
    evaluate_retriever,
    make_retriever,
    persist_evaluation,
    temporary_corpus_session,
    write_evaluation_artifact,
)
from app.evals.types import GoldenCase
from app.llm import LLMProvider, ProviderBudget
from app.retrieval.embeddings import EmbeddingProvider, get_embedding_provider
from app.retrieval.hybrid import DEFAULT_RRF_K
from app.retrieval.language import QueryLanguage
from app.retrieval.sbert import MULTILINGUAL_SBERT_MODEL
from app.retrieval.service import retrieve
from app.retrieval.translate import QueryTranslation, translate_query
from app.retrieval.types import ChunkHit, RetrievalFilters

QueryHandling = Literal["direct", "routed", "translated"]
ProviderChoice = Literal["deterministic", "openai", "sbert", "sbert-multi"]

CROSSLINGUAL_SUITE: Final[str] = "m8-crosslingual-v1"
# The M3 ablation's winning chunk target. Chunking is held fixed so the only axes in
# this matrix are the ones the module is about: embedding space, retrieval strategy,
# query language, and query handling.
CROSSLINGUAL_TARGET_TEXT_CHARS: Final[int] = 1200
DETERMINISTIC_EMBEDDING_MODEL: Final[str] = "token-hash-384"
PROVIDER_CHOICES: Final[tuple[ProviderChoice, ...]] = (
    "deterministic",
    "openai",
    "sbert",
    "sbert-multi",
)
LANGUAGE_CHOICES: Final[tuple[QueryLanguage, ...]] = ("en", "ko")
HANDLING_CHOICES: Final[tuple[QueryHandling, ...]] = ("direct", "routed", "translated")
ARM_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RANKER_SLUG: Final[dict[str, str]] = {"ts_rank_cd": "ts-rank-cd", "bm25": "bm25"}
STRATEGY_ORDER: Final[dict[str, int]] = {"lexical": 0, "vector": 1, "hybrid": 2}
HANDLING_ORDER: Final[dict[str, int]] = {"direct": 0, "routed": 1, "translated": 2}
LANGUAGE_ORDER: Final[dict[str, int]] = {"en": 0, "ko": 1}


def embedding_identity(provider: ProviderChoice, settings: Settings) -> tuple[str, str]:
    """Map one CLI provider choice onto the Settings provider and the model name.

    ``sbert-multi`` is not a new provider literal. It is the existing ``sbert``
    provider pointed at the multilingual checkpoint, which is natively 384
    dimensions, so the arm changes the vector space without changing the schema.
    """
    if provider == "deterministic":
        return "deterministic", DETERMINISTIC_EMBEDDING_MODEL
    if provider == "openai":
        return "openai", settings.embedding_model
    if provider == "sbert":
        return "sbert", settings.sbert_model
    if provider == "sbert-multi":
        return "sbert", MULTILINGUAL_SBERT_MODEL
    raise ValueError(f"unsupported embedding provider choice: {provider}")


@dataclass(frozen=True, slots=True)
class CrosslingualArm:
    """One measured cross-lingual retrieval arm and its canonical provenance."""

    embedding_provider: ProviderChoice
    embedding_model: str
    strategy: RetrievalStrategy
    language: QueryLanguage
    handling: QueryHandling = "direct"
    lexical_ranker: LexicalRanker | None = None
    translator_model: str | None = None
    dimensions: int = 384
    target_text_chars: int = CROSSLINGUAL_TARGET_TEXT_CHARS
    k: int = 5
    candidate_k: int = 20
    rrf_k: int = DEFAULT_RRF_K

    def __post_init__(self) -> None:
        """Reject arm shapes whose measured numbers could not be attributed."""
        if self.embedding_provider not in PROVIDER_CHOICES:
            raise ValueError(f"unsupported embedding provider: {self.embedding_provider}")
        if not self.embedding_model.strip():
            raise ValueError("embedding_model must be nonblank")
        if self.strategy not in STRATEGY_ORDER:
            raise ValueError(f"unsupported retrieval strategy: {self.strategy}")
        if self.language not in LANGUAGE_ORDER:
            raise ValueError(f"unsupported query language: {self.language}")
        if self.handling not in HANDLING_ORDER:
            raise ValueError(f"unsupported query handling: {self.handling}")
        if self.strategy == "vector":
            if self.lexical_ranker is not None:
                raise ValueError("vector retrieval must not name a lexical ranker")
        elif self.lexical_ranker not in RANKER_SLUG:
            raise ValueError(f"{self.strategy} retrieval requires an explicit lexical ranker")
        # Routing decides whether to ask the lexical component at all, so it only
        # means something where both components run. A "routed" vector arm would be
        # the direct vector arm under a label claiming a route it never took.
        if self.handling != "direct" and self.strategy != "hybrid":
            raise ValueError(f"{self.handling} handling requires the hybrid strategy")
        if (self.handling == "translated") != (self.translator_model is not None):
            raise ValueError("a translator model is required exactly for translated handling")
        if self.dimensions <= 0 or self.target_text_chars <= 0:
            raise ValueError("dimensions and target_text_chars must be positive")
        if self.k <= 0 or self.candidate_k < self.k or self.rrf_k <= 0:
            raise ValueError("k, candidate_k, and rrf_k are inconsistent")
        if ARM_NAME.fullmatch(self.name) is None:
            raise ValueError("arm name must be lowercase kebab-case")

    @property
    def name(self) -> str:
        """Return the kebab arm name, which must survive being used as a filename."""
        parts = ["xling", self.embedding_provider, self.strategy]
        if self.lexical_ranker is not None:
            parts.append(RANKER_SLUG[self.lexical_ranker])
        if self.handling != "direct":
            parts.append(self.handling)
        parts.append(self.language)
        return "-".join(parts)

    @property
    def sort_key(self) -> tuple[int, int, int, str]:
        """Order arms by retrieval path, then handling, then language."""
        return (
            STRATEGY_ORDER[self.strategy],
            HANDLING_ORDER[self.handling],
            LANGUAGE_ORDER[self.language],
            self.name,
        )

    def paired_with(self, language: QueryLanguage) -> CrosslingualArm:
        """Return the same arm measured in the other query language."""
        return CrosslingualArm(**{**asdict(self), "language": language})

    def to_config(self) -> dict[str, Any]:
        """Return the canonical config dict consumed by artifacts and baselines.

        ``embedding.model`` and ``query.language`` carry the whole weight of every
        regression number in this module: ``latest_comparable_baseline`` matches on
        the serialized config, so an arm that omitted either would be compared
        against a run in a different vector space or a different language and the
        comparison would look valid.

        ``retrieval.reranker`` is recorded as null rather than left out. The M2.6
        cross-encoder is an English-trained model, so it stays off in every arm here;
        writing that down makes a future run that switches it on visibly incomparable
        instead of quietly contaminating the Korean slice.
        """
        translator = (
            None
            if self.translator_model is None
            else {"provider": "openai", "model": self.translator_model}
        )
        return {
            "name": self.name,
            "chunking": {
                "strategy": "structure-aware",
                "target_text_chars": self.target_text_chars,
                "golden_identity": "source-sha256-and-half-open-span",
            },
            "retrieval": {
                "strategy": self.strategy,
                "lexical_ranker": self.lexical_ranker,
                "reranker": None,
                "k": self.k,
                "candidate_k": self.candidate_k,
                "rrf_k": self.rrf_k,
            },
            "embedding": {
                "provider": self.embedding_provider,
                "model": self.embedding_model,
                "dimensions": self.dimensions,
            },
            "query": {
                "language": self.language,
                "handling": self.handling,
                "translator": translator,
            },
            "measurement": {
                "environment": "isolated-temporary-postgresql",
                "paid_api_calls": self.embedding_provider == "openai"
                or self.handling == "translated",
                "populated_corpus_embeddings_modified": False,
            },
        }


@dataclass(frozen=True, slots=True)
class TwinCosine:
    """One twin pair's query-vector cosine under a single embedding provider."""

    case_id: str
    cosine: float


@dataclass(frozen=True, slots=True)
class TwinAlignment:
    """How closely one embedding space places Korean queries beside their twins."""

    provider: str
    pair_count: int
    mean_cosine: float
    min_cosine: float
    max_cosine: float
    pairs: tuple[TwinCosine, ...]


@dataclass(frozen=True, slots=True)
class LexicalCoverage:
    """How often the English lexical index returns nothing for one language."""

    language: QueryLanguage
    case_count: int
    zero_candidate_cases: int
    zero_candidate_rate: float
    mean_candidate_count: float
    zero_candidate_case_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LanguageRun:
    """One evaluated arm together with its per-category slice."""

    arm: CrosslingualArm
    evaluation: RetrievalEvaluation
    categories: tuple[GroupScore, ...]
    artifact_path: Path | None = None


@dataclass(slots=True)
class TranslationLog:
    """Ordered record of every translation a measured arm actually performed.

    A translation arm is the one non-deterministic part of this matrix. Recording
    what each query became is what lets a reported number be re-read later; without
    it the arm reports a score for queries nobody can reconstruct.
    """

    entries: list[tuple[str, QueryTranslation]] = field(default_factory=list)

    def record(self, original: str, translation: QueryTranslation) -> None:
        """Append one translated query in call order."""
        self.entries.append((original, translation))

    def payload(self) -> list[dict[str, str]]:
        """Return a JSON-ready record for the run artifact."""
        return [
            {
                "original": original,
                "translated": translation.translated_query,
                "source_language": translation.source_language,
            }
            for original, translation in self.entries
        ]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Return the cosine of two equal-length nonzero vectors."""
    if len(left) != len(right):
        raise ValueError("cosine requires vectors of equal length")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("cosine is undefined for a zero vector")
    return dot / (left_norm * right_norm)


async def twin_query_alignment(
    provider: EmbeddingProvider,
    suite: BilingualSuite,
    *,
    provider_name: str = "unknown",
) -> TwinAlignment:
    """Measure how near each Korean query sits to its English twin, before any corpus.

    This is the cheapest honest answer to "does this embedding space recognize both
    languages at all": no database, no chunks, no retrieval. A token-hashing provider
    shares almost no tokens across the pair and lands near zero — near, not at, since
    384 hashed dimensions collide. A multilingual model places the twins close, and
    that difference is visible before a single arm is indexed.
    """
    pairs = suite.pairs()
    if not pairs:
        raise ValueError("twin alignment requires at least one pair")
    en_vectors = await provider.embed_documents([english.question for english, _ in pairs])
    ko_vectors = await provider.embed_documents([korean.question for _, korean in pairs])
    measured = tuple(
        TwinCosine(case_id=english.id, cosine=_cosine(en_vector, ko_vector))
        for (english, _), en_vector, ko_vector in zip(pairs, en_vectors, ko_vectors, strict=True)
    )
    cosines = [item.cosine for item in measured]
    return TwinAlignment(
        provider=provider_name,
        pair_count=len(measured),
        mean_cosine=sum(cosines) / len(cosines),
        min_cosine=min(cosines),
        max_cosine=max(cosines),
        pairs=measured,
    )


async def lexical_candidate_coverage(
    retriever: Retriever,
    cases: Sequence[GoldenCase],
    *,
    language: QueryLanguage,
    candidate_k: int = 20,
) -> LexicalCoverage:
    """Count how many questions the lexical arm answers with nothing at all.

    The retriever is injected rather than built from a session here, so the
    diagnostic is exercised offline against a scripted lexical arm and used in the
    measured run against ``make_retriever(session, strategy="lexical", ...)``.

    The rate is measured, not assumed. Korean questions about this corpus still carry
    Latin tokens — tickers, ``7nm``, ``G4ad`` — and the English tsquery can match
    those, so the collapse is partial in a way only the number shows.
    """
    if not cases:
        raise ValueError("lexical coverage requires at least one case")
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    empty: list[str] = []
    total = 0
    for case in sorted(cases, key=lambda item: item.id):
        hits = await retriever(case.question, candidate_k)
        total += len(hits)
        if not hits:
            empty.append(case.id)
    return LexicalCoverage(
        language=language,
        case_count=len(cases),
        zero_candidate_cases=len(empty),
        zero_candidate_rate=len(empty) / len(cases),
        mean_candidate_count=total / len(cases),
        zero_candidate_case_ids=tuple(empty),
    )


def category_breakdown(evaluation: RetrievalEvaluation) -> tuple[GroupScore, ...]:
    """Slice one evaluation by golden category through the unmodified breakdown."""
    cases = [case.golden for case in evaluation.cases]
    scores = [case.score for case in evaluation.cases if case.score is not None]
    return breakdown_by_category(cases, scores)


def arm_comparison_markdown(runs: Sequence[LanguageRun]) -> str:
    """Render one row per measured arm in deterministic arm order."""
    if not runs:
        raise ValueError("comparison requires at least one run")
    lines = [
        "| Arm | Strategy | Handling | Language | Cases | Recall@k | Hit rate@k | MRR | P95 ms |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for run in sorted(runs, key=lambda item: item.arm.sort_key):
        score = run.evaluation.score
        lines.append(
            f"| {run.arm.name} | {run.arm.strategy} | {run.arm.handling} | "
            f"{run.arm.language} | {score.case_count} | {score.recall_at_k:.6f} | "
            f"{score.hit_rate_at_k:.6f} | {score.mrr:.6f} | "
            f"{run.evaluation.latency.p95_ms:.3f} |"
        )
    return "\n".join(lines)


def language_category_markdown(runs: Sequence[LanguageRun]) -> str:
    """Join the per-category slices of every run into one language-aware table.

    Language is not a breakdown dimension inside ``breakdown.py``; each language is a
    separate run of the unmodified harness, and the two are joined here at render
    time. That keeps ``GroupScore`` and the loader's span-identity rule untouched, and
    it is the same move M9.5 made when it sliced decomposition by category.
    """
    if not runs:
        raise ValueError("category table requires at least one run")
    lines = [
        "| Arm | Language | Category | Cases | Recall@k | Hit rate@k | MRR |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for run in sorted(runs, key=lambda item: item.arm.sort_key):
        for group in run.categories:
            lines.append(
                f"| {run.arm.name} | {run.arm.language} | {group.group} | "
                f"{group.case_count} | {group.recall_at_k:.6f} | "
                f"{group.hit_rate_at_k:.6f} | {group.mrr:.6f} |"
            )
    return "\n".join(lines)


def make_crosslingual_retriever(
    session: AsyncSession,
    arm: CrosslingualArm,
    *,
    provider: EmbeddingProvider | None,
    llm_provider: LLMProvider | None = None,
    provider_budget: ProviderBudget | None = None,
    translation_log: TranslationLog | None = None,
    filters: RetrievalFilters | None = None,
) -> Retriever:
    """Bind one arm's query handling on top of the unmodified M3 retriever factory.

    Every handling value is a wrapper, never a fork of the harness: ``direct`` is
    ``make_retriever`` itself, ``routed`` is the same production ``retrieve`` call
    with language routing switched on, and ``translated`` rewrites the query before
    handing it to the direct arm. The comparison is therefore between query paths,
    not between evaluation code paths.
    """
    if arm.handling == "direct":
        return make_retriever(
            session,
            strategy=arm.strategy,
            provider=provider,
            lexical_ranker=arm.lexical_ranker,
            candidate_k=arm.candidate_k,
            rrf_k=arm.rrf_k,
            filters=filters,
        )

    if arm.handling == "routed":

        async def routed(query: str, k: int) -> Sequence[ChunkHit]:
            result = await retrieve(
                session,
                query,
                provider=provider,
                k=k,
                candidate_k=arm.candidate_k,
                filters=filters,
                rrf_k=arm.rrf_k,
                route_by_language=True,
                lexical_ranker=arm.lexical_ranker,
            )
            return result.hits

        return routed

    if llm_provider is None or provider_budget is None:
        raise ValueError("translated handling requires an LLM provider and a budget")
    inner = make_retriever(
        session,
        strategy=arm.strategy,
        provider=provider,
        lexical_ranker=arm.lexical_ranker,
        candidate_k=arm.candidate_k,
        rrf_k=arm.rrf_k,
        filters=filters,
    )

    async def translated(query: str, k: int) -> Sequence[ChunkHit]:
        translation = await translate_query(
            query,
            llm_provider=llm_provider,
            provider_budget=provider_budget,
        )
        if translation_log is not None:
            translation_log.record(query, translation)
        return await inner(translation.translated_query, k)

    return translated


def artifact_filename(recorded_at: datetime, arm: CrosslingualArm) -> str:
    """Return a UTC timestamped stable artifact filename for one arm."""
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    timestamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{arm.name}.json"


async def run_arm(
    session: AsyncSession,
    arm: CrosslingualArm,
    suite: BilingualSuite,
    *,
    provider: EmbeddingProvider | None,
    artifact_dir: str | Path | None = None,
    recorded_at: datetime | None = None,
    llm_provider: LLMProvider | None = None,
    provider_budget: ProviderBudget | None = None,
    translation_log: TranslationLog | None = None,
) -> LanguageRun:
    """Evaluate one arm on its own language slice and optionally write its artifact.

    The arm supplies its config dict straight to ``evaluate_retriever`` instead of
    going through ``run_ablation``, whose config-equality check would force the M3
    ``ExperimentConfig`` shape and leave no place to record language or handling.
    Everything else — scoring, provenance, latency, artifact schema — is the M3
    harness untouched.
    """
    moment = recorded_at or datetime.now(UTC)
    retriever = make_crosslingual_retriever(
        session,
        arm,
        provider=provider,
        llm_provider=llm_provider,
        provider_budget=provider_budget,
        translation_log=translation_log,
    )
    evaluation = await evaluate_retriever(
        suite.cases(arm.language),
        retriever,
        suite=CROSSLINGUAL_SUITE,
        config=arm.to_config(),
        k=arm.k,
        recorded_at=moment,
    )
    artifact_path = None
    if artifact_dir is not None:
        artifact_path = write_evaluation_artifact(
            Path(artifact_dir) / artifact_filename(moment, arm),
            evaluation,
        )
    return LanguageRun(
        arm=arm,
        evaluation=evaluation,
        categories=category_breakdown(evaluation),
        artifact_path=artifact_path,
    )


def parity_pairs(
    runs: Sequence[LanguageRun],
    *,
    min_recall_ratio: float = DEFAULT_MIN_RECALL_RATIO,
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Assess parity for every arm that was measured in both languages."""
    by_identity: dict[tuple[str, str, str | None], dict[str, LanguageRun]] = {}
    for run in runs:
        identity = (run.arm.strategy, run.arm.handling, run.arm.lexical_ranker)
        by_identity.setdefault(identity, {})[run.arm.language] = run
    assessments: list[tuple[CrosslingualArm, ParityAssessment]] = []
    ordered = sorted(
        by_identity,
        key=lambda key: (STRATEGY_ORDER[key[0]], HANDLING_ORDER[key[1]], key[2] or ""),
    )
    for identity in ordered:
        slices = by_identity[identity]
        if set(slices) != {"en", "ko"}:
            continue
        assessments.append(
            (
                slices["ko"].arm,
                assess_parity(
                    slices["en"].evaluation,
                    slices["ko"].evaluation,
                    min_recall_ratio=min_recall_ratio,
                ),
            )
        )
    return tuple(assessments)


def gated_assessments(
    assessments: Sequence[tuple[CrosslingualArm, ParityAssessment]],
) -> tuple[tuple[CrosslingualArm, ParityAssessment], ...]:
    """Select the shipping arms whose parity the gate is allowed to judge.

    Only a hybrid arm with language-aware handling can claim parity. The direct arm
    is the "before" measurement — gating it would make the gate report the very
    failure the module was built to expose, and passing it would mean the routing
    change had not been measured at all.
    """
    return tuple(
        (arm, assessment)
        for arm, assessment in assessments
        if arm.strategy == "hybrid" and arm.handling != "direct"
    )


def _positive_int(value: str) -> int:
    """Parse one argparse value that must be a positive integer."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the cross-lingual measurement command."""
    parser = argparse.ArgumentParser(
        description="Measure retrieval on Korean and English twin queries and gate parity."
    )
    parser.add_argument("--suite", default=CROSSLINGUAL_SUITE)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--ko-golden", type=Path, default=KO_GOLDEN_PATH)
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
        choices=("lexical", "vector", "hybrid"),
        nargs="+",
        default=["lexical", "vector", "hybrid"],
    )
    parser.add_argument(
        "--handling",
        choices=HANDLING_CHOICES,
        nargs="+",
        default=["direct"],
        help="Query-path variants to cross with every hybrid arm.",
    )
    parser.add_argument("--lexical-ranker", choices=("ts_rank_cd", "bm25"), default="ts_rank_cd")
    parser.add_argument("--translator-model", default="gpt-4.1-mini")
    parser.add_argument("-k", type=_positive_int, default=5)
    parser.add_argument("--candidate-k", type=_positive_int, default=20)
    parser.add_argument("--rrf-k", type=_positive_int, default=DEFAULT_RRF_K)
    parser.add_argument("--min-recall-ratio", type=float, default=DEFAULT_MIN_RECALL_RATIO)
    parser.add_argument("--persist-results", action="store_true")
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Exit nonzero when a shipping arm fails the ko/en recall parity floor.",
    )
    return parser.parse_args(argv)


def build_arms(args: argparse.Namespace, embedding_model: str) -> tuple[CrosslingualArm, ...]:
    """Expand the parsed command into the sorted, deduplicated arm matrix."""
    languages = list(dict.fromkeys(args.languages))
    strategies = list(dict.fromkeys(args.strategies))
    handlings = list(dict.fromkeys(args.handling))
    arms: list[CrosslingualArm] = []
    for strategy in strategies:
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
                        handling=handling,
                        lexical_ranker=None if strategy == "vector" else args.lexical_ranker,
                        translator_model=(
                            args.translator_model if handling == "translated" else None
                        ),
                        k=args.k,
                        candidate_k=args.candidate_k,
                        rrf_k=args.rrf_k,
                    )
                )
    if not arms:
        raise ValueError("the requested matrix contains no arms")
    return tuple(sorted(arms, key=lambda arm: arm.sort_key))


async def _run_cli(args: argparse.Namespace) -> dict[str, Any]:
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

    Notes
    -----
    The engine is disposed in every exit path, and both the LLM provider and its
    budget are constructed only when the matrix actually contains a translated arm,
    so an unpaid matrix never builds a paid boundary.
    """
    from app.db.bootstrap import bootstrap_schema
    from app.llm import OpenAILLMProvider, TokenPricing

    settings_provider, embedding_model = embedding_identity(args.provider, get_settings())
    settings = get_settings().model_copy(
        update={"embedding_provider": settings_provider, "sbert_model": embedding_model}
        if settings_provider == "sbert"
        else {"embedding_provider": settings_provider}
    )
    provider = get_embedding_provider(settings)
    suite = load_bilingual_suites(args.golden, args.ko_golden)
    arms = build_arms(args, embedding_model)
    recorded_at = datetime.now(UTC)

    llm_provider = None
    provider_budget = None
    if any(arm.handling == "translated" for arm in arms):
        # The key travels through Settings, exactly as it does for the embedding
        # provider. Reading it here rather than letting the SDK fall back to the
        # process environment keeps a configured-but-unexported ``.env`` key working
        # and keeps every paid boundary in this command sourced the same way.
        llm_provider = OpenAILLMProvider(
            model_name=args.translator_model,
            api_key=(
                settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
            ),
        )
        provider_budget = ProviderBudget(
            max_input_tokens=2_000,
            max_output_tokens=400,
            max_cost_usd=Decimal("0.05"),
            pricing=TokenPricing(
                input_per_million_usd=Decimal("0.4"),
                output_per_million_usd=Decimal("1.6"),
            ),
        )

    alignment = await twin_query_alignment(provider, suite, provider_name=args.provider)
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    runs: list[LanguageRun] = []
    coverage: list[LexicalCoverage] = []
    translations = TranslationLog()
    try:
        batch = build_chunking_batch(CROSSLINGUAL_TARGET_TEXT_CHARS, settings=settings)
        async with temporary_corpus_session(
            engine,
            batch,
            provider,
            target_text_chars=CROSSLINGUAL_TARGET_TEXT_CHARS,
            embedding_provider=args.provider,
        ) as (session, indexing):
            lexical_probe = make_retriever(
                session,
                strategy="lexical",
                provider=None,
                lexical_ranker=args.lexical_ranker,
                candidate_k=args.candidate_k,
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
                runs.append(
                    await run_arm(
                        session,
                        arm,
                        suite,
                        provider=provider,
                        artifact_dir=args.artifact_dir,
                        recorded_at=recorded_at,
                        llm_provider=llm_provider,
                        provider_budget=provider_budget,
                        translation_log=translations,
                    )
                )

        assessments = parity_pairs(runs, min_recall_ratio=args.min_recall_ratio)
        gated = gated_assessments(assessments)
        if args.gate and not gated:
            raise RuntimeError(
                "--gate requires a hybrid arm with routed or translated handling in both languages"
            )

        persisted = []
        if args.persist_results:
            await bootstrap_schema(engine)
            async with AsyncSession(engine, expire_on_commit=False) as db_session:
                for run in runs:
                    if run.artifact_path is None:
                        continue
                    persisted.append(
                        await persist_evaluation(
                            db_session,
                            run.evaluation,
                            raw_artifact_path=run.artifact_path,
                        )
                    )
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
            "persisted": [asdict(result) for result in persisted],
            "gate": {
                "enabled": bool(args.gate),
                "arms": [arm.name for arm, _ in gated],
                "passed": all(assessment.passed for _, assessment in gated),
            },
        }
    finally:
        await engine.dispose()


def main() -> None:
    """Run the cross-lingual measurement command and honour the parity gate."""
    args = arguments()
    result = asyncio.run(_run_cli(args))
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
