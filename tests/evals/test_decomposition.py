"""Decomposition comparison: category slices, paired artifacts, and deltas."""

import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import cast

import pytest

from app.db.session_factory import SessionFactory
from app.evals.decompose import make_decomposed_retriever
from app.evals.decomposition import category_metrics, run_decomposition_comparison
from app.evals.retrieval_eval import RetrievalEvaluation
from app.evals.scoring import CaseScore
from app.evals.types import EvaluationRetrieval
from app.llm.local_engine import local_provider_budget
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.agent.support import FakeSessionFactory
from tests.evals.support import EVALUATION_RECORDED_AT, absent_case, positive_case, relevant_hit
from tests.llm.support import DeterministicLLMProvider, raw


def test_category_metrics_slices_scored_cases_only():
    """Report per-category metrics over scored cases, omitting unscored ones."""

    def case(category, recall, rank, index):
        """Build one evaluated case, scored or left unscored."""
        score = None
        if recall is not None:
            score = CaseScore(
                case_id=f"m3c-{category[:2]}-{index}",
                k=5,
                gold_span_count=2,
                matched_gold_count=int(recall * 2),
                recall_at_k=recall,
                hit_at_k=float(recall > 0),
                reciprocal_rank=1.0 / rank,
                first_relevant_rank=rank,
            )
        return SimpleNamespace(golden=SimpleNamespace(category=category), score=score)

    evaluation = SimpleNamespace(
        cases=(
            case("multi_hop", 0.5, 2, 1),
            case("multi_hop", 1.0, 1, 2),
            case("simple_lookup", 1.0, 1, 1),
            case("absent", None, 1, 1),
        )
    )

    metrics = category_metrics(cast(RetrievalEvaluation, evaluation))

    assert set(metrics) == {"multi_hop", "simple_lookup"}
    assert metrics["multi_hop"]["scored_case_count"] == 2.0
    assert metrics["multi_hop"]["recall_at_k"] == pytest.approx(0.75)
    assert metrics["multi_hop"]["mrr"] == pytest.approx(0.75)
    assert metrics["simple_lookup"]["recall_at_k"] == pytest.approx(1.0)


def test_comparison_writes_paired_artifacts_and_signed_category_deltas(tmp_path):
    """Run both arms through the real harness and difference their categories."""
    cases = (positive_case(), absent_case())

    async def covering(question, k):
        """Return the hit that covers the positive case's gold span."""
        return EvaluationRetrieval(hits=(relevant_hit(),))

    async def empty(question, k):
        """Return no hits, so the decomposed arm scores zero."""
        return EvaluationRetrieval(hits=())

    result = asyncio.run(
        run_decomposition_comparison(
            cases,
            baseline_retriever=covering,
            decomposed_retriever=empty,
            baseline_config={"strategy": "single_query"},
            decomposed_config={"strategy": "decomposed"},
            suite="m9-decomposition-v1",
            artifact_dir=tmp_path,
            k=5,
            recorded_at=EVALUATION_RECORDED_AT,
        )
    )

    assert result["baseline"]["categories"]["simple_lookup"]["recall_at_k"] == 1.0
    assert result["decomposed"]["categories"]["simple_lookup"]["recall_at_k"] == 0.0
    assert result["category_deltas"]["simple_lookup"]["recall_at_k"] == pytest.approx(-1.0)
    for label in ("baseline", "decomposed"):
        path = tmp_path / f"20260101T000000Z-m9-decomposition-v1-decomposition-{label}.json"
        assert result["artifacts"][label] == str(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["suite"] == "m9-decomposition-v1"


def test_comparison_refuses_to_overwrite_and_rejects_naive_timestamps(tmp_path):
    """Fail loudly on an existing artifact, and on a naive timestamp before any retrieval."""
    cases = (positive_case(), absent_case())
    retrievals = []

    async def counting(question, k):
        """Count every retrieval so a rejected run provably ran none."""
        retrievals.append(question)
        return EvaluationRetrieval(hits=(relevant_hit(),))

    shared = {
        "baseline_retriever": counting,
        "decomposed_retriever": counting,
        "baseline_config": {"strategy": "single_query"},
        "decomposed_config": {"strategy": "decomposed"},
        "suite": "m9-decomposition-v1",
        "artifact_dir": tmp_path,
    }

    naive = datetime(2026, 1, 1)  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone-aware"):
        asyncio.run(run_decomposition_comparison(cases, recorded_at=naive, **shared))
    assert retrievals == []

    asyncio.run(run_decomposition_comparison(cases, recorded_at=EVALUATION_RECORDED_AT, **shared))
    with pytest.raises(FileExistsError):
        asyncio.run(
            run_decomposition_comparison(cases, recorded_at=EVALUATION_RECORDED_AT, **shared)
        )


def test_comparison_records_each_actual_decomposition_without_changing_rankings(
    tmp_path, monkeypatch
):
    """Associate measured questions and fallback with case IDs, even for repeated questions."""
    original = "Repeated question?"
    cases = tuple(
        positive_case().model_copy(update={"id": identifier, "question": original})
        for identifier in ("case-b", "case-a")
    )
    provider = DeterministicLLMProvider(
        [
            raw('{"sub_questions":["First lane?","Shared lane?"]}'),
            raw("not json"),
            raw("still not json"),
        ]
    )
    first, second, third = (
        relevant_hit().model_copy(update={"chunk_id": identifier}) for identifier in (1, 2, 3)
    )
    queries = []

    async def retrieve(session, query, **kwargs):
        """Return fixed lane rankings through the actual decomposition and fusion path."""
        queries.append(query)
        return SimpleNamespace(
            hits={
                "First lane?": (first, second),
                "Shared lane?": (second, third),
                original: (third,),
            }[query]
        )

    async def baseline(question, k):
        """Return the undecomposed ranking without decomposition evidence."""
        assert question == original
        return EvaluationRetrieval(hits=(third,))

    monkeypatch.setattr(sys.modules[make_decomposed_retriever.__module__], "retrieve", retrieve)
    retriever = make_decomposed_retriever(
        cast(SessionFactory, FakeSessionFactory()),
        llm_provider=provider,
        provider_budget=local_provider_budget(max_input_tokens=1_000, max_output_tokens=200),
        embedding_provider=DeterministicEmbeddingProvider(),
    )
    result = asyncio.run(
        run_decomposition_comparison(
            cases,
            baseline_retriever=baseline,
            decomposed_retriever=retriever,
            baseline_config={"strategy": "single_query"},
            decomposed_config={"strategy": "decomposed"},
            suite="decomposition-evidence",
            artifact_dir=tmp_path,
            k=2,
            recorded_at=EVALUATION_RECORDED_AT,
        )
    )

    payload = json.loads(Path(result["artifacts"]["decomposed"]).read_text(encoding="utf-8"))
    decomposed, fallback = payload["cases"]
    assert [case["golden"]["id"] for case in payload["cases"]] == ["case-a", "case-b"]
    assert [case["golden"]["question"] for case in payload["cases"]] == [original, original]
    assert decomposed["decomposition"] == {
        "sub_questions": ["First lane?", "Shared lane?"],
        "fallback_status": None,
    }
    assert fallback["decomposition"] == {
        "sub_questions": [original],
        "fallback_status": "schema_rejected",
    }
    assert [hit["chunk_id"] for hit in decomposed["hits"]] == [2, 1]
    assert [hit["chunk_id"] for hit in fallback["hits"]] == [3]
    assert queries == ["First lane?", "Shared lane?", original]
    assert provider.prompts[0].user == provider.prompts[1].user == original
    baseline_payload = json.loads(Path(result["artifacts"]["baseline"]).read_text(encoding="utf-8"))
    assert all("decomposition" not in case for case in baseline_payload["cases"])
