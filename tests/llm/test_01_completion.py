"""Typed generation, bounded repair, budget refusal, and strict schema decoding."""

import asyncio
from decimal import Decimal
import json
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field
import pytest

from app.llm.completion import BilledAttemptAllowanceError
from app.llm.decoding import strict_response_format
import app.llm.openai as provider_module
from app.llm.openai import OpenAILLMProvider
from app.llm.schemas import (
    AnswerDecision,
    BudgetExceeded,
    Prompt,
    ProviderBudget,
    ProviderMetadata,
    ProviderRefusal,
    RelevanceJudgment,
    SchemaRejected,
    TokenPricing,
)
from app.release.ai_allowance import AIAllowanceError, SharedAIAllowance, active_allowance
from tests.llm.support import DeterministicLLMProvider, TickClock, raw


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


def test_deterministic_provider_returns_typed_output_and_trace_metadata():
    """Return a typed output together with the metadata a trace needs."""
    provider = DeterministicLLMProvider(
        [raw(valid_output(), input_tokens=100, output_tokens=20)],
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "ok"
    assert result.parsed is not None
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
    # Nothing failed validation before the refusal, so the schema evidence stays empty.
    assert result.refusal.schema_errors == ()
    assert result.parsed is None


class FakeResponses:
    """Record one request and return a scenario-owned response."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    async def create(self, **kwargs):
        """Record the arguments and return the staged response."""
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    """Expose the responses surface the OpenAI adapter calls."""

    def __init__(self, response):
        self.responses = FakeResponses(response)


class UnreachableResponses:
    """Fail the test if the adapter sends anything after refusing the call."""

    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        """Record the arguments and fail: a refused request must never be sent."""
        self.calls.append(kwargs)
        raise AssertionError("a refused request must not be sent")


def test_openai_adapter_sends_one_schema_bound_request_with_injected_offline_client():
    """Exercise SDK serialization and response decoding through an offline HTTP transport."""
    requests = []

    def respond(request):
        """Return the wire format consumed by the installed Responses SDK."""
        assert request.method == "POST"
        assert request.url.path == "/v1/responses"
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp-123",
                "object": "response",
                "status": "completed",
                "model": "gpt-5.6-terra",
                "created_at": 0,
                "output": [
                    {
                        "id": "message-1",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": valid_output(), "annotations": []}
                        ],
                    }
                ],
                "usage": {"input_tokens": 30, "output_tokens": 12, "total_tokens": 42},
            },
        )

    async def generate():
        """Own the offline SDK client for the full completion lifecycle."""
        async with AsyncOpenAI(
            api_key="offline-test-key",
            base_url="https://openai.test/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        ) as client:
            provider = OpenAILLMProvider(
                model_name="gpt-5.6-terra", client=client, clock=TickClock()
            )
            return await provider.complete(prompt(), AnswerDecision, budget())

    result = asyncio.run(generate())

    assert result.status == "ok"
    assert result.metadata.provider == "openai"
    assert result.metadata.request_ids == ("resp-123",)
    assert (result.metadata.input_tokens, result.metadata.output_tokens) == (30, 12)
    assert len(requests) == 1
    call = requests[0]
    assert call.pop("text") == {"format": strict_response_format(AnswerDecision)}
    assert call == {
        "model": "gpt-5.6-terra",
        "instructions": "Return one strict evidence decision.",
        "input": "What changed?",
        "reasoning": {"effort": "medium"},
        "max_output_tokens": 100,
        "store": False,
    }


def test_openai_adapter_maps_structured_refusal_without_network_or_retry():
    """Map a structured refusal without retrying or reaching the network."""
    refusal = SimpleNamespace(type="refusal", refusal="Request refused by the model.")
    response = SimpleNamespace(
        id="resp-refused",
        output_text="",
        output=(SimpleNamespace(content=(refusal,)),),
        usage=SimpleNamespace(input_tokens=8, output_tokens=0),
    )
    client = FakeClient(response)
    provider = OpenAILLMProvider(
        model_name="gpt-5.6-terra",
        client=client,
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "provider_refused"
    assert isinstance(result.refusal, ProviderRefusal)
    assert result.refusal.message == "Request refused by the model."
    assert result.refusal.attempts == 1
    assert result.metadata.retries == 0
    assert len(client.responses.calls) == 1


def test_openai_adapter_rejects_missing_usage_as_typed_provider_error():
    """Reject a response carrying no usage as a typed provider error."""
    response = SimpleNamespace(
        id="resp-no-usage",
        output_text=valid_output(),
        output=(),
        usage=None,
    )
    client = FakeClient(response)
    provider = OpenAILLMProvider(
        model_name="gpt-5.6-terra",
        client=client,
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "provider_error"
    assert isinstance(result.refusal, ProviderRefusal)
    assert "token usage" in result.refusal.message
    assert result.metadata.input_tokens == 0
    assert result.metadata.output_tokens == 0
    # The failed attempt is recorded as one empty raw output, never as invented usage.
    assert result.metadata.raw_outputs == ("",)


def test_provider_closes_only_the_client_it_opened_itself():
    """Own the shutdown of a self-built client and leave an injected one alone."""
    injected = FakeClient(SimpleNamespace())
    borrower = OpenAILLMProvider(model_name="gpt-5.6-terra", client=injected)

    asyncio.run(borrower.aclose())

    owner = OpenAILLMProvider(model_name="gpt-5.6-terra", api_key="test-key")
    assert owner._owned_client is not None
    assert not owner._owned_client.is_closed()

    asyncio.run(owner.aclose())

    assert owner._owned_client.is_closed()


def test_strict_format_closes_every_object_and_requires_every_key():
    """Close every object and require every key in the strict format."""
    payload = strict_response_format(AnswerDecision)

    assert payload["type"] == "json_schema"
    assert payload["name"] == "AnswerDecision"
    # The OpenAI payload type leaves "strict" optional and types the schema as
    # dict[str, object]; narrow the parts read below.
    assert "strict" in payload
    assert payload["strict"] is True
    schema = payload["schema"]
    assert schema["additionalProperties"] is False
    assert isinstance(schema["properties"], dict)
    assert schema["required"] == list(schema["properties"])

    nested = strict_response_format(RelevanceJudgment)["schema"]
    assert isinstance(nested["$defs"], dict)
    grade = nested["$defs"]["ChunkRelevance"]
    assert grade["additionalProperties"] is False
    assert grade["required"] == list(grade["properties"])
    # The rationale length bound survives the strict rewrite and reaches the provider.
    assert grade["properties"]["reason"]["maxLength"] == 160


def test_strict_format_strips_defaults_and_requires_every_field():
    """Drop defaults, which strict decoding never applies, while requiring the field."""

    class Defaulted(BaseModel):
        """Schema carrying a default, which strict decoding never applies."""

        model_config = ConfigDict(extra="forbid")

        label: str = Field(default="SUPPORTED")

    schema = strict_response_format(Defaulted)["schema"]

    # The OpenAI payload types the schema as dict[str, object]; narrow the part read below.
    assert isinstance(schema["properties"], dict)
    assert "default" not in schema["properties"]["label"]
    assert schema["required"] == ["label"]


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
        model_name="gpt-5.6-terra",
        client=SimpleNamespace(responses=responses),
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert result.status == "ok"
    assert result.metadata.retries == 1
    assert len(responses.calls) == 2
    assert "failed validation" in responses.calls[1]["input"]
    assert responses.calls[1]["text"] == responses.calls[0]["text"]


def test_repair_is_refused_before_the_call_when_the_repair_prompt_would_not_fit():
    """The larger repair prompt passes the same gate and keeps the validation errors."""
    provider = DeterministicLLMProvider(
        [
            raw('{"label":"SUPPORTED"}', input_tokens=500, output_tokens=5),
            raw(valid_output(), input_tokens=15, output_tokens=5, request_id="req-2"),
        ],
        clock=TickClock(),
        projected_input_tokens=lambda p: 700 if "failed validation" in p.user else 300,
    )

    result = asyncio.run(
        provider.complete(prompt(), AnswerDecision, budget(max_input_tokens=1_000))
    )

    assert result.status == "budget_exceeded"
    assert isinstance(result.refusal, BudgetExceeded)
    assert result.refusal.used == 500
    assert result.refusal.attempts == 1
    assert result.refusal.projected_input_tokens == 700
    assert result.refusal.schema_errors
    assert len(provider.prompts) == 1
    assert result.metadata.requests == 1
    assert result.metadata.retries == 0
    assert result.metadata.raw_outputs == ('{"label":"SUPPORTED"}',)


def test_projection_equal_to_the_allowance_is_sent_and_one_token_over_is_refused():
    """The gate compares against the allowance itself: exact fit is sent, one more is not."""
    exact = DeterministicLLMProvider(
        [raw(valid_output(), input_tokens=1_000, output_tokens=20)],
        clock=TickClock(),
        projected_input_tokens=lambda _prompt: 1_000,
    )
    over = DeterministicLLMProvider(
        [raw(valid_output(), input_tokens=1_000, output_tokens=20)],
        clock=TickClock(),
        projected_input_tokens=lambda _prompt: 1_001,
    )

    sent = asyncio.run(exact.complete(prompt(), AnswerDecision, budget(max_input_tokens=1_000)))
    refused = asyncio.run(over.complete(prompt(), AnswerDecision, budget(max_input_tokens=1_000)))

    assert sent.status == "ok"
    assert len(exact.prompts) == 1
    assert sent.metadata.requests == 1
    assert sent.metadata.input_tokens == 1_000
    assert refused.status == "budget_exceeded"
    assert isinstance(refused.refusal, BudgetExceeded)
    assert refused.refusal.projected_input_tokens == 1_001
    assert refused.refusal.attempts == 0
    assert over.prompts == ()
    assert refused.refusal.which == "input_tokens"
    assert refused.refusal.used == 0
    assert refused.refusal.limit == 1_000
    assert refused.metadata.requests == 0
    assert refused.metadata.raw_outputs == ()
    assert refused.metadata.llm_output == ""
    assert refused.metadata.request_ids == ()
    assert refused.metadata.retries == 0
    assert refused.metadata.input_tokens == 0
    assert refused.metadata.request_time_ms == 0
    assert refused.metadata.projected_input_tokens == 1_001


def test_post_hoc_accounting_is_unchanged_when_the_projection_undershoots():
    """An undercounted prompt is sent and the reported usage still trips the post-hoc check."""
    provider = DeterministicLLMProvider(
        [raw(valid_output(), input_tokens=1_100, output_tokens=20)],
        clock=TickClock(),
        projected_input_tokens=lambda _prompt: 900,
    )

    result = asyncio.run(
        provider.complete(prompt(), AnswerDecision, budget(max_input_tokens=1_000))
    )

    assert len(provider.prompts) == 1
    assert result.status == "budget_exceeded"
    assert isinstance(result.refusal, BudgetExceeded)
    assert result.refusal.which == "input_tokens"
    assert result.refusal.used == 1_100
    assert result.refusal.projected_input_tokens is None


def test_openai_preflight_refusal_records_its_projection_in_metadata():
    """The adapter's schema-inclusive preflight reports one projection in the refusal and
    the metadata alike, so model_calls and the failure details tell the same story."""
    responses = UnreachableResponses()
    provider = OpenAILLMProvider(
        model_name="gpt-5.6-terra",
        client=SimpleNamespace(responses=responses),
        clock=TickClock(),
    )

    # The prompt alone fits 100 tokens; the prompt plus the serialized strict schema does not.
    result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget(max_input_tokens=100)))

    assert responses.calls == []
    assert result.status == "budget_exceeded"
    assert isinstance(result.refusal, BudgetExceeded)
    assert result.refusal.which == "input_tokens"
    assert result.refusal.attempts == 0
    assert result.refusal.projected_input_tokens is not None
    assert result.refusal.projected_input_tokens > 100
    assert result.metadata.requests == 0
    assert result.metadata.projected_input_tokens == result.refusal.projected_input_tokens


def test_missing_tokenizer_is_a_pre_call_refusal_that_sent_nothing(monkeypatch, tmp_path):
    """Under the shared allowance the cost preflight needs the tokenizer; without it the
    call is refused before dispatch, sending nothing and naming the local cause."""
    monkeypatch.setattr(
        provider_module, "estimate_prompt_tokens", lambda prompt, *, model_name: None
    )
    responses = UnreachableResponses()
    provider = OpenAILLMProvider(
        model_name="gpt-5.6-terra",
        client=SimpleNamespace(responses=responses),
        clock=TickClock(),
    )
    ledger = SharedAIAllowance(tmp_path / "limits.sqlite3", Decimal("1"), 5, 25)
    token = active_allowance.set(ledger)
    try:
        result = asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))
    finally:
        active_allowance.reset(token)

    assert responses.calls == []
    assert result.status == "provider_error"
    assert isinstance(result.refusal, ProviderRefusal)
    assert result.metadata.requests == 0
    assert result.refusal.attempts == 0
    assert "tokenizer" in result.refusal.message
    assert result.metadata.raw_outputs == ()
    assert result.metadata.llm_output == ""
    assert result.metadata.request_time_ms == 0


class AllowanceCappedProvider(DeterministicLLMProvider):
    """Meter like the shared allowance: deny the request sent after ``deny_after`` others."""

    def __init__(self, responses, *, deny_after):
        super().__init__(responses, clock=TickClock())
        self.deny_after = deny_after
        self.denial = AIAllowanceError("public_daily_limit", "Daily AI allowance reached.", 60)

    async def _request(self, prompt, schema, budget):
        """Deny before the request is sent, as the allowance reservation does."""
        if len(self.prompts) == self.deny_after:
            raise self.denial
        return await super()._request(prompt, schema, budget)


def test_denied_repair_surfaces_the_billed_first_attempt_as_provider_metadata():
    """Raise a denied repair with the metadata of the first attempt, which was billed.

    The error stays an ``AIAllowanceError`` with the original code, message and retry
    delay, so the 429 mapping is unchanged, and its metadata is what a typed failure
    after that attempt would carry, so the caller can trace what was paid for.
    """
    label_only_decision = '{"label":"SUPPORTED"}'
    provider = AllowanceCappedProvider(
        [raw(label_only_decision, input_tokens=10, output_tokens=5)], deny_after=1
    )

    with pytest.raises(AIAllowanceError) as raised:
        asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    denial = raised.value
    assert isinstance(denial, BilledAttemptAllowanceError)
    assert (denial.code, str(denial), denial.retry_after) == (
        "public_daily_limit",
        "Daily AI allowance reached.",
        60,
    )
    assert len(provider.prompts) == 1
    assert denial.metadata == ProviderMetadata(
        provider="deterministic",
        model_name="deterministic-mock",
        api_url="deterministic://local",
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=Decimal("0.00007"),
        request_time_ms=1.0,
        retries=0,
        request_ids=("req-1",),
        llm_output=label_only_decision,
        raw_outputs=(label_only_decision,),
        requests=1,
    )


def test_denied_first_attempt_is_re_raised_unchanged():
    """Re-raise a denial of the first attempt as is: nothing was sent, so nothing was billed."""
    provider = AllowanceCappedProvider([], deny_after=0)

    with pytest.raises(AIAllowanceError) as raised:
        asyncio.run(provider.complete(prompt(), AnswerDecision, budget()))

    assert raised.value is provider.denial
    assert provider.prompts == ()
