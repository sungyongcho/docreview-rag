"""M3.4 configurable experiment matrix and raw artifact tests."""

import asyncio
from datetime import UTC, datetime
import importlib
import os

import pytest

from app.evals.retrieval_eval import evaluate_retriever
from app.evals.types import GoldenCase, GoldenSpan
from app.retrieval.types import ChunkHit
from tests.support import need

ABLATION_MODULE_NAME = os.getenv("EVAL_ABLATION_MODULE", "app.evals.ablation")
A = importlib.import_module(ABLATION_MODULE_NAME)
SOURCE_SHA256 = "a" * 64


def golden_case() -> GoldenCase:
    return GoldenCase(
        id="m3c-01",
        question="Where is the source-grounded evidence?",
        category="simple_lookup",
        facet="factual",
        tags=("demo-hero",),
        answers=(
            GoldenSpan(
                doc_id="NVDA-FY2024",
                source_sha256=SOURCE_SHA256,
                start_char=100,
                end_char=200,
            ),
        ),
        expected_label="SUPPORTED",
        reference_answer="In the cited span.",
        note="Deterministic ablation fixture.",
        curation_status="agent-curated",
        approval_status="pending-author-approval",
        human_verified=False,
    )


def hit() -> ChunkHit:
    return ChunkHit(
        chunk_id=1,
        doc_id="NVDA-FY2024",
        item="7",
        kind="text",
        citation="NVDA FY2024 · Item 7",
        start_char=90,
        end_char=210,
        source_sha256=SOURCE_SHA256,
        body="Source-grounded evidence.",
        context_header="NVDA FY2024 · Item 7",
        index_text="NVDA FY2024 · Item 7\n\nSource-grounded evidence.",
        score=1.0,
    )


def test_experiment_matrix_crosses_chunking_retrieval_and_lexical_ranker():
    need(A, "ExperimentConfig", "experiment_matrix")
    configs = A.experiment_matrix(
        target_text_chars=(1200, 500),
        strategies=("hybrid", "lexical", "vector"),
        lexical_rankers=("bm25", "ts_rank_cd"),
        embedding_provider="deterministic",
        dimensions=384,
    )

    assert [
        (config.target_text_chars, config.strategy, config.lexical_ranker) for config in configs
    ] == [
        (500, "lexical", "ts_rank_cd"),
        (500, "lexical", "bm25"),
        (500, "vector", None),
        (500, "hybrid", "ts_rank_cd"),
        (500, "hybrid", "bm25"),
        (1200, "lexical", "ts_rank_cd"),
        (1200, "lexical", "bm25"),
        (1200, "vector", None),
        (1200, "hybrid", "ts_rank_cd"),
        (1200, "hybrid", "bm25"),
    ]


def test_experiment_matrix_names_are_unique_and_filename_safe():
    need(A, "experiment_matrix")
    configs = A.experiment_matrix(target_text_chars=(500, 1200))
    names = [config.name for config in configs]

    assert len(set(names)) == len(names) == 10
    assert "structure-500-lexical-ts-rank-cd" in names
    assert "structure-1200-hybrid-bm25" in names
    for name in names:
        assert A.EXPERIMENT_NAME.fullmatch(name)


def test_vector_arm_is_not_duplicated_across_rankers():
    """The vector path never runs a lexical query, so a ranker label would lie."""
    need(A, "experiment_matrix")
    configs = A.experiment_matrix(
        target_text_chars=(500,),
        strategies=("vector",),
        lexical_rankers=("ts_rank_cd", "bm25"),
    )

    assert len(configs) == 1
    assert configs[0].name == "structure-500-vector"
    assert configs[0].lexical_ranker is None


def test_matrix_is_sorted_the_same_way_however_the_axes_are_given():
    need(A, "experiment_matrix")
    forward = A.experiment_matrix(
        target_text_chars=(500, 1200),
        strategies=("lexical", "vector", "hybrid"),
        lexical_rankers=("ts_rank_cd", "bm25"),
    )
    reversed_axes = A.experiment_matrix(
        target_text_chars=(1200, 500),
        strategies=("hybrid", "vector", "lexical"),
        lexical_rankers=("bm25", "ts_rank_cd"),
    )

    assert [config.name for config in forward] == [config.name for config in reversed_axes]


def test_config_provenance_records_the_ranker_that_produced_the_numbers():
    need(A, "experiment_matrix")
    lexical, _bm25, vector = A.experiment_matrix(
        target_text_chars=(500,),
        strategies=("lexical", "vector"),
    )

    assert lexical.to_dict() == {
        "name": "structure-500-lexical-ts-rank-cd",
        "chunking": {
            "strategy": "structure-aware",
            "target_text_chars": 500,
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
            "paid_api_calls": False,
            "populated_corpus_embeddings_modified": False,
        },
    }
    assert vector.to_dict()["retrieval"]["lexical_ranker"] is None


def test_matrix_rejects_a_lexical_axis_without_a_ranker():
    need(A, "experiment_matrix")
    with pytest.raises(ValueError, match="requires a lexical ranker"):
        A.experiment_matrix(target_text_chars=(500,), strategies=("lexical",), lexical_rankers=())
    with pytest.raises(ValueError, match="must be unique"):
        A.experiment_matrix(
            target_text_chars=(500,),
            strategies=("lexical",),
            lexical_rankers=("bm25", "bm25"),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "Not Stable"},
        {"target_text_chars": 0},
        {"strategy": "unknown"},
        {"candidate_k": 4},
        {"lexical_ranker": None},
        {"lexical_ranker": "okapi"},
        {"strategy": "vector"},
    ],
)
def test_experiment_config_rejects_ambiguous_or_inconsistent_values(changes):
    need(A, "ExperimentConfig")
    values = {
        "name": "structure-500-hybrid",
        "target_text_chars": 500,
        "strategy": "hybrid",
        "embedding_provider": "deterministic",
        "dimensions": 384,
        "lexical_ranker": "bm25",
        "k": 5,
        "candidate_k": 20,
        "rrf_k": 60,
    }
    values.update(changes)
    with pytest.raises(ValueError):
        A.ExperimentConfig(**values)


def test_run_ablation_writes_stable_raw_artifacts_and_comparison_table(tmp_path):
    need(A, "experiment_matrix", "run_ablation")
    recorded_at = datetime(2026, 8, 12, 14, 30, tzinfo=UTC)
    configs = A.experiment_matrix(
        target_text_chars=(500, 1200),
        strategies=("lexical",),
        lexical_rankers=("bm25",),
    )

    async def evaluator(config):
        async def retriever(_query, _k):
            return [hit()]

        clock_values = iter((0, 1_000_000))
        return await evaluate_retriever(
            [golden_case()],
            retriever,
            suite="m3-test",
            config=config.to_dict(),
            clock=lambda: next(clock_values),
            recorded_at=recorded_at,
        )

    report = asyncio.run(
        A.run_ablation(
            tuple(reversed(configs)),
            evaluator,
            artifact_dir=tmp_path,
            recorded_at=recorded_at,
        )
    )

    assert [outcome.config.target_text_chars for outcome in report.outcomes] == [500, 1200]
    assert [outcome.artifact_path.name for outcome in report.outcomes] == [
        "20260812T143000Z-structure-500-lexical-bm25.json",
        "20260812T143000Z-structure-1200-lexical-bm25.json",
    ]
    assert all(outcome.artifact_path.is_file() for outcome in report.outcomes)
    table = report.comparison_markdown()
    assert "| Config | Chunk target | Retrieval | Lexical ranker |" in table
    assert "| structure-500-lexical-bm25 | 500 | lexical | bm25 | 1.000000 |" in table
    assert "20260812T143000Z-structure-1200-lexical-bm25.json" in table


def test_run_ablation_rejects_duplicate_config_names(tmp_path):
    need(A, "ExperimentConfig", "run_ablation")
    config = A.ExperimentConfig(
        name="same-name",
        target_text_chars=500,
        strategy="lexical",
        embedding_provider="deterministic",
        dimensions=384,
        lexical_ranker="ts_rank_cd",
    )

    async def evaluator(_config):
        raise AssertionError("duplicate validation must run first")

    with pytest.raises(ValueError, match="names must be unique"):
        asyncio.run(
            A.run_ablation(
                [config, config],
                evaluator,
                artifact_dir=tmp_path,
                recorded_at=datetime.now(UTC),
            )
        )
