"""M3.4 retrieval runner, provenance, raw result, and budget tests."""

import asyncio
from datetime import UTC, datetime
import importlib
import json
import os
from types import SimpleNamespace

import pytest

from app.evals.types import GoldenCase, GoldenSpan
from app.retrieval.types import ChunkHit
from tests.support import need

RUNNER_MODULE_NAME = os.getenv("EVAL_RUNNER_MODULE", "app.evals.retrieval_eval")
R = importlib.import_module(RUNNER_MODULE_NAME)
SOURCE_SHA256 = "a" * 64


def positive_case(case_id="m3c-01") -> GoldenCase:
    return GoldenCase(
        id=case_id,
        question="What evidence is supported?",
        category="simple_lookup",
        facet="factual",
        tags=("runner",),
        answers=(
            GoldenSpan(
                doc_id="NVDA-FY2024",
                source_sha256=SOURCE_SHA256,
                start_char=100,
                end_char=200,
            ),
        ),
        expected_label="SUPPORTED",
        reference_answer="Supported evidence.",
        note="Deterministic runner fixture.",
        curation_status="agent-curated",
        approval_status="pending-author-approval",
        human_verified=False,
    )


def absent_case(case_id="m3c-02") -> GoldenCase:
    return GoldenCase(
        id=case_id,
        question="What evidence is absent?",
        category="absent",
        facet="risk",
        tags=("negative",),
        answers=(),
        expected_label="NOT_IN_DOCS",
        reference_answer="NOT_IN_DOCS",
        note="Retrieval-only metrics do not score absence.",
        curation_status="agent-curated",
        approval_status="pending-author-approval",
        human_verified=False,
    )


def relevant_hit() -> ChunkHit:
    return ChunkHit(
        chunk_id=1,
        doc_id="NVDA-FY2024",
        item="7",
        kind="text",
        citation="NVDA FY2024 · Item 7",
        start_char=90,
        end_char=210,
        source_sha256=SOURCE_SHA256,
        body="Supported evidence.",
        context_header="NVDA FY2024 · Item 7",
        index_text="NVDA FY2024 · Item 7\n\nSupported evidence.",
        score=1.0,
    )


def _evaluation():
    async def retriever(_query, _k):
        return [relevant_hit()]

    clock_values = iter((0, 1_000_000, 2_000_000, 5_000_000))
    return asyncio.run(
        R.evaluate_retriever(
            [absent_case(), positive_case()],
            retriever,
            suite="m3-runner-test",
            config={"provider": "deterministic", "k": 5},
            clock=lambda: next(clock_values),
            recorded_at=datetime(2026, 8, 12, 15, tzinfo=UTC),
        )
    )


def test_runner_records_all_cases_but_scores_only_source_bearing_positives():
    need(R, "evaluate_retriever", "RetrievalEvaluation")
    evaluation = _evaluation()

    assert [case.golden.id for case in evaluation.cases] == ["m3c-01", "m3c-02"]
    assert evaluation.score.case_count == 1
    assert evaluation.score.recall_at_k == 1.0
    assert evaluation.score.hit_rate_at_k == 1.0
    assert evaluation.score.mrr == 1.0
    assert evaluation.cases[0].score is not None
    assert evaluation.cases[1].score is None
    assert evaluation.provenance.total_cases == 2
    assert evaluation.provenance.scored_positive_cases == 1
    assert evaluation.provenance.unscored_absent_cases == 1
    assert evaluation.provenance.curation_status == "agent-curated"
    assert evaluation.provenance.approval_status == "pending-author-approval"
    assert evaluation.provenance.human_verified is False
    assert evaluation.latency.total_ms == 4.0
    assert evaluation.latency.mean_ms == 2.0
    assert evaluation.latency.p95_ms == 3.0


def test_raw_artifact_preserves_hits_spans_latency_and_review_provenance(tmp_path):
    need(R, "write_evaluation_artifact")
    path = R.write_evaluation_artifact(tmp_path / "raw.json", _evaluation())
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["recorded_at"] == "2026-08-12T15:00:00Z"
    assert payload["golden_provenance"]["human_verified"] is False
    assert payload["golden_provenance"]["approval_status"] == "pending-author-approval"
    assert payload["cases"][0]["hits"][0]["source_sha256"] == SOURCE_SHA256
    assert payload["cases"][0]["hits"][0]["start_char"] == 90
    assert payload["cases"][0]["latency_ms"] == 1.0
    assert payload["cases"][1]["score"] is None


def test_200_query_budget_measures_exact_boundary_without_storing_fake_results():
    need(R, "measure_query_budget", "QUERY_BUDGET_COUNT", "QUERY_BUDGET_SECONDS")
    calls = []

    async def retriever(query, k):
        calls.append((query, k))
        return []

    tick = -450_000_000

    def clock():
        nonlocal tick
        tick += 450_000_000
        return tick

    result = asyncio.run(
        R.measure_query_budget(
            ["q1", "q2"],
            retriever,
            k=5,
            query_count=R.QUERY_BUDGET_COUNT,
            budget_seconds=R.QUERY_BUDGET_SECONDS,
            clock=clock,
        )
    )

    assert len(calls) == 200
    assert calls[:3] == [("q1", 5), ("q2", 5), ("q1", 5)]
    assert result.total_seconds == 90.0
    assert result.passed
    assert result.p95_ms == 450.0


def test_query_budget_fails_only_after_the_explicit_limit():
    need(R, "measure_query_budget")

    async def retriever(_query, _k):
        return []

    tick = -450_000_001

    def clock():
        nonlocal tick
        tick += 450_000_001
        return tick

    result = asyncio.run(
        R.measure_query_budget(
            ["q"],
            retriever,
            query_count=200,
            budget_seconds=90.0,
            clock=clock,
        )
    )

    assert result.total_seconds > 90.0
    assert not result.passed


def test_indexing_budget_keeps_configuration_and_provider_provenance():
    need(R, "assess_indexing_budget")
    result = R.assess_indexing_budget(
        target_text_chars=500,
        document_count=20,
        chunk_count=10_000,
        embedding_provider="deterministic",
        target_phase_seconds=284.0,
        shared_preparation_seconds=15.5,
    )

    assert result.passed
    assert result.embedding_provider == "deterministic"
    assert result.target_text_chars == 500
    assert result.target_phase_seconds == 284.0
    assert result.derived_standalone_seconds == 299.5


def test_budget_schema_v2_separates_shared_and_target_work():
    need(
        R,
        "BUDGET_ARTIFACT_SCHEMA_VERSION",
        "IndexingBudgetMeasurement",
        "SharedPreparationMeasurement",
    )
    shared = R.SharedPreparationMeasurement(
        operation="manifest-load-and-parse",
        document_count=20,
        total_seconds=15.0,
    )
    arms = (
        R.assess_indexing_budget(
            target_text_chars=500,
            document_count=20,
            chunk_count=12_984,
            embedding_provider="deterministic",
            target_phase_seconds=25.0,
            shared_preparation_seconds=15.0,
        ),
        R.assess_indexing_budget(
            target_text_chars=1_200,
            document_count=20,
            chunk_count=9_172,
            embedding_provider="deterministic",
            target_phase_seconds=20.0,
            shared_preparation_seconds=15.0,
        ),
    )

    payload = R._indexing_budget_payload(shared, arms)

    assert R.BUDGET_ARTIFACT_SCHEMA_VERSION == 2
    assert payload["shared_preparation"] == {
        "operation": "manifest-load-and-parse",
        "document_count": 20,
        "total_seconds": 15.0,
    }
    assert [arm["target_phase_seconds"] for arm in payload["arms"]] == [25.0, 20.0]
    assert [arm["derived_standalone_seconds"] for arm in payload["arms"]] == [40.0, 35.0]
    assert payload["measured_multi_target_work_seconds"] == 60.0


def test_build_chunking_batch_reuses_supplied_filings_without_loading_manifest(monkeypatch):
    need(R, "build_chunking_batch")
    parsed_filings = (object(),)
    expected_batch = object()
    calls = []

    def build_from_filings(filings, *, chunker):
        calls.append(filings)
        assert callable(chunker)
        return expected_batch

    monkeypatch.setattr(R, "build_seed_batch_from_filings", build_from_filings)
    monkeypatch.setattr(
        R,
        "load_manifest",
        lambda _path: pytest.fail("manifest must not be loaded when parsed filings are supplied"),
    )

    result = R.build_chunking_batch(500, parsed_filings=parsed_filings)

    assert result is expected_batch
    assert calls == [parsed_filings]


def test_load_chunking_filings_parses_the_manifest_once(monkeypatch, tmp_path):
    need(R, "load_chunking_filings")
    manifest = tmp_path / "manifest.json"
    entries = [{"ticker": "NVDA"}, {"ticker": "AMD"}]
    parsed_filings = (object(), object())
    calls = []

    monkeypatch.setattr(R, "load_manifest", lambda path: entries if path == manifest else None)

    def parse_once(received, *, expected_documents):
        calls.append((received, expected_documents))
        return parsed_filings

    monkeypatch.setattr(R, "parse_seed_filings", parse_once)
    settings = type("SettingsStub", (), {"corpus_dir": tmp_path})()

    result = R.load_chunking_filings(settings=settings)

    assert result is parsed_filings
    assert calls == [(entries, 20)]


@pytest.mark.parametrize(
    "cases",
    [[], [absent_case()]],
)
def test_runner_rejects_empty_or_absent_only_scoring_suites(cases):
    need(R, "evaluate_retriever")

    async def retriever(_query, _k):
        return []

    with pytest.raises(ValueError):
        asyncio.run(
            R.evaluate_retriever(
                cases,
                retriever,
                suite="m3-test",
                config={},
            )
        )


def test_cli_defaults_to_the_isolated_deterministic_ten_arm_matrix():
    need(R, "arguments")
    args = R.arguments([])

    assert args.provider == "deterministic"
    assert args.target_text_chars == [500, 1200]
    assert args.strategies == ["lexical", "vector", "hybrid"]
    assert args.lexical_rankers == ["ts_rank_cd", "bm25"]
    assert args.budget_queries == 200
    assert not args.persist_results


def test_cli_default_axes_expand_to_ten_uniquely_named_arms():
    """Two chunk targets, three retrieval paths, two rankers, no duplicated vector arm."""
    need(R, "arguments")
    from app.evals.ablation import experiment_matrix

    args = R.arguments([])
    configs = [
        config
        for target in args.target_text_chars
        for config in experiment_matrix(
            target_text_chars=(target,),
            strategies=tuple(args.strategies),
            lexical_rankers=tuple(args.lexical_rankers),
        )
    ]

    assert len(configs) == 10
    assert len({config.name for config in configs}) == 10
    assert sum(config.strategy == "vector" for config in configs) == 2


def test_cli_can_narrow_the_ranker_axis():
    need(R, "arguments")
    args = R.arguments(["--lexical-rankers", "bm25"])

    assert args.lexical_rankers == ["bm25"]


def test_every_retrieval_strategy_receives_the_same_normalized_query(monkeypatch):
    need(R, "make_retriever")
    queries = []

    class Provider:
        dimensions = 384

        async def embed_query(self, query):
            queries.append(query)
            return [0.0] * self.dimensions

    async def lexical_search(_session, query, _k, _filters):
        queries.append(query)
        return []

    async def vector_search(_session, _vector, *, k, filters):
        assert k == 1
        assert filters is None
        return []

    async def retrieve(_session, query, **_kwargs):
        queries.append(query)
        return SimpleNamespace(hits=())

    monkeypatch.setattr(R, "lexical_search", lexical_search)
    monkeypatch.setattr(R, "vector_search", vector_search)
    monkeypatch.setattr(R, "retrieve", retrieve)
    provider = Provider()

    retrievers = (
        R.make_retriever(object(), strategy="lexical", provider=None, lexical_ranker="ts_rank_cd"),
        R.make_retriever(object(), strategy="vector", provider=provider),
        R.make_retriever(
            object(), strategy="hybrid", provider=provider, lexical_ranker="ts_rank_cd"
        ),
    )
    for retriever in retrievers:
        asyncio.run(retriever("NVDA 2024 R&D", 1))

    assert queries == ["NVDA 2024 research development"] * 3


def test_bm25_parameters_are_identical_in_lexical_and_hybrid_paths(monkeypatch):
    need(R, "make_retriever")
    calls = []

    class Provider:
        dimensions = 384

        async def embed_query(self, _query):
            return [0.0] * self.dimensions

    async def bm25_search(_session, query, _k, _filters, *, k1, b, idf):
        calls.append(("lexical", query, k1, b, idf))
        return []

    async def retrieve(_session, query, **kwargs):
        calls.append(
            (
                "hybrid",
                query,
                kwargs["bm25_k1"],
                kwargs["bm25_b"],
                kwargs["bm25_idf"],
            )
        )
        return SimpleNamespace(hits=())

    monkeypatch.setattr(R, "bm25_search", bm25_search)
    monkeypatch.setattr(R, "retrieve", retrieve)
    settings = {"bm25_k1": 1.5, "bm25_b": 0.4, "bm25_idf": "robertson"}
    lexical = R.make_retriever(
        object(), strategy="lexical", provider=None, lexical_ranker="bm25", **settings
    )
    hybrid = R.make_retriever(
        object(), strategy="hybrid", provider=Provider(), lexical_ranker="bm25", **settings
    )

    asyncio.run(lexical("R & D spending", 1))
    asyncio.run(hybrid("R & D spending", 1))

    assert calls == [
        ("lexical", "research development spending", 1.5, 0.4, "robertson"),
        ("hybrid", "research development spending", 1.5, 0.4, "robertson"),
    ]
