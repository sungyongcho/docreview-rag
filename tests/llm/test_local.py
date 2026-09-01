"""Local structured-output provider protocol tests."""

import asyncio
from decimal import Decimal

import httpx

from app.llm.local import LocalLLMProvider
from app.llm.schemas import Prompt, ProviderBudget, TokenPricing
from app.workflow.gate import ChatReply


def budget() -> ProviderBudget:
    """Return one zero-cost local provider allowance."""
    return ProviderBudget(
        max_input_tokens=100,
        max_output_tokens=50,
        max_cost_usd=Decimal("0"),
        pricing=TokenPricing(
            input_per_million_usd=Decimal("0"),
            output_per_million_usd=Decimal("0"),
        ),
    )


def test_ollama_native_normalizes_structured_output_and_usage() -> None:
    """Map native message and token counters onto the shared provider contract."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "message": {"content": '{"answer":"hello"}'},
                "prompt_eval_count": 8,
                "eval_count": 3,
            },
        )
    )
    client = httpx.AsyncClient(transport=transport)
    provider = LocalLLMProvider(
        base_url="http://127.0.0.1:11434",
        model_name="test",
        protocol="ollama",
        client=client,
    )

    result = asyncio.run(provider.complete(Prompt(system="s", user="u"), ChatReply, budget()))
    asyncio.run(client.aclose())

    assert result.status == "ok"
    assert result.parsed == ChatReply(answer="hello")
    assert result.metadata.api_url == "local://ollama"
    assert (result.metadata.input_tokens, result.metadata.output_tokens) == (8, 3)


def test_local_provider_fails_closed_when_usage_is_missing() -> None:
    """Reject a schema-shaped answer that cannot be budgeted authoritatively."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"message": {"content": '{"answer":"x"}'}})
    )
    client = httpx.AsyncClient(transport=transport)
    provider = LocalLLMProvider(
        base_url="http://127.0.0.1:11434",
        model_name="test",
        protocol="ollama",
        client=client,
    )

    result = asyncio.run(provider.complete(Prompt(system="s", user="u"), ChatReply, budget()))
    asyncio.run(client.aclose())

    assert result.status == "provider_error"
    assert result.metadata.input_tokens == 0
