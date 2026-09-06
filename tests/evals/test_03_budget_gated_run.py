"""Assembled runner behavior: budget evidence, artifacts, and the run verdict."""

import asyncio
from contextlib import asynccontextmanager
import json

import pytest

from app.config import DEFAULT_BM25_B, DEFAULT_BM25_IDF, DEFAULT_BM25_K1, Settings
from app.evals.measurement import assess_indexing_budget
import app.evals.run as run
from app.evals.run import _run_cli, arguments, main
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.evals.support import positive_case, relevant_hit


class _Engine:
    """Async engine stub that only has to be disposable."""

    def __init__(self):
        self.disposed = False

    async def dispose(self):
        """Record that the runner released the engine."""
        self.disposed = True


def _install(monkeypatch, *, indexing_seconds=1.0, arms=None):
    """Replace every I/O boundary of the runner and record the arms it binds."""
    bound = [] if arms is None else arms
    engine = _Engine()

    monkeypatch.setattr(
        run, "get_settings", lambda: Settings(embedding_provider="deterministic", review_model=None)
    )
    provider = DeterministicEmbeddingProvider(dimensions=8)
    monkeypatch.setattr(run, "get_embedding_provider", lambda _settings: provider)
    monkeypatch.setattr(
        run, "load_golden_cases", lambda _path, *, manifest_path, selection_id: [positive_case()]
    )
    monkeypatch.setattr(
        run,
        "load_chunking_filings",
        lambda *, settings, manifest_name, selection_id, on_progress: (object(), object()),
    )
    monkeypatch.setattr(
        run,
        "build_chunking_batch",
        lambda target, *, provider, parsed_filings, selection_id, settings, on_progress: object(),
    )
    monkeypatch.setattr(run, "create_async_engine", lambda *_a, **_k: engine)

    @asynccontextmanager
    async def temporary_corpus_session(
        _engine,
        _batch,
        _provider,
        *,
        target_tokens,
        embedding_provider,
        shared_preparation_seconds,
        started_at_ns,
        on_progress,
    ):
        """Yield a stub session with fixed indexing evidence for one chunk target."""
        yield (
            object(),
            assess_indexing_budget(
                target_tokens=target_tokens,
                document_count=2,
                chunk_count=6,
                embedding_provider="deterministic",
                target_phase_seconds=indexing_seconds,
            ),
        )

    monkeypatch.setattr(run, "temporary_corpus_session", temporary_corpus_session)

    def make_retriever(_session, *, strategy, lexical_ranker=None, **_kwargs):
        """Record the bound arm and always return the one relevant hit."""
        bound.append((strategy, lexical_ranker))

        async def retriever(_query, _k):
            """Return the fixed relevant hit for one bound arm."""
            return [relevant_hit()]

        return retriever

    monkeypatch.setattr(run, "make_retriever", make_retriever)
    return engine, bound


def _execute(monkeypatch, argv, **install):
    """Run the command with every boundary stubbed and return its result dict."""
    engine, bound = _install(monkeypatch, **install)
    result = asyncio.run(_run_cli(arguments(argv)))
    assert engine.disposed
    return result, bound


def _budget(result):
    """Read back the budget artifact the run wrote."""
    return json.loads(open(result["budget_artifact"], encoding="utf-8").read())


def test_a_full_run_writes_one_artifact_per_arm_and_one_budget_artifact(monkeypatch, tmp_path):
    """Emit every arm's raw evidence plus a single budget artifact for the run."""
    result, _bound = _execute(monkeypatch, ["--artifact-dir", str(tmp_path)])

    assert len(result["artifacts"]) == 10
    assert len({path for path in result["artifacts"]}) == 10
    assert result["budget_artifact"].endswith("-budgets.json")
    assert result["passed"] is True
    assert "| structure-1024-lexical-ts-rank-cd |" in result["comparison_table"]


def test_the_budget_artifact_names_the_arm_its_latency_belongs_to(monkeypatch, tmp_path):
    """Record the corpus and retrieval lane behind the reported repeated-query latency."""
    result, _bound = _execute(monkeypatch, ["--artifact-dir", str(tmp_path)])

    arm = _budget(result)["query_budget"]["arm"]

    assert arm["target_tokens"] == 2048
    assert arm["strategy"] == "hybrid"
    assert arm["lexical_ranker"] == "ts_rank_cd"
    assert arm["bm25"] is None
    assert (arm["k"], arm["candidate_k"], arm["rrf_k"]) == (5, 20, 60)


def test_a_shortened_budget_run_is_not_assessed_against_the_full_query_limit(monkeypatch, tmp_path):
    """Scale the asserted limit to the queries actually measured."""
    result, _bound = _execute(
        monkeypatch, ["--artifact-dir", str(tmp_path), "--budget-queries", "20"]
    )

    query_budget = _budget(result)["query_budget"]

    assert query_budget["latency"]["query_count"] == 20
    assert query_budget["budget_seconds"] == 9.0


def test_the_budget_arm_is_the_same_however_the_strategy_axis_is_ordered(monkeypatch, tmp_path):
    """Produce identical budget provenance for the same matrix typed in any order."""
    forward, _ = _execute(
        monkeypatch,
        ["--artifact-dir", str(tmp_path / "a"), "--strategies", "lexical", "vector"],
    )
    reversed_axis, _ = _execute(
        monkeypatch,
        ["--artifact-dir", str(tmp_path / "b"), "--strategies", "vector", "lexical"],
    )

    assert _budget(forward)["query_budget"]["arm"] == _budget(reversed_axis)["query_budget"]["arm"]
    assert _budget(forward)["query_budget"]["arm"]["strategy"] == "vector"


def test_a_bm25_only_budget_arm_records_the_parameters_it_measured(monkeypatch, tmp_path):
    """Record the exact BM25 values behind a lexical budget measurement."""
    result, _bound = _execute(
        monkeypatch,
        ["--artifact-dir", str(tmp_path), "--strategies", "lexical", "--lexical-rankers", "bm25"],
    )

    arm = _budget(result)["query_budget"]["arm"]

    assert arm["strategy"] == "lexical"
    assert arm["lexical_ranker"] == "bm25"
    assert arm["bm25"] == {"k1": DEFAULT_BM25_K1, "b": DEFAULT_BM25_B, "idf": DEFAULT_BM25_IDF}


def test_an_exceeded_indexing_budget_fails_the_run(monkeypatch, tmp_path):
    """Report failure instead of printing a blown budget and exiting successfully."""
    result, _bound = _execute(
        monkeypatch, ["--artifact-dir", str(tmp_path)], indexing_seconds=301.0
    )

    assert all(arm["passed"] is False for arm in _budget(result)["indexing"]["arms"])
    assert result["passed"] is False


def test_the_command_exit_status_follows_the_measured_verdict(monkeypatch, tmp_path, capsys):
    """Exit nonzero on a blown budget so a regression cannot pass unnoticed."""
    _install(monkeypatch, indexing_seconds=301.0)
    failed = main(["--artifact-dir", str(tmp_path / "fail")])
    capsys.readouterr()

    _install(monkeypatch, indexing_seconds=1.0)
    passed = main(["--artifact-dir", str(tmp_path / "pass")])
    printed = capsys.readouterr().out

    assert failed == 1
    assert passed == 0
    assert '"passed": true' in printed


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--target-tokens", "1024"], 5),
        (["--strategies", "vector"], 2),
        (["--strategies", "lexical", "--lexical-rankers", "bm25"], 2),
    ],
)
def test_a_narrowed_matrix_runs_exactly_the_requested_arms(monkeypatch, tmp_path, argv, expected):
    """Run one arm per requested combination and no vector arm per ranker."""
    result, _bound = _execute(monkeypatch, ["--artifact-dir", str(tmp_path), *argv])

    assert len(result["artifacts"]) == expected
