"""Typed generation, bounded repair, budget refusal, and strict schema decoding."""

import asyncio
from decimal import Decimal
from inspect import isabstract, iscoroutinefunction
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field
import pytest

from app.llm.provider import (
    DeterministicLLMProvider,
    LLMProvider,
    OpenAILLMProvider,
    strict_response_format,
)
from app.llm.schemas import (
    AnswerDecision,
    BudgetExceeded,
    Prompt,
    ProviderBudget,
    ProviderRefusal,
    RawProviderResponse,
    RelevanceJudgment,
    SchemaRejected,
    TokenPricing,
)


class TickClock:
    """Deterministic monotonic nanosecond clock with one millisecond ticks."""

    def __init__(self):
        self.value = -1_000_000

    def __call__(self):
        self.value += 1_000_000
        return self.value


def prompt():
    """Build the fixed prompt every provider test sends."""
    return Prompt(system="Return one strict evidence decision.", user="What changed?")


def budget(**changes):
    """Build a provider budget with optional replacements."""
    values = {
        "max_input_tokens": 1_000,
        "max_output_tokens": 100,
        "max_cost_usd": Decimal("0.10"),
        "pricing": TokenPricing(
            input_per_million_usd=Decimal("2"),
            output_per_million_usd=Decimal("10"),
        ),
    }
    values.update(changes)
    return ProviderBudget(**values)


def valid_output():
    """Return the JSON text of one valid answer decision."""
    return (
        '{"label":"SUPPORTED","answer":"Research expense increased.",'
        '"citation_chunk_ids":[7],"reason":"The cited chunk contains the statement."}'
    )


def raw(output_text, *, input_tokens=10, output_tokens=5, request_id="req-1", refusal=None):
    """Build one raw provider response with optional usage and refusal."""
    return RawProviderResponse(
        output_text=output_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        request_id=request_id,
        refusal=refusal,
    )


def test_provider_boundary_is_abstract_and_async():
    """Keep the provider boundary abstract with an awaitable generate method."""

    assert isabstract(LLMProvider)
    assert iscoroutinefunction(LLMProvider.complete)


def test_deterministic_provider_returns_typed_output_and_trace_metadata():
    """Return a typed output together with the metadata a trace needs."""
    provider = DeterministicLLMProvider(
        [raw(valid_output(), input_tokens=100, output_tokens=20)],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

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


def test_schema_failure_repairs_once_with_errors_and_remaining_budget():
    """Repair one schema failure using the reported errors and the remaining budget."""
    provider = DeterministicLLMProvider(
        [
            raw('{"label":"SUPPORTED"}', input_tokens=10, output_tokens=5),
            raw(
                valid_output(),
                input_tokens=15,
                output_tokens=5,
                request_id="req-2",
            ),
        ],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

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


def test_second_schema_failure_returns_typed_rejection_without_third_call():
    """Stop after one repair and report a typed rejection."""
    provider = DeterministicLLMProvider(
        [raw("not-json"), raw("{}", request_id="req-2")],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "schema_rejected"
    assert result.parsed is None
    assert isinstance(result.refusal, SchemaRejected)
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
def test_non_strict_json_is_repaired_instead_of_silently_interpreted(invalid_output):
    """Repair loose JSON instead of guessing what it meant."""
    provider = DeterministicLLMProvider(
        [raw(invalid_output), raw(valid_output(), request_id="req-2")],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "ok"
    assert result.metadata.retries == 1
    assert "json_invalid" in provider.prompts[1].user


def test_repair_does_not_start_after_the_first_attempt_exhausts_budget():
    """Skip the repair attempt but still report why the output was unusable."""
    provider = DeterministicLLMProvider(
        [raw("{}", input_tokens=10, output_tokens=5)],
        clock=TickClock(),
    )

    result = asyncio.run(
        provider.complete(
            prompt(),
            AnswerDecision,
            budget(max_input_tokens=10),
        )
    )

    assert result.status == "budget_exceeded"
    assert isinstance(result.refusal, BudgetExceeded)
    assert result.refusal.which == "input_tokens"
    assert result.refusal.used == result.refusal.limit == 10
    assert any("Field required" in error for error in result.refusal.schema_errors)
    assert len(provider.prompts) == 1


def test_budget_refusal_before_any_validation_carries_no_schema_errors():
    """Leave the schema evidence empty when nothing failed validation."""
    provider = DeterministicLLMProvider(
        [raw(valid_output(), input_tokens=10, output_tokens=5)],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget(max_input_tokens=9)))

    assert isinstance(result.refusal, BudgetExceeded)
    assert result.refusal.schema_errors == ()


def test_explicit_model_refusal_is_typed_and_not_repaired():
    """Report a model refusal as typed evidence without repairing it."""
    provider = DeterministicLLMProvider(
        [raw("", refusal="I cannot provide that output.")],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "provider_refused"
    assert isinstance(result.refusal, ProviderRefusal)
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
def test_explicit_usage_and_cost_budgets_fail_closed(budget_changes, response_changes, which):
    """Fail closed when a call would exceed its usage or cost budget."""
    response = {"output_text": valid_output(), **response_changes}
    provider = DeterministicLLMProvider(
        [raw(**response)],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget(**budget_changes)))

    assert result.status == "budget_exceeded"
    assert isinstance(result.refusal, BudgetExceeded)
    assert result.refusal.which == which
    assert result.parsed is None


def test_provider_exception_becomes_typed_error_without_fake_usage():
    """Turn a transport exception into a typed error without inventing usage."""
    provider = DeterministicLLMProvider([], clock=TickClock())

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "provider_error"
    assert isinstance(result.refusal, ProviderRefusal)
    assert "response queue is empty" in result.refusal.message
    assert result.metadata.input_tokens == 0
    assert result.metadata.output_tokens == 0
    assert result.metadata.raw_outputs == ("",)


def test_provider_boundary_rejects_untyped_prompt_budget_and_mock_responses():
    """Reject untyped prompts, budgets, and responses at the boundary."""
    with pytest.raises(TypeError):
        DeterministicLLMProvider([valid_output()])

    provider = DeterministicLLMProvider([raw(valid_output())])
    with pytest.raises(TypeError):
        asyncio.run(provider.complete({"system": "s", "user": "u"}, AnswerDecision, budget()))
    with pytest.raises(TypeError):
        asyncio.run(provider.complete(prompt(), AnswerDecision, {"max_output_tokens": 10}))


class FakeResponses:
    """Record one request and return a scenario-owned response."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        """Record the arguments and return the staged response."""
        self.calls.append(kwargs)
        return self.response

    async def parse(self, **kwargs):
        """Record the arguments and return the staged response."""
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    """Expose the responses surface the OpenAI adapter calls."""

    def __init__(self, response):
        self.responses = FakeResponses(response)


def test_openai_adapter_sends_one_schema_bound_request_with_injected_offline_client():
    """Send exactly one schema-bound request through an injected client."""
    parsed = AnswerDecision.model_validate_json(valid_output(), strict=True)
    response = SimpleNamespace(
        id="resp-123",
        output_parsed=parsed,
        output_text=valid_output(),
        output=(),
        usage=SimpleNamespace(input_tokens=30, output_tokens=12),
    )
    client = FakeClient(response)
    provider = OpenAILLMProvider(
        model_name="test-structured-model",
        client=client,
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

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


def test_openai_adapter_maps_structured_refusal_without_network_or_retry():
    """Map a structured refusal without retrying or reaching the network."""
    refusal = SimpleNamespace(type="refusal", refusal="Request refused by the model.")
    response = SimpleNamespace(
        id="resp-refused",
        output_parsed=None,
        output_text="",
        output=(SimpleNamespace(content=(refusal,)),),
        usage=SimpleNamespace(input_tokens=8, output_tokens=0),
    )
    client = FakeClient(response)
    provider = OpenAILLMProvider(
        model_name="test-structured-model",
        client=client,
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "provider_refused"
    assert isinstance(result.refusal, ProviderRefusal)
    assert result.refusal.message == "Request refused by the model."
    assert len(client.responses.calls) == 1


def test_openai_adapter_rejects_missing_usage_as_typed_provider_error():
    """Reject a response carrying no usage as a typed provider error."""
    response = SimpleNamespace(
        id="resp-no-usage",
        output_parsed=None,
        output_text=valid_output(),
        output=(),
        usage=None,
    )
    client = FakeClient(response)
    provider = OpenAILLMProvider(
        model_name="test-structured-model",
        client=client,
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "provider_error"
    assert isinstance(result.refusal, ProviderRefusal)
    assert "token usage" in result.refusal.message
    assert result.metadata.input_tokens == 0
    assert result.metadata.output_tokens == 0


def test_provider_closes_only_the_client_it_opened_itself():
    """Own the shutdown of a self-built client and leave an injected one alone."""
    injected = FakeClient(SimpleNamespace())
    borrower = OpenAILLMProvider(model_name="test-structured-model", client=injected)

    asyncio.run(borrower.aclose())

    owner = OpenAILLMProvider(model_name="test-structured-model", api_key="test-key")
    assert owner._owned_client is not None
    assert not owner._owned_client.is_closed()

    asyncio.run(owner.aclose())

    assert owner._owned_client.is_closed()


def test_strict_format_closes_every_object_and_requires_every_key():
    """Close every object and require every key in the strict format."""
    payload = strict_response_format(AnswerDecision)

    assert payload["type"] == "json_schema"
    assert payload["name"] == "AnswerDecision"
    assert payload["strict"] is True
    schema = payload["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])

    nested = strict_response_format(RelevanceJudgment)["schema"]
    grade = nested["$defs"]["ChunkRelevance"]
    assert grade["additionalProperties"] is False
    assert grade["required"] == list(grade["properties"])


def test_strict_format_strips_defaults_and_requires_every_field():
    """Drop defaults, which strict decoding never applies, while requiring the field."""

    class Defaulted(BaseModel):
        """Schema carrying a default, which strict decoding never applies."""

        model_config = ConfigDict(extra="forbid")

        label: str = Field(default="SUPPORTED")

    schema = strict_response_format(Defaulted)["schema"]

    assert "default" not in schema["properties"]["label"]
    assert schema["required"] == ["label"]


def test_strict_format_is_deterministic_between_calls():
    """Produce the same strict format on every call."""
    assert strict_response_format(AnswerDecision) == strict_response_format(AnswerDecision)


def test_legacy_flag_keeps_the_sdk_parsed_path():
    """Keep the SDK parsed path reachable behind the legacy flag."""
    parsed = AnswerDecision.model_validate_json(valid_output(), strict=True)
    response = SimpleNamespace(
        id="resp-legacy",
        output_parsed=parsed,
        output_text=valid_output(),
        output=(),
        usage=SimpleNamespace(input_tokens=30, output_tokens=12),
    )
    client = FakeClient(response)
    provider = OpenAILLMProvider(
        model_name="test-structured-model",
        client=client,
        structured_output=False,
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "ok"
    call = client.responses.calls[0]
    assert call["text_format"] is AnswerDecision
    assert "text" not in call


def test_repair_loop_still_guards_the_strict_path():
    """Guard the strict path with the same bounded repair loop."""

    class SequencedResponses:
        """Responses endpoint returning one staged reply per call, in order."""

        def __init__(self, responses):
            self.responses = list(responses)
            self.calls = []

        async def create(self, **kwargs):
            """Record the arguments and return the staged response."""
            self.calls.append(kwargs)
            return self.responses.pop(0)

    invalid = SimpleNamespace(
        id="resp-bad",
        output_text='{"label":"SUPPORTED"}',
        output=(),
        usage=SimpleNamespace(input_tokens=10, output_tokens=4),
    )
    repaired = SimpleNamespace(
        id="resp-good",
        output_text=valid_output(),
        output=(),
        usage=SimpleNamespace(input_tokens=12, output_tokens=8),
    )
    responses = SequencedResponses([invalid, repaired])
    provider = OpenAILLMProvider(
        model_name="test-structured-model",
        client=SimpleNamespace(responses=responses),
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "ok"
    assert result.metadata.retries == 1
    assert len(responses.calls) == 2
    assert "failed validation" in responses.calls[1]["input"]
    assert responses.calls[1]["text"] == responses.calls[0]["text"]
