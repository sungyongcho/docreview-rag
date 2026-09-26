"""Configurable experiment matrix, arm provenance, and artifact orchestration."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1
from app.evals.ablation import ExperimentConfig, experiment_matrix, run_ablation
from app.evals.retrieval_eval import evaluate_retriever
from app.evals.types import EvaluationRetrieval
from tests.evals.support import positive_case, relevant_hit


def retrieval_provenance(config: ExperimentConfig) -> dict[str, object]:
    """Return the nested retrieval mapping of one arm's provenance."""
    retrieval = config.to_dict()["retrieval"]
    assert isinstance(retrieval, dict)
    return retrieval


def test_experiment_matrix_crosses_chunking_retrieval_and_lexical_ranker():
    """Cross every chunk target, retrieval path, and lexical ranker in canonical order."""
    configs = experiment_matrix(
        target_tokens=(2048, 1024),
        strategies=("hybrid", "lexical", "vector"),
        lexical_rankers=("bm25", "ts_rank_cd"),
        embedding_provider="deterministic",
        dimensions=384,
    )

    assert [
        (config.target_tokens, config.strategy, config.lexical_ranker) for config in configs
    ] == [
        (1024, "lexical", "ts_rank_cd"),
        (1024, "lexical", "bm25"),
        (1024, "vector", None),
        (1024, "hybrid", "ts_rank_cd"),
        (1024, "hybrid", "bm25"),
        (2048, "lexical", "ts_rank_cd"),
        (2048, "lexical", "bm25"),
        (2048, "vector", None),
        (2048, "hybrid", "ts_rank_cd"),
        (2048, "hybrid", "bm25"),
    ]


def test_config_provenance_records_the_ranker_and_bm25_defaults_only_where_used():
    """Record per-arm provenance, carrying the project BM25 defaults on BM25 arms only."""
    lexical, bm25, vector = experiment_matrix(
        target_tokens=(1024,),
        strategies=("lexical", "vector"),
    )

    assert lexical.to_dict() == {
        "name": "structure-1024-lexical-ts-rank-cd",
        "chunking": {
            "strategy": "structure-aware",
            "target_tokens": 1024,
            "golden_identity": "source-sha256-and-half-open-span",
        },
        "retrieval": {
            "strategy": "lexical",
            "lexical_ranker": "ts_rank_cd",
            "k": 5,
            "candidate_k": 20,
            "rrf_k": 60,
        },
        "embedding": {"provider": "deterministic", "dimensions": 384},
        "measurement": {
            "environment": "isolated-temporary-postgresql",
            "corpus_preparation": "parse-once-per-run",
            "paid_api_calls": False,
            "populated_corpus_embeddings_modified": False,
        },
    }
    assert retrieval_provenance(vector)["lexical_ranker"] is None
    assert "bm25" not in retrieval_provenance(lexical)
    assert "bm25" not in retrieval_provenance(vector)

    assert (bm25.bm25_k1, bm25.bm25_b, bm25.bm25_idf) == (
        DEFAULT_BM25_K1,
        DEFAULT_BM25_B,
        DEFAULT_BM25_IDF,
    )
    assert retrieval_provenance(bm25)["bm25"] == {
        "k1": DEFAULT_BM25_K1,
        "b": DEFAULT_BM25_B,
        "idf": DEFAULT_BM25_IDF,
    }
    assert (lexical.bm25_k1, lexical.bm25_b, lexical.bm25_idf) == (None, None, None)
    assert (vector.bm25_k1, vector.bm25_b, vector.bm25_idf) == (None, None, None)


def test_experiment_matrix_propagates_explicit_bm25_parameters():
    """Propagate caller-supplied BM25 parameters into arm provenance."""
    (config,) = experiment_matrix(
        target_tokens=(1024,),
        strategies=("hybrid",),
        lexical_rankers=("bm25",),
        bm25_k1=1.5,
        bm25_b=0.4,
        bm25_idf="robertson",
    )

    assert retrieval_provenance(config)["bm25"] == {
        "k1": 1.5,
        "b": 0.4,
        "idf": "robertson",
    }


def test_matrix_rejects_a_lexical_axis_without_a_ranker():
    """Reject a lexical axis with no ranker or with a repeated ranker."""
    with pytest.raises(ValueError, match="requires a lexical ranker"):
        experiment_matrix(target_tokens=(1024,), strategies=("lexical",), lexical_rankers=())
    with pytest.raises(ValueError, match="must be unique"):
        experiment_matrix(
            target_tokens=(1024,),
            strategies=("lexical",),
            lexical_rankers=("bm25", "bm25"),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"name": "Not Stable"}, "lowercase kebab-case"),
        ({"target_tokens": 0}, "must be positive"),
        ({"strategy": "unknown"}, "unsupported retrieval strategy"),
        ({"candidate_k": 4}, "inconsistent"),
        ({"lexical_ranker": None}, "requires an explicit lexical ranker"),
        ({"lexical_ranker": "okapi"}, "requires an explicit lexical ranker"),
        ({"strategy": "vector"}, "must not name a lexical ranker"),
        ({"bm25_k1": None}, "require explicit k1"),
        (
            {"lexical_ranker": "ts_rank_cd", "bm25_b": None, "bm25_idf": None},
            "only for bm25 arms",
        ),
    ],
    ids=[
        "name_not_kebab_case",
        "nonpositive_chunk_target",
        "unknown_strategy",
        "candidate_depth_below_k",
        "hybrid_without_a_ranker",
        "unknown_ranker",
        "vector_names_a_ranker",
        "bm25_arm_without_k1",
        "ts_rank_cd_arm_with_a_bm25_value",
    ],
)
def test_experiment_config_rejects_ambiguous_or_inconsistent_values(changes, message):
    """Reject arm provenance that is malformed or internally contradictory, naming the rule."""
    values = {
        "name": "structure-1024-hybrid",
        "target_tokens": 1024,
        "strategy": "hybrid",
        "embedding_provider": "deterministic",
        "dimensions": 384,
        "lexical_ranker": "bm25",
        "bm25_k1": DEFAULT_BM25_K1,
        "bm25_b": DEFAULT_BM25_B,
        "bm25_idf": DEFAULT_BM25_IDF,
        "k": 5,
        "candidate_k": 20,
        "rrf_k": 60,
    }
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        ExperimentConfig(**values)


def test_run_ablation_writes_stable_raw_artifacts_and_comparison_table(tmp_path):
    """Evaluate arms in canonical order, writing one artifact and one table row each."""
    recorded_at = datetime(2026, 8, 12, 14, 30, tzinfo=UTC)
    configs = experiment_matrix(
        target_tokens=(1024, 2048),
        strategies=("lexical",),
        lexical_rankers=("bm25",),
    )

    async def evaluator(config):
        """Evaluate one arm against a fixed hit and a fixed clock."""

        async def retriever(_query, _k):
            """Return the one relevant hit for every query."""
            return EvaluationRetrieval(hits=(relevant_hit(),))

        clock_values = iter((0, 1_000_000))
        return await evaluate_retriever(
            [positive_case()],
            retriever,
            suite="m3-test",
            config=config.to_dict(),
            clock=lambda: next(clock_values),
            recorded_at=recorded_at,
        )

    report = asyncio.run(
        run_ablation(
            tuple(reversed(configs)),
            evaluator,
            artifact_dir=tmp_path,
            recorded_at=recorded_at,
        )
    )

    assert [outcome.config.target_tokens for outcome in report.outcomes] == [1024, 2048]
    assert [outcome.artifact_path.name for outcome in report.outcomes] == [
        "20260812T143000Z-structure-1024-lexical-bm25.json",
        "20260812T143000Z-structure-2048-lexical-bm25.json",
    ]
    assert all(outcome.artifact_path.is_file() for outcome in report.outcomes)
    table = report.comparison_markdown()
    assert "| Config | Chunk target (tokens) | Retrieval | Lexical ranker |" in table
    assert "| structure-1024-lexical-bm25 | 1024 | lexical | bm25 | 1.000000 |" in table
    assert "20260812T143000Z-structure-2048-lexical-bm25.json" in table


def test_run_ablation_rejects_duplicate_config_names(tmp_path):
    """Reject repeated arm names before any evaluator runs."""
    config = ExperimentConfig(
        name="same-name",
        target_tokens=1024,
        strategy="lexical",
        embedding_provider="deterministic",
        dimensions=384,
        lexical_ranker="ts_rank_cd",
    )

    async def evaluator(_config):
        """Fail if reached, because name validation must run first."""
        raise AssertionError("duplicate validation must run first")

    with pytest.raises(ValueError, match="names must be unique"):
        asyncio.run(
            run_ablation(
                [config, config],
                evaluator,
                artifact_dir=tmp_path,
                recorded_at=datetime.now(UTC),
            )
        )


def test_run_ablation_accepts_extra_provenance_but_rejects_a_changed_arm(tmp_path):
    """The admin surface adds its corpus and golden identity to the evaluation config; the
    arm's own values must still be carried unchanged."""
    recorded_at = datetime(2026, 8, 12, 14, 30, tzinfo=UTC)
    (config,) = experiment_matrix(
        target_tokens=(1024,), strategies=("lexical",), lexical_rankers=("bm25",)
    )

    def evaluator_with(extra):
        """Build an evaluator whose config is the arm provenance plus ``extra``."""

        async def evaluator(arm):
            """Evaluate one arm against a fixed hit."""

            async def retriever(_query, _k):
                """Return the one relevant hit for every query."""
                return EvaluationRetrieval(hits=(relevant_hit(),))

            return await evaluate_retriever(
                [positive_case()],
                retriever,
                suite="m3-test",
                config=arm.to_dict() | extra,
                clock=lambda: 0,
                recorded_at=recorded_at,
            )

        return evaluator

    identity = {"admin_identity": {"golden_sha256": "a" * 64, "corpus_fingerprint": "b" * 64}}
    report = asyncio.run(
        run_ablation(
            (config,), evaluator_with(identity), artifact_dir=tmp_path, recorded_at=recorded_at
        )
    )
    (outcome,) = report.outcomes
    assert outcome.evaluation.config["admin_identity"] == identity["admin_identity"]
    assert outcome.evaluation.config["chunking"]["target_tokens"] == 1024

    with pytest.raises(ValueError, match="does not carry arm"):
        asyncio.run(
            run_ablation(
                (config,),
                evaluator_with({"chunking": {"target_tokens": 2048}}),
                artifact_dir=tmp_path / "changed",
                recorded_at=recorded_at,
            )
        )
