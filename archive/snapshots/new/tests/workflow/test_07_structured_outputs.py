"""M4.4 strict structured-output tests: schema transform, both paths, outer repair."""

import asyncio
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field
import pytest

from tests.support import need
from tests.workflow.test_02_provider import (
    FakeClient,
    TickClock,
    budget,
    prompt,
    valid_output,
)


def test_strict_format_closes_every_object_and_requires_every_key(W):
    need(W, "strict_response_format", "AnswerDecision", "RelevanceJudgment")
    payload = W.strict_response_format(W.AnswerDecision)

    assert payload["type"] == "json_schema"
    assert payload["name"] == "AnswerDecision"
    assert payload["strict"] is True
    schema = payload["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])

    nested = W.strict_response_format(W.RelevanceJudgment)["schema"]
    grade = nested["$defs"]["ChunkRelevance"]
    assert grade["additionalProperties"] is False
    assert grade["required"] == list(grade["properties"])


def test_strict_format_rejects_constructs_decoding_cannot_enforce(W):
    need(W, "strict_response_format")

    class Defaulted(BaseModel):
        model_config = ConfigDict(extra="forbid")

        label: str = Field(default="SUPPORTED")

    with pytest.raises(ValueError, match=r"defaults at \$\.label"):
        W.strict_response_format(Defaulted)


def test_strict_format_is_deterministic_between_calls(W):
    need(W, "strict_response_format", "AnswerDecision")
    assert W.strict_response_format(W.AnswerDecision) == W.strict_response_format(W.AnswerDecision)


def test_legacy_flag_keeps_the_sdk_parsed_path(W):
    need(W, "OpenAILLMProvider", "AnswerDecision")
    parsed = W.AnswerDecision.model_validate_json(valid_output(), strict=True)
    response = SimpleNamespace(
        id="resp-legacy",
        output_parsed=parsed,
        output_text=valid_output(),
        output=(),
        usage=SimpleNamespace(input_tokens=30, output_tokens=12),
    )
    client = FakeClient(response)
    provider = W.OpenAILLMProvider(
        model_name="test-structured-model",
        client=client,
        structured_output=False,
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(W), W.AnswerDecision, budget(W)))

    assert result.status == "ok"
    call = client.responses.calls[0]
    assert call["text_format"] is W.AnswerDecision
    assert "text" not in call


def test_repair_loop_still_guards_the_strict_path(W):
    need(W, "OpenAILLMProvider", "AnswerDecision")

    class SequencedResponses:
        def __init__(self, responses):
            self.responses = list(responses)
            self.calls = []

        async def create(self, **kwargs):
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
    provider = W.OpenAILLMProvider(
        model_name="test-structured-model",
        client=SimpleNamespace(responses=responses),
        clock=TickClock(),
    )

    result = asyncio.run(provider.complete(prompt(W), W.AnswerDecision, budget(W)))

    assert result.status == "ok"
    assert result.metadata.retries == 1
    assert len(responses.calls) == 2
    assert "failed validation" in responses.calls[1]["input"]
    assert responses.calls[1]["text"] == responses.calls[0]["text"]
