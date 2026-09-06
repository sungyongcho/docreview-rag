"""M9.5 decomposition: contract, fallback, n-list fusion, and category slices."""

import asyncio
from decimal import Decimal
import sys
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from app.evals.scoring import CaseScore
from app.llm import DeterministicLLMProvider, ProviderBudget, RawProviderResponse, TokenPricing
from app.retrieval import ChunkHit
from tests.retrieval.test_01_contract import hit_values
from tests.support import need


def budget():
    return ProviderBudget(
        max_input_tokens=1_000,
        max_output_tokens=200,
        max_cost_usd=Decimal("0.10"),
        pricing=TokenPricing(
            input_per_million_usd=Decimal("2"),
            output_per_million_usd=Decimal("10"),
        ),
    )


def raw(output_text):
    return RawProviderResponse(
        output_text=output_text,
        input_tokens=10,
        output_tokens=5,
        request_id="req-1",
        refusal=None,
    )


def hit(chunk_id, *, score=0.5):
    start = chunk_id * 100
    return ChunkHit(
        **hit_values(chunk_id=chunk_id, score=score, start_char=start, end_char=start + 50)
    )


def test_decomposition_contract_rejects_duplicates_and_overflow(AG):
    need(AG, "QueryDecomposition")
    AG.QueryDecomposition(sub_questions=("What was 2023 revenue?", "What was 2024 revenue?"))

    with pytest.raises(ValidationError):
        AG.QueryDecomposition(sub_questions=())
    with pytest.raises(ValidationError):
        AG.QueryDecomposition(sub_questions=("Same question?", "same   QUESTION?"))
    with pytest.raises(ValidationError):
        AG.QueryDecomposition(sub_questions=tuple(f"Question {index}?" for index in range(5)))


def test_decompose_query_returns_sub_questions_and_falls_back_on_failure(AG):
    need(AG, "decompose_query")
    provider = DeterministicLLMProvider(
        [raw('{"sub_questions":["What was 2023 revenue?","What was 2024 revenue?"]}')]
    )
    sub_questions = asyncio.run(
        AG.decompose_query(
            "How did revenue change between 2023 and 2024?",
            llm_provider=provider,
            provider_budget=budget(),
        )
    )
    assert sub_questions == ("What was 2023 revenue?", "What was 2024 revenue?")

    refusing = DeterministicLLMProvider([raw("not json"), raw("still not json")])
    fallback = asyncio.run(
        AG.decompose_query(
            "How did revenue change between 2023 and 2024?",
            llm_provider=refusing,
            provider_budget=budget(),
        )
    )
    assert fallback == ("How did revenue change between 2023 and 2024?",)


def test_merge_ranked_lists_rewards_cross_list_agreement(AG):
    need(AG, "merge_ranked_lists")
    first = (hit(1), hit(2))
    second = (hit(2), hit(3))

    fused = AG.merge_ranked_lists((first, second), 3, rrf_k=60)

    assert [item.chunk_id for item in fused] == [2, 1, 3]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    with pytest.raises(ValueError):
        AG.merge_ranked_lists((first,), 0)


def test_decomposed_retriever_merges_per_sub_question_rankings(AG, monkeypatch):
    need(AG, "make_decomposed_retriever")
    provider = DeterministicLLMProvider(
        [raw('{"sub_questions":["What was 2023 revenue?","What was 2024 revenue?"]}')]
    )
    queries = []

    async def fake_retrieve(session, query, **kwargs):
        queries.append(query)
        ranked = {
            ("What was 2023 revenue?"): (hit(1), hit(2)),
            "What was 2024 revenue?": (hit(2), hit(3)),
        }[query]
        return SimpleNamespace(hits=ranked)

    module = sys.modules[AG.make_decomposed_retriever.__module__]
    monkeypatch.setattr(module, "retrieve", fake_retrieve)
    retriever = AG.make_decomposed_retriever(
        object(),
        llm_provider=provider,
        provider_budget=budget(),
    )
    hits = asyncio.run(retriever("How did revenue change between 2023 and 2024?", 2))

    assert queries == ["What was 2023 revenue?", "What was 2024 revenue?"]
    assert [item.chunk_id for item in hits] == [2, 1]


def test_category_metrics_slices_scored_cases_only(AG):
    need(AG, "category_metrics")

    def case(category, recall, rank):
        score = None
        if recall is not None:
            score = CaseScore(
                case_id=f"m3c-{category[:2]}-{rank}",
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
            case("multi_hop", 0.5, 2),
            case("multi_hop", 1.0, 1),
            case("simple_lookup", 1.0, 1),
            case("absent", None, 1),
        )
    )

    metrics = AG.category_metrics(evaluation)

    assert set(metrics) == {"multi_hop", "simple_lookup"}
    assert metrics["multi_hop"]["scored_case_count"] == 2.0
    assert metrics["multi_hop"]["recall_at_k"] == pytest.approx(0.75)
    assert metrics["multi_hop"]["mrr"] == pytest.approx(0.75)
    assert metrics["simple_lookup"]["recall_at_k"] == pytest.approx(1.0)
