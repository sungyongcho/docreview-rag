"""Local structured-output provider protocol tests."""

import asyncio
from collections.abc import Callable
from decimal import Decimal
import json

import httpx
import pytest

from app.llm.local import LocalLlmProtocol, LocalLLMProvider
from app.llm.schemas import Prompt, ProviderBudget, ProviderRefusal, ProviderResult, TokenPricing
from tests.llm.support import ChatReply


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


def complete_locally(
    respond: Callable[[httpx.Request], httpx.Response],
    *,
    protocol: LocalLlmProtocol,
    base_url: str,
) -> ProviderResult[ChatReply]:
    """Run one completion over an offline transport that answers with ``respond``."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = LocalLLMProvider(
        base_url=base_url, model_name="local-model", protocol=protocol, client=client
    )
    result = asyncio.run(provider.complete(Prompt(system="s", user="u"), ChatReply, budget()))
    asyncio.run(client.aclose())
    return result


def responses_payload(*content: dict[str, object]) -> dict[str, object]:
    """Build one Responses wire object whose single assistant message carries ``content``."""
    return {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": list(content),
            }
        ],
        "usage": {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11},
    }


@pytest.mark.parametrize(("context_window", "expected_num_ctx"), [(None, 150), (12_600, 12_600)])
def test_ollama_request_states_its_window_and_maps_the_native_reply(
    context_window, expected_num_ctx
) -> None:
    """Ask Ollama for the budget's window, or the configured run-wide one, and map its reply.
    Ollama drops overflow past its default window and reloads the model when the window changes.
    """
    sent: list[dict[str, object]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        """Record the request body and answer with a structured reply and token counters."""
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
        context_window=context_window,
    )

    result = asyncio.run(provider.complete(Prompt(system="s", user="u"), ChatReply, budget()))
    asyncio.run(client.aclose())

    options = sent[0]["options"]
    assert isinstance(options, dict)
    # The window must cover both halves of the budget, or be the configured run-wide window.
    assert options["num_ctx"] == expected_num_ctx
    assert options["num_predict"] == 50
    assert sent[0]["think"] is False, "hidden reasoning would consume the output allowance"
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


@pytest.mark.parametrize(
    ("setting", "message"),
    [
        pytest.param({"timeout_s": 0}, "timeout must be positive", id="zero-timeout"),
        pytest.param(
            {"context_window": 0}, "context window must be positive", id="zero-context-window"
        ),
    ],
)
def test_provider_refuses_a_nonpositive_timeout_or_context_window(setting, message) -> None:
    """A CPU-hosted model needs a real deadline, and a window must be able to hold a prompt."""
    with pytest.raises(ValueError, match=message):
        LocalLLMProvider(
            base_url="http://ollama:11434",
            model_name="gemma4:e4b",
            protocol="ollama",
            api_key=None,
            **setting,
        )


def test_responses_wire_payload_is_read_from_its_output_items() -> None:
    """The Responses wire format carries text only inside ``output[].content[]``, so a
    spec-shaped local server answers with status ``ok`` and its reported usage."""
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Record the request and answer with the documented Responses object."""
        sent.append(request)
        return httpx.Response(
            200,
            json=responses_payload(
                {"type": "output_text", "text": '{"answer":"hello"}', "annotations": []}
            ),
        )

    result = complete_locally(
        respond, protocol="openai_responses", base_url="http://127.0.0.1:8000/v1"
    )

    assert sent[0].url.path == "/v1/responses"
    assert result.status == "ok", result.refusal
    assert result.parsed == ChatReply(answer="hello")
    assert result.metadata.api_url == "local://openai-compatible"
    assert result.metadata.request_ids == ("resp_1",)
    assert (result.metadata.input_tokens, result.metadata.output_tokens) == (8, 3)


def test_responses_refusal_item_becomes_a_typed_provider_refusal() -> None:
    """A ``refusal`` content part is the model declining, not a malformed payload."""
    result = complete_locally(
        lambda request: httpx.Response(
            200, json=responses_payload({"type": "refusal", "refusal": "I cannot help with that."})
        ),
        protocol="openai_responses",
        base_url="http://127.0.0.1:8000/v1",
    )

    assert result.status == "provider_refused", result.refusal
    assert isinstance(result.refusal, ProviderRefusal)
    assert result.refusal.message == "I cannot help with that."
    assert result.refusal.attempts == 1
    assert result.metadata.requests == 1


def test_responses_top_level_output_text_is_still_accepted() -> None:
    """A server that adds the SDK's convenience field, and nothing else, is still read."""
    result = complete_locally(
        lambda request: httpx.Response(
            200,
            json={
                "id": "resp_2",
                "output_text": '{"answer":"hello"}',
                "usage": {"input_tokens": 8, "output_tokens": 3},
            },
        ),
        protocol="openai_responses",
        base_url="http://127.0.0.1:8000/v1",
    )

    assert result.status == "ok", result.refusal
    assert result.parsed == ChatReply(answer="hello")


def test_responses_payload_without_text_or_refusal_fails_closed() -> None:
    """An answer carrying neither text nor a refusal is a provider error, not a repair."""
    result = complete_locally(
        lambda request: httpx.Response(
            200,
            json={
                "id": "resp_3",
                "status": "incomplete",
                "output": [{"type": "reasoning", "id": "rs_1", "summary": []}],
                "usage": {"input_tokens": 8, "output_tokens": 3},
            },
        ),
        protocol="openai_responses",
        base_url="http://127.0.0.1:8000/v1",
    )

    assert result.status == "provider_error"
    assert isinstance(result.refusal, ProviderRefusal)
    assert "output text" in result.refusal.message


@pytest.mark.parametrize("protocol", ["ollama", "openai_responses"])
def test_http_status_failure_names_its_kind_and_never_the_private_endpoint(
    protocol: LocalLlmProtocol,
) -> None:
    """The server address is an admin-only setting and the refusal message reaches the
    public failure details and the persisted trace, so a 503 is reported by its kind."""
    base = "http://192.168.50.7:11434"

    result = complete_locally(
        lambda request: httpx.Response(503, json={"error": "model is loading"}),
        protocol=protocol,
        base_url=base,
    )

    assert result.status == "provider_error"
    assert isinstance(result.refusal, ProviderRefusal)
    assert base not in result.refusal.message
    assert "192.168.50.7" not in result.refusal.message
    assert "http_503" in result.refusal.message
    assert result.metadata.api_url.startswith("local://")


def test_transport_failure_is_reported_by_its_kind_only() -> None:
    """A timeout on the way to the server is described as a timeout and nothing more."""

    def time_out(request: httpx.Request) -> httpx.Response:
        """Fail the connection attempt the way httpx reports a connect timeout."""
        raise httpx.ConnectTimeout("timed out", request=request)

    result = complete_locally(time_out, protocol="ollama", base_url="http://192.168.50.7:11434")

    assert result.status == "provider_error"
    assert isinstance(result.refusal, ProviderRefusal)
    assert result.refusal.message == "ValueError: local model server request failed: timeout"
