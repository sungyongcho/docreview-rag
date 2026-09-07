"""Local structured-output provider protocol tests."""

import asyncio
from decimal import Decimal
import json

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


def test_ollama_request_asks_for_a_window_that_fits_the_budget() -> None:
    """Ollama defaults to a small context and silently drops the overflow.

    Notes
    -----
    A truncated evidence prompt would yield an answer about filings the model never read,
    so the request states the window the caller's budget already assumes.
    """
    sent: list[dict[str, object]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": '{"answer":"hello"}'},
                "prompt_eval_count": 8,
                "eval_count": 3,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    provider = LocalLLMProvider(
        base_url="http://127.0.0.1:11434", model_name="test", protocol="ollama", client=client
    )

    asyncio.run(provider.complete(Prompt(system="s", user="u"), ChatReply, budget()))
    asyncio.run(client.aclose())

    options = sent[0]["options"]
    assert isinstance(options, dict)
    assert options["num_ctx"] == 150, "the window must cover both halves of the budget"
    assert options["num_predict"] == 50
    assert sent[0]["think"] is False, "hidden reasoning would consume the output allowance"


def test_ollama_timing_preserves_attempts_and_omits_unreceived_fields() -> None:
    """Retain nanosecond metrics as milliseconds without inventing absent timings."""
    count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        """Return a malformed first answer and a measured successful repair."""
        nonlocal count
        count += 1
        return httpx.Response(
            200,
            json={
                "message": {"content": "invalid" if count == 1 else '{"answer":"hello"}'},
                "prompt_eval_count": 8,
                "eval_count": 3,
                "load_duration": 1_500_000,
                "eval_duration": 3_000_000,
                "prompt_eval_duration": -10,
            },
        )

    async def exercise() -> None:
        """Exercise the real repair loop over an offline HTTP transport."""
        from app.observability.stages import record_stages, stage, stage_metadata

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = LocalLLMProvider(
                base_url="http://local", model_name="answer", protocol="ollama", client=client
            )
            with record_stages():
                async with stage("grade"):
                    result = await provider.complete(
                        Prompt(system="s", user="u"), ChatReply, budget()
                    )
                recorded = stage_metadata()
        assert result.status == "ok" and result.metadata.retries == 1
        assert [timing.attempt for timing in result.metadata.local_timings] == [1, 2]
        assert result.metadata.local_timings[0].load_duration_ms == 1.5
        assert result.metadata.local_timings[1].eval_duration_ms == 3.0
        assert result.metadata.local_timings[0].prompt_eval_duration_ms is None
        assert result.metadata.local_timings[0].total_duration_ms is None
        assert recorded["model_calls"][0]["attempts"] == 2
        assert recorded["model_calls"][0]["node"] == "grade"
        assert "prompt_eval_duration_ms" not in recorded["model_calls"][0]["local_timings"][0]

    asyncio.run(exercise())


def test_local_provider_refuses_an_oversized_prompt_before_contacting_ollama() -> None:
    """A prompt that cannot fit the 100-token allowance is refused without any request."""
    calls: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "message": {"content": '{"answer":"hello"}'},
                "prompt_eval_count": 8,
                "eval_count": 3,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    provider = LocalLLMProvider(
        base_url="http://127.0.0.1:11434", model_name="test", protocol="ollama", client=client
    )

    result = asyncio.run(
        provider.complete(Prompt(system="s", user="word " * 400), ChatReply, budget())
    )
    asyncio.run(client.aclose())

    assert calls == []
    assert result.status == "budget_exceeded"
    assert result.refusal is not None
    assert getattr(result.refusal, "which", None) == "input_tokens"
    assert getattr(result.refusal, "projected_input_tokens", 0) > 100
    assert result.metadata.input_tokens == 0


def test_ollama_keeps_the_configured_window_when_the_remaining_budget_shrinks() -> None:
    """A configured window is requested unchanged so later calls of a run never reload the model."""
    sent: list[dict[str, object]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": '{"answer":"hello"}'},
                "prompt_eval_count": 8,
                "eval_count": 3,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    provider = LocalLLMProvider(
        base_url="http://127.0.0.1:11434",
        model_name="test",
        protocol="ollama",
        client=client,
        context_window=12_600,
    )

    asyncio.run(provider.complete(Prompt(system="s", user="u"), ChatReply, budget()))
    asyncio.run(client.aclose())

    options = sent[0]["options"]
    assert isinstance(options, dict)
    assert options["num_ctx"] == 12_600
    assert options["num_predict"] == 50
