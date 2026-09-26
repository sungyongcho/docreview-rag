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


@pytest.mark.parametrize(
    ("details", "reason"),
    [
        pytest.param(None, None, id="no-details"),
        pytest.param(
            SimpleNamespace(reason="max_output_tokens"), "max_output_tokens", id="ceiling"
        ),
        pytest.param(SimpleNamespace(reason="content_filter"), "content_filter", id="filter"),
    ],
)
def test_openai_adapter_surfaces_an_incomplete_response_with_its_reason(details, reason):
    """Mark a cut-off turn and name why it stopped, so the loop can tell a budget stop from a
    provider one instead of nudging a truncated reply."""
    response = SimpleNamespace(
        id="resp-2",
        status="incomplete",
        incomplete_details=details,
        output_text="The filings sho",
        output=(),
        usage=SimpleNamespace(input_tokens=30, output_tokens=16),
    )
    provider, _ = openai_provider(response)

    result = asyncio.run(provider.turn("instructions", [], [], max_output_tokens=16))

    assert result.incomplete is True
    assert result.incomplete_reason == reason
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


def test_openai_adapter_closes_only_the_client_it_owns(monkeypatch):
    """Build the owned client with retries off, record its resolved URL as provenance,
    close it on aclose, and leave an injected client alone."""
    captured = {}
    closed = []

    class FakeClient:
        """SDK stand-in capturing its constructor arguments, with an observable close."""

        base_url = "https://api.openai.com/v1"

        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.responses = SimpleNamespace()

        async def close(self):
            """Record that the pool was shut down."""
            closed.append(True)

    module = sys.modules[OpenAIToolProvider.__module__]
    monkeypatch.setattr(module, "AsyncOpenAI", FakeClient)

    owned = OpenAIToolProvider(model_name="gpt-5.6-terra", api_key="sk-test")
    assert captured["max_retries"] == 0
    assert "base_url" not in captured
    assert owned.api_url == "https://api.openai.com/v1/responses"
    asyncio.run(owned.aclose())
    assert closed == [True]

    injected = OpenAIToolProvider(
        model_name="gpt-5.6-terra",
        client=cast(AsyncOpenAI, SimpleNamespace(responses=SimpleNamespace())),
    )
    asyncio.run(injected.aclose())
    assert closed == [True]


def test_openai_adapter_reports_a_failed_response_as_a_provider_failure():
    """A failed reply is a provider failure, not an empty turn the loop would replay."""
    failed = SimpleNamespace(
        id="resp-failed",
        status="failed",
        error=SimpleNamespace(code="server_error", message="The server had an error."),
        incomplete_details=None,
        output_text="",
        output=(),
        usage=SimpleNamespace(input_tokens=30, output_tokens=0),
    )
    provider, responses = openai_provider(failed)
    with pytest.raises(RuntimeError, match="failed"):
        asyncio.run(provider.turn("instructions", [], [], max_output_tokens=16))
    assert len(responses.calls) == 1
