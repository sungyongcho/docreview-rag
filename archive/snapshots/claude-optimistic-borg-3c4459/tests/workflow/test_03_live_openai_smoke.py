"""Explicitly opt-in live OpenAI workflow smoke test, separate from offline acceptance."""

import asyncio
import os

import pytest

from app.llm.provider import OpenAILLMProvider
from app.observability.types import Budget
from app.workflow.runner import run_workflow
from app.workflow.types import WorkflowRequest
from tests.workflow.support import (
    hit as _hit,
    provider_budget as _provider_budget,
    report_of,
)

LIVE_ENABLED = os.getenv("RUN_OPENAI_WORKFLOW_LIVE") == "1"
LIVE_MODEL = os.getenv("OPENAI_WORKFLOW_MODEL")
LIVE_KEY = os.getenv("OPENAI_API_KEY")


@pytest.mark.skipif(
    not (LIVE_ENABLED and LIVE_MODEL and LIVE_KEY),
    reason="live OpenAI workflow requires explicit flag, model, and credential",
)
def test_opt_in_live_openai_workflow_smoke():
    """Run one real workflow against OpenAI when the opt-in flags are set."""
    assert LIVE_MODEL is not None
    assert LIVE_KEY is not None

    async def retriever(query, k, filters):
        return [_hit(1, body="Revenue increased by ten percent.")]

    request = WorkflowRequest(
        run_id="run-live-smoke",
        query="How much did revenue increase?",
        budget=Budget(),
        provider_budget=_provider_budget(
            max_input_tokens=2_000,
            max_output_tokens=300,
            max_cost_usd="0.02",
        ),
    )
    provider = OpenAILLMProvider(model_name=LIVE_MODEL, api_key=LIVE_KEY)

    async def run():
        """Close the provider's own HTTP client before the loop shuts down."""
        try:
            return await run_workflow(request, retriever=retriever, provider=provider)
        finally:
            await provider.aclose()

    result = asyncio.run(run())

    assert result.status == "ok"
    assert report_of(result)["label"] == "SUPPORTED"
    assert report_of(result)["citations"][0]["chunk_id"] == 1
