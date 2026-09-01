"""Tool-calling providers: deterministic queue and the OpenAI adapter."""

import asyncio
import sys
from types import SimpleNamespace
from typing import cast

from openai import AsyncOpenAI
from pydantic import ValidationError
import pytest

from app.agent.provider import DeterministicToolProvider, OpenAIToolProvider
from app.agent.types import ToolCall
from tests.agent.support import turn


class FakeResponses:
    """Responses endpoint returning one staged reply and recording each call."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        """Return the staged response, recording the arguments it was called with."""
        self.calls.append(kwargs)
        return self.response


def openai_provider(response):
    """Build the OpenAI adapter around one staged response."""
    responses = FakeResponses(response)
    provider = OpenAIToolProvider(
        model_name="gpt-5.6-terra",
        client=cast(AsyncOpenAI, SimpleNamespace(responses=responses)),
    )
    return provider, responses


def test_deterministic_provider_replays_turns_and_records_requests():
    """Replay the queued turn, record the request, and fail once the queue is empty."""
    provider = DeterministicToolProvider([turn()])

    result = asyncio.run(
        provider.turn("instructions", [{"role": "user", "content": "q"}], [], max_output_tokens=50)
    )

    assert result.input_tokens == 10
    assert provider.requests == (("instructions", ({"role": "user", "content": "q"},), ()),)
    with pytest.raises(RuntimeError, match="queue is empty"):
        asyncio.run(provider.turn("instructions", [], [], max_output_tokens=50))


def test_openai_adapter_sends_tools_and_parses_function_calls():
    """Send the tool specs unstored and parse the function call back out."""
    response = SimpleNamespace(
        id="resp-1",
        status="completed",
        output_text="Looking at the filings.",
        output=(
            SimpleNamespace(
                type="function_call",
                call_id="call-1",
                name="search_filings",
                arguments='{"query":"revenue"}',
            ),
        ),
        usage=SimpleNamespace(input_tokens=30, output_tokens=12),
    )
    provider, responses = openai_provider(response)
    specs = [{"type": "function", "name": "search_filings", "parameters": {}, "strict": True}]

    result = asyncio.run(
        provider.turn(
            "instructions",
            [{"role": "user", "content": "q"}],
            specs,
            max_output_tokens=64,
        )
    )

    call = responses.calls[0]
    assert call["tools"] == specs
    assert call["store"] is False
    assert call["max_output_tokens"] == 64
    assert call["reasoning"] == {"effort": "medium"}
    assert result.tool_calls[0].name == "search_filings"
    assert result.tool_calls[0].arguments_json == '{"query":"revenue"}'
    assert result.request_id == "resp-1"
    assert result.incomplete is False


def test_openai_adapter_surfaces_an_incomplete_response():
    """Mark a turn the output ceiling cut off, so the loop can stop instead of nudging."""
    response = SimpleNamespace(
        id="resp-2",
        status="incomplete",
        output_text="The filings sho",
        output=(),
        usage=SimpleNamespace(input_tokens=30, output_tokens=16),
    )
    provider, _ = openai_provider(response)

    result = asyncio.run(provider.turn("instructions", [], [], max_output_tokens=16))

    assert result.incomplete is True
    assert result.tool_calls == ()


def test_openai_adapter_rejects_missing_usage():
    """Refuse a response that reports no token usage."""
    response = SimpleNamespace(id="resp-3", output_text="", output=(), usage=None)
    provider, _ = openai_provider(response)

    with pytest.raises(ValueError, match="token usage"):
        asyncio.run(provider.turn("instructions", [], [], max_output_tokens=10))


def test_provider_turn_rejects_duplicate_call_ids():
    """Reject a turn carrying the same call id twice."""
    duplicate = ToolCall(call_id="same", name="search", arguments_json="{}")

    with pytest.raises(ValidationError, match="unique"):
        turn(tool_calls=(duplicate, duplicate))


def test_openai_adapter_wires_base_url_and_disables_hidden_sdk_retries(monkeypatch):
    """Send traffic to the configured endpoint, retries off, and record it as provenance."""
    captured = {}

    class FakeClient:
        """Client standing in for the SDK, capturing its constructor arguments."""

        base_url = "https://api.openai.com/v1"

        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.responses = SimpleNamespace()

    module = sys.modules[OpenAIToolProvider.__module__]
    monkeypatch.setattr(module, "AsyncOpenAI", FakeClient)

    provider = OpenAIToolProvider(
        model_name="gpt-5.6-terra",
        api_key="sk-test",
        base_url="https://gateway.example/v1",
    )

    assert captured["max_retries"] == 0
    assert captured["base_url"] == "https://gateway.example/v1"
    assert provider.api_url == "https://gateway.example/v1/responses"

    OpenAIToolProvider(model_name="gpt-5.6-terra", api_key="sk-test")
    assert captured["base_url"] is None


def test_openai_adapter_closes_only_the_client_it_owns(monkeypatch):
    """Close the owned connection pool on aclose and leave an injected client alone."""
    closed = []

    class FakeClient:
        """SDK stand-in whose close call is observable."""

        base_url = "https://api.openai.com/v1"

        def __init__(self, **kwargs):
            del kwargs
            self.responses = SimpleNamespace()

        async def close(self):
            """Record that the pool was shut down."""
            closed.append(True)

    module = sys.modules[OpenAIToolProvider.__module__]
    monkeypatch.setattr(module, "AsyncOpenAI", FakeClient)

    owned = OpenAIToolProvider(model_name="gpt-5.6-terra", api_key="sk-test")
    asyncio.run(owned.aclose())
    assert closed == [True]

    injected = OpenAIToolProvider(
        model_name="gpt-5.6-terra",
        client=cast(AsyncOpenAI, SimpleNamespace(responses=SimpleNamespace())),
    )
    asyncio.run(injected.aclose())
    assert closed == [True]
