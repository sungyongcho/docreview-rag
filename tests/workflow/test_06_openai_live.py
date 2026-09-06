"""Explicitly opt-in live OpenAI workflow smoke test, separate from offline acceptance."""

import asyncio
from decimal import Decimal
import os

import pytest

from app.llm import OpenAILLMProvider, ProviderBudget, TokenPricing
from app.observability import Budget
from app.retrieval import ChunkHit
from tests.support import need

LIVE_ENABLED = os.getenv("RUN_OPENAI_WORKFLOW_LIVE") == "1"
LIVE_MODEL = os.getenv("OPENAI_WORKFLOW_MODEL")
LIVE_KEY = os.getenv("OPENAI_API_KEY")


@pytest.mark.skipif(
    not (LIVE_ENABLED and LIVE_MODEL and LIVE_KEY),
    reason="live OpenAI workflow requires explicit flag, model, and credential",
)
def test_opt_in_live_openai_workflow_smoke(G):
    need(G, "WorkflowRequest", "run_workflow")
    assert LIVE_MODEL is not None
    assert LIVE_KEY is not None
    context = "ACME FY2024 · Item 7"
    hit = ChunkHit(
        chunk_id=1,
        doc_id="ACME-FY2024",
        item="7",
        kind="text",
        citation=context,
        start_char=100,
        end_char=180,
        source_sha256="c" * 64,
        body="Revenue increased by ten percent.",
        context_header=context,
        index_text=f"{context}\n\nRevenue increased by ten percent.",
        score=1.0,
    )

    async def retriever(query, k, filters):
        return [hit]

    provider_budget = ProviderBudget(
        max_input_tokens=2_000,
        max_output_tokens=300,
        max_cost_usd=Decimal("0.02"),
        pricing=TokenPricing(
            input_per_million_usd=Decimal("0.40"),
            output_per_million_usd=Decimal("1.60"),
        ),
    )
    request = G.WorkflowRequest(
        run_id="run-live-smoke",
        query="How much did revenue increase?",
        budget=Budget(),
        provider_budget=provider_budget,
    )
    provider = OpenAILLMProvider(model_name=LIVE_MODEL, api_key=LIVE_KEY)

    result = asyncio.run(G.run_workflow(request, retriever=retriever, provider=provider))

    assert result.status == "ok"
    assert result.report["label"] == "SUPPORTED"
    assert result.report["citations"][0]["chunk_id"] == 1
