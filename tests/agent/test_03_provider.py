"""M9.2 tool-calling providers: deterministic queue and the OpenAI adapter."""

import asyncio
import sys
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from tests.support import need


class TickClock:
    """Deterministic monotonic nanosecond clock with one millisecond ticks."""

    def __init__(self):
        self.value = -1_000_000

    def __call__(self):
        self.value += 1_000_000
        return self.value


def turn(AG, **changes):
    values = {
        "output_text": "",
        "tool_calls": (),
        "input_tokens": 10,
        "output_tokens": 5,
    }
    values.update(changes)
    return AG.ProviderTurn(**values)


def test_deterministic_provider_replays_turns_and_records_requests(AG):
    need(AG, "DeterministicToolProvider", "ProviderTurn")
    provider = AG.DeterministicToolProvider([turn(AG)], clock=TickClock())

    result, elapsed_ms = asyncio.run(
        provider.turn("instructions", [{"role": "user", "content": "q"}], [], max_output_tokens=50)
    )

    assert result.input_tokens == 10
    assert elapsed_ms == 1.0
    assert provider.requests == (("instructions", ({"role": "user", "content": "q"},), ()),)
    with pytest.raises(RuntimeError, match="queue is empty"):
        asyncio.run(provider.turn("instructions", [], [], max_output_tokens=50))


def test_openai_adapter_sends_tools_and_parses_function_calls(AG):
    need(AG, "OpenAIToolProvider")

    class FakeResponses:
        def __init__(self, response):
            self.response = response
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return self.response

    response = SimpleNamespace(
        id="resp-1",
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
    responses = FakeResponses(response)
    provider = AG.OpenAIToolProvider(
        model_name="test-agent-model",
        client=SimpleNamespace(responses=responses),
        clock=TickClock(),
    )
    specs = [{"type": "function", "name": "search_filings", "parameters": {}, "strict": True}]

    result, _ = asyncio.run(
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
    assert result.tool_calls[0].name == "search_filings"
    assert result.tool_calls[0].arguments_json == '{"query":"revenue"}'
    assert result.request_id == "resp-1"


def test_openai_adapter_rejects_missing_usage(AG):
    need(AG, "OpenAIToolProvider")

    class FakeResponses:
        async def create(self, **kwargs):
            return SimpleNamespace(id="resp-2", output_text="", output=(), usage=None)

    provider = AG.OpenAIToolProvider(
        model_name="test-agent-model",
        client=SimpleNamespace(responses=FakeResponses()),
        clock=TickClock(),
    )

    with pytest.raises(ValueError, match="token usage"):
        asyncio.run(provider.turn("instructions", [], [], max_output_tokens=10))


def test_provider_turn_rejects_duplicate_call_ids(AG):
    duplicate = AG.ToolCall(call_id="same", name="search", arguments_json="{}")

    with pytest.raises(ValidationError, match="unique"):
        turn(AG, tool_calls=(duplicate, duplicate))


def test_openai_adapter_disables_hidden_sdk_retries(AG, monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.responses = SimpleNamespace()

    module = sys.modules[AG.OpenAIToolProvider.__module__]
    monkeypatch.setattr(module, "AsyncOpenAI", FakeClient)

    AG.OpenAIToolProvider(model_name="test-agent-model", api_key="sk-test")

    assert captured["max_retries"] == 0
