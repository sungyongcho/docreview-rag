"""Query decomposition: contract, fallback, and n-list fusion."""

import asyncio
from decimal import Decimal
import sys
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from app.agent.decompose import (
    QueryDecomposition,
    decompose_query,
    make_decomposed_retriever,
    merge_ranked_lists,
)
from app.llm.provider import DeterministicLLMProvider
from app.llm.schemas import ProviderBudget, RawProviderResponse, TokenPricing
from app.retrieval.types import ChunkHit
from tests.retrieval.support import hit_values


def budget():
    """Build one provider budget for a decomposition call."""
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
    """Build one raw provider response carrying the given output text."""
    return RawProviderResponse(
        output_text=output_text,
        input_tokens=10,
        output_tokens=5,
        request_id="req-1",
        refusal=None,
    )


def hit(chunk_id, *, score=0.5):
    """Build one retrieval hit with offsets derived from its chunk id."""
    start = chunk_id * 100
    return ChunkHit(
        **hit_values(chunk_id=chunk_id, score=score, start_char=start, end_char=start + 50)
    )


def test_decomposition_contract_rejects_duplicates_and_overflow():
    """Require two to four distinct sub-questions, rejecting repeats and overflow."""
    QueryDecomposition(sub_questions=("What was 2023 revenue?", "What was 2024 revenue?"))

    with pytest.raises(ValidationError):
        QueryDecomposition(sub_questions=())
    with pytest.raises(ValidationError):
        QueryDecomposition(sub_questions=("Same question?", "same   QUESTION?"))
    with pytest.raises(ValidationError):
        QueryDecomposition(sub_questions=tuple(f"Question {index}?" for index in range(5)))


def test_decompose_query_returns_sub_questions_and_falls_back_on_failure():
    """Return the parsed sub-questions, falling back to the original on refusal."""
    provider = DeterministicLLMProvider(
        [raw('{"sub_questions":["What was 2023 revenue?","What was 2024 revenue?"]}')]
    )
    sub_questions = asyncio.run(
        decompose_query(
            "How did revenue change between 2023 and 2024?",
            llm_provider=provider,
            provider_budget=budget(),
        )
    )
    assert sub_questions == ("What was 2023 revenue?", "What was 2024 revenue?")

    refusing = DeterministicLLMProvider([raw("not json"), raw("still not json")])
    fallback = asyncio.run(
        decompose_query(
            "How did revenue change between 2023 and 2024?",
            llm_provider=refusing,
            provider_budget=budget(),
        )
    )
    assert fallback == ("How did revenue change between 2023 and 2024?",)


def test_merge_ranked_lists_rewards_cross_list_agreement():
    """Rank a hit both lists returned above one only a single list found."""
    first = (hit(1), hit(2))
    second = (hit(2), hit(3))

    fused = merge_ranked_lists((first, second), 3, rrf_k=60)

    assert [item.chunk_id for item in fused] == [2, 1, 3]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    with pytest.raises(ValueError):
        merge_ranked_lists((first,), 0)


def test_merge_ranked_lists_ignores_intra_list_duplicates_and_rejects_identity_drift():
    """Count a repeat within one list once, and refuse two hits claiming one identity."""
    first = hit(1)
    second = hit(2)

    fused = merge_ranked_lists(((first, first, second),), 2, rrf_k=60)

    assert [item.chunk_id for item in fused] == [1, 2]
    assert fused[0].score == pytest.approx(1 / 61)
    conflicting = first.model_copy(update={"doc_id": "OTHER"})
    with pytest.raises(ValueError, match="conflicting source identity"):
        merge_ranked_lists(((first,), (conflicting,)), 1)


def test_decomposed_retriever_merges_per_sub_question_rankings(monkeypatch):
    """Retrieve once per sub-question and merge the rankings, closing each read."""
    provider = DeterministicLLMProvider(
        [raw('{"sub_questions":["What was 2023 revenue?","What was 2024 revenue?"]}')]
    )
    queries = []

    class FakeSession:
        """Session recording how many read transactions were closed."""

        def __init__(self):
            self.transaction_open = False
            self.rollback_count = 0

        def in_transaction(self):
            """Report whether this fake session currently holds a transaction."""
            return self.transaction_open

        async def rollback(self):
            """Close the transaction and count the rollback."""
            self.transaction_open = False
            self.rollback_count += 1

    session = FakeSession()

    async def fake_retrieve(received_session, query, **kwargs):
        """Record the query and return the staged hits for it."""
        received_session.transaction_open = True
        queries.append(query)
        ranked = {
            ("What was 2023 revenue?"): (hit(1), hit(2)),
            "What was 2024 revenue?": (hit(2), hit(3)),
        }[query]
        return SimpleNamespace(hits=ranked)

    module = sys.modules[make_decomposed_retriever.__module__]
    monkeypatch.setattr(module, "retrieve", fake_retrieve)
    retriever = make_decomposed_retriever(
        session,
        llm_provider=provider,
        provider_budget=budget(),
    )
    hits = asyncio.run(retriever("How did revenue change between 2023 and 2024?", 2))

    assert queries == ["What was 2023 revenue?", "What was 2024 revenue?"]
    assert [item.chunk_id for item in hits] == [2, 1]
    assert session.rollback_count == 2
