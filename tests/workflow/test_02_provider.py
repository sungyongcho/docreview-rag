"""M4 async provider, repair, budget, refusal, and OpenAI adapter tests."""

import asyncio
from decimal import Decimal
from inspect import isabstract, iscoroutinefunction
from types import SimpleNamespace

import pytest

from tests.support import need


class TickClock:
    """Deterministic monotonic nanosecond clock with one millisecond ticks."""

    def __init__(self):
        self.value = -1_000_000

    def __call__(self):
        self.value += 1_000_000
        return self.value


def prompt(W):
    return W.Prompt(system="Return one strict evidence decision.", user="What changed?")


def budget(W, **changes):
    values = {
        "max_input_tokens": 1_000,
        "max_output_tokens": 100,
        "max_cost_usd": Decimal("0.10"),
        "pricing": W.TokenPricing(
            input_per_million_usd=Decimal("2"),
            output_per_million_usd=Decimal("10"),
        ),
    }
    values.update(changes)
    return W.ProviderBudget(**values)


def valid_output():
    return (
        '{"label":"SUPPORTED","answer":"Research expense increased.",'
        '"citation_chunk_ids":[7],"reason":"The cited chunk contains the statement."}'
    )


def raw(W, output_text, *, input_tokens=10, output_tokens=5, request_id="req-1", refusal=None):
    return W.RawProviderResponse(
        output_text=output_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        request_id=request_id,
        refusal=refusal,
    )


def test_provider_boundary_is_abstract_and_async(W):
    need(W, "LLMProvider")

    assert isabstract(W.LLMProvider)
    assert iscoroutinefunction(W.LLMProvider.complete)


def test_deterministic_provider_returns_typed_output_and_trace_metadata(W):
    need(W, "DeterministicLLMProvider", "AnswerDecision")
    provider = W.DeterministicLLMProvider(
        [raw(W, valid_output(), input_tokens=100, output_tokens=20)],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(W), W.AnswerDecision, budget(W)))

    assert result.status == "ok"
    assert result.parsed.label == "SUPPORTED"
    assert result.refusal is None
    assert result.metadata.provider == "deterministic"
    assert result.metadata.model_name == "deterministic-mock"
    assert result.metadata.api_url == "deterministic://local"
    assert result.metadata.input_tokens == 100
    assert result.metadata.output_tokens == 20
    assert result.metadata.estimated_cost_usd == Decimal("0.0004")
    assert result.metadata.request_time_ms == 1.0
    assert result.metadata.retries == 0
    assert result.metadata.request_ids == ("req-1",)
    assert result.metadata.llm_output == valid_output()


def test_schema_failure_repairs_once_with_errors_and_remaining_budget(W):
    need(W, "DeterministicLLMProvider", "AnswerDecision")
    provider = W.DeterministicLLMProvider(
        [
            raw(W, '{"label":"SUPPORTED"}', input_tokens=10, output_tokens=5),
            raw(
                W,
                valid_output(),
                input_tokens=15,
                output_tokens=5,
                request_id="req-2",
            ),
        ],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(W), W.AnswerDecision, budget(W)))

    assert result.status == "ok"
    assert result.metadata.retries == 1
    assert result.metadata.input_tokens == 25
    assert result.metadata.output_tokens == 10
    assert result.metadata.request_time_ms == 2.0
    assert len(provider.prompts) == 2
    assert "failed validation" in provider.prompts[1].user
    assert "Field required" in provider.prompts[1].user
    assert '{"label":"SUPPORTED"}' in provider.prompts[1].user
    assert provider.budgets[1].max_input_tokens == 990
    assert provider.budgets[1].max_output_tokens == 95


def test_second_schema_failure_returns_typed_rejection_without_third_call(W):
    need(W, "DeterministicLLMProvider", "AnswerDecision", "SchemaRejected")
    provider = W.DeterministicLLMProvider(
        [raw(W, "not-json"), raw(W, "{}", request_id="req-2")],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(W), W.AnswerDecision, budget(W)))

    assert result.status == "schema_rejected"
    assert result.parsed is None
    assert isinstance(result.refusal, W.SchemaRejected)
    assert result.refusal.attempts == 2
    assert result.refusal.errors
    assert result.metadata.retries == 1
    assert len(provider.prompts) == 2


@pytest.mark.parametrize(
    "invalid_output",
    [
        '{"label":"SUPPORTED","label":"NOT_IN_DOCS"}',
        ('{"label":"SUPPORTED","answer":"Evidence.","citation_chunk_ids":[1],"reason":NaN}'),
    ],
)
def test_non_strict_json_is_repaired_instead_of_silently_interpreted(W, invalid_output):
    need(W, "DeterministicLLMProvider", "AnswerDecision")
    provider = W.DeterministicLLMProvider(
        [raw(W, invalid_output), raw(W, valid_output(), request_id="req-2")],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(W), W.AnswerDecision, budget(W)))

    assert result.status == "ok"
    assert result.metadata.retries == 1
    assert "json_invalid" in provider.prompts[1].user


def test_repair_does_not_start_after_the_first_attempt_exhausts_budget(W):
    need(W, "DeterministicLLMProvider", "AnswerDecision", "BudgetExceeded")
    provider = W.DeterministicLLMProvider(
        [raw(W, "{}", input_tokens=10, output_tokens=5)],
        clock=TickClock(),
    )

    result = asyncio.run(
        provider.complete(
            prompt(W),
            W.AnswerDecision,
            budget(W, max_input_tokens=10),
        )
    )

    assert result.status == "budget_exceeded"
    assert isinstance(result.refusal, W.BudgetExceeded)
    assert result.refusal.which == "input_tokens"
    assert result.refusal.used == result.refusal.limit == 10
    assert len(provider.prompts) == 1


def test_explicit_model_refusal_is_typed_and_not_repaired(W):
    need(W, "DeterministicLLMProvider", "AnswerDecision", "ProviderRefusal")
    provider = W.DeterministicLLMProvider(
        [raw(W, "", refusal="I cannot provide that output.")],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(W), W.AnswerDecision, budget(W)))

    assert result.status == "provider_refused"
    assert isinstance(result.refusal, W.ProviderRefusal)
    assert result.refusal.attempts == 1
    assert result.metadata.retries == 0
    assert len(provider.prompts) == 1


@pytest.mark.parametrize(
    ("budget_changes", "response_changes", "which"),
    [
        ({"max_input_tokens": 9}, {"input_tokens": 10}, "input_tokens"),
        ({"max_output_tokens": 4}, {"output_tokens": 5}, "output_tokens"),
        (
            {"max_cost_usd": Decimal("0.00001")},
            {"input_tokens": 10, "output_tokens": 5},
            "estimated_cost_usd",
        ),
    ],
)
def test_explicit_usage_and_cost_budgets_fail_closed(W, budget_changes, response_changes, which):
    need(W, "DeterministicLLMProvider", "AnswerDecision", "BudgetExceeded")
    response = {"output_text": valid_output(), **response_changes}
    provider = W.DeterministicLLMProvider(
        [raw(W, **response)],
        clock=TickClock(),
    )

    result = asyncio.run(
        provider.complete(prompt(W), W.AnswerDecision, budget(W, **budget_changes))
    )

    assert result.status == "budget_exceeded"
    assert isinstance(result.refusal, W.BudgetExceeded)
    assert result.refusal.which == which
    assert result.parsed is None


def test_provider_exception_becomes_typed_error_without_fake_usage(W):
    need(W, "DeterministicLLMProvider", "AnswerDecision", "ProviderRefusal")
    provider = W.DeterministicLLMProvider([], clock=TickClock())

    result = asyncio.run(provider.complete(prompt(W), W.AnswerDecision, budget(W)))

    assert result.status == "provider_error"
    assert isinstance(result.refusal, W.ProviderRefusal)
    assert "response queue is empty" in result.refusal.message
    assert result.metadata.input_tokens == 0
    assert result.metadata.output_tokens == 0
    assert result.metadata.raw_outputs == ("",)


def test_provider_boundary_rejects_untyped_prompt_budget_and_mock_responses(W):
    need(W, "DeterministicLLMProvider", "AnswerDecision")
    with pytest.raises(TypeError):
        W.DeterministicLLMProvider([valid_output()])

    provider = W.DeterministicLLMProvider([raw(W, valid_output())])
    with pytest.raises(TypeError):
        asyncio.run(provider.complete({"system": "s", "user": "u"}, W.AnswerDecision, budget(W)))
    with pytest.raises(TypeError):
        asyncio.run(provider.complete(prompt(W), W.AnswerDecision, {"max_output_tokens": 10}))


class FakeResponses:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response):
        self.responses = FakeResponses(response)


def test_openai_adapter_sends_one_schema_bound_request_with_injected_offline_client(W):
    need(W, "OpenAILLMProvider", "AnswerDecision")
    parsed = W.AnswerDecision.model_validate_json(valid_output(), strict=True)
    response = SimpleNamespace(
        id="resp-123",
        output_parsed=parsed,
        output_text=valid_output(),
        output=(),
        usage=SimpleNamespace(input_tokens=30, output_tokens=12),
    )
    client = FakeClient(response)
    provider = W.OpenAILLMProvider(
        model_name="test-structured-model",
        client=client,
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(W), W.AnswerDecision, budget(W)))

    assert result.status == "ok"
    assert result.metadata.provider == "openai"
    assert result.metadata.request_ids == ("resp-123",)
    assert len(client.responses.calls) == 1
    call = dict(client.responses.calls[0])
    # The schema may be bound as the M4.1 SDK-parsed text_format or as the M4.4
    # strict text.format payload; either stage must bind exactly one mechanism.
    mechanisms = [key for key in ("text_format", "text") if key in call]
    assert len(mechanisms) == 1
    call.pop(mechanisms[0])
    assert call == {
        "model": "test-structured-model",
        "instructions": "Return one strict evidence decision.",
        "input": "What changed?",
        "max_output_tokens": 100,
        "store": False,
    }


def test_openai_adapter_maps_structured_refusal_without_network_or_retry(W):
    need(W, "OpenAILLMProvider", "AnswerDecision", "ProviderRefusal")
    refusal = SimpleNamespace(type="refusal", refusal="Request refused by the model.")
    response = SimpleNamespace(
        id="resp-refused",
        output_parsed=None,
        output_text="",
        output=(SimpleNamespace(content=(refusal,)),),
        usage=SimpleNamespace(input_tokens=8, output_tokens=0),
    )
    client = FakeClient(response)
    provider = W.OpenAILLMProvider(
        model_name="test-structured-model",
        client=client,
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(W), W.AnswerDecision, budget(W)))

    assert result.status == "provider_refused"
    assert isinstance(result.refusal, W.ProviderRefusal)
    assert result.refusal.message == "Request refused by the model."
    assert len(client.responses.calls) == 1


def test_openai_adapter_rejects_missing_usage_as_typed_provider_error(W):
    need(W, "OpenAILLMProvider", "AnswerDecision", "ProviderRefusal")
    response = SimpleNamespace(
        id="resp-no-usage",
        output_parsed=None,
        output_text=valid_output(),
        output=(),
        usage=None,
    )
    client = FakeClient(response)
    provider = W.OpenAILLMProvider(
        model_name="test-structured-model",
        client=client,
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(W), W.AnswerDecision, budget(W)))

    assert result.status == "provider_error"
    assert isinstance(result.refusal, W.ProviderRefusal)
    assert "token usage" in result.refusal.message
    assert result.metadata.input_tokens == 0
    assert result.metadata.output_tokens == 0
