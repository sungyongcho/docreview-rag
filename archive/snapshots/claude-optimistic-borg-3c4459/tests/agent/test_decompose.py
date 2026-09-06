"""Query decomposition: contract, fallback signalling, and the fused retriever."""

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
)
from app.llm.provider import DeterministicLLMProvider
from app.llm.schemas import ProviderBudget, RawProviderResponse, TokenPricing
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.agent.support import FakeSessionFactory, hit


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


def test_decomposition_contract_accepts_one_to_four_distinct_sub_questions():
    """Accept one to four distinct sub-questions, rejecting repeats and overflow."""
    QueryDecomposition(sub_questions=("What was 2023 revenue?",))
    QueryDecomposition(sub_questions=("What was 2023 revenue?", "What was 2024 revenue?"))

    with pytest.raises(ValidationError):
        QueryDecomposition(sub_questions=())
    with pytest.raises(ValidationError):
        QueryDecomposition(sub_questions=("Same question?", "same   QUESTION?"))
    with pytest.raises(ValidationError):
        QueryDecomposition(sub_questions=tuple(f"Question {index}?" for index in range(5)))


def test_decompose_query_returns_sub_questions_and_names_the_fallback_cause():
    """Return the parsed sub-questions, and carry the provider status on fallback."""
    provider = DeterministicLLMProvider(
        [raw('{"sub_questions":["What was 2023 revenue?","What was 2024 revenue?"]}')]
    )
    decomposition = asyncio.run(
        decompose_query(
            "How did revenue change between 2023 and 2024?",
            llm_provider=provider,
            provider_budget=budget(),
        )
    )
    assert decomposition.sub_questions == ("What was 2023 revenue?", "What was 2024 revenue?")
    assert decomposition.fallback_status is None

    refusing = DeterministicLLMProvider([raw("not json"), raw("still not json")])
    fallback = asyncio.run(
        decompose_query(
            "How did revenue change between 2023 and 2024?",
            llm_provider=refusing,
            provider_budget=budget(),
        )
    )
    assert fallback.sub_questions == ("How did revenue change between 2023 and 2024?",)
    assert fallback.fallback_status is not None


def test_decomposed_retriever_gathers_per_sub_question_sessions_and_fuses(monkeypatch):
    """Retrieve each sub-question over its own session and fuse the rankings."""
    provider = DeterministicLLMProvider(
        [raw('{"sub_questions":["What was 2023 revenue?","What was 2024 revenue?"]}')]
    )
    queries = []

    async def fake_retrieve(session, query, **kwargs):
        """Record the query and return the staged hits for it."""
        session.transaction_open = True
        queries.append(query)
        ranked = {
            "What was 2023 revenue?": (hit(1), hit(2)),
            "What was 2024 revenue?": (hit(2), hit(3)),
        }[query]
        return SimpleNamespace(hits=ranked)

    module = sys.modules[make_decomposed_retriever.__module__]
    monkeypatch.setattr(module, "retrieve", fake_retrieve)
    factory = FakeSessionFactory()
    retriever = make_decomposed_retriever(
        factory,
        llm_provider=provider,
        provider_budget=budget(),
        embedding_provider=DeterministicEmbeddingProvider(),
    )
    hits = asyncio.run(retriever("How did revenue change between 2023 and 2024?", 2))

    assert sorted(queries) == ["What was 2023 revenue?", "What was 2024 revenue?"]
    assert [item.chunk_id for item in hits] == [2, 1]
    assert len(factory.sessions) == 2
    assert all(session.closed for session in factory.sessions)
    assert all(not session.in_transaction() for session in factory.sessions)


def test_decomposed_retriever_logs_a_degraded_decomposition(monkeypatch, caplog):
    """Warn with the provider status when retrieval degrades to the original question."""
    refusing = DeterministicLLMProvider([raw("not json"), raw("still not json")])
    original = "How did revenue change between 2023 and 2024?"

    async def fake_retrieve(session, query, **kwargs):
        """Return one staged hit for the fallback query."""
        assert query == original
        return SimpleNamespace(hits=(hit(1),))

    module = sys.modules[make_decomposed_retriever.__module__]
    monkeypatch.setattr(module, "retrieve", fake_retrieve)
    retriever = make_decomposed_retriever(
        FakeSessionFactory(),
        llm_provider=refusing,
        provider_budget=budget(),
        embedding_provider=DeterministicEmbeddingProvider(),
    )

    with caplog.at_level("WARNING", logger="app.agent.decompose"):
        hits = asyncio.run(retriever(original, 1))

    assert [item.chunk_id for item in hits] == [1]
    assert any("fell back" in record.getMessage() for record in caplog.records)
