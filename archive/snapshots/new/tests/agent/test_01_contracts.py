"""M9.1 strict agent value-object contracts."""

import json

from pydantic import ValidationError
import pytest

from tests.support import need


def usage(AG, **changes):
    values = {
        "model_name": "deterministic-agent",
        "api_url": "deterministic://local",
        "input_tokens": 10,
        "output_tokens": 5,
        "request_time_ms": 1.0,
    }
    values.update(changes)
    return AG.StepUsage(**values)


def call(AG, *, call_id="call-1", name="search_filings", arguments=None):
    return AG.ToolCall(
        call_id=call_id,
        name=name,
        arguments_json=json.dumps(arguments or {"query": "revenue"}),
    )


def supported_answer(AG, *, chunk_id=7):
    return AG.AgentAnswer(
        label="SUPPORTED",
        answer="Revenue increased by ten percent.",
        citations=(
            AG.AgentCitation(
                chunk_id=chunk_id,
                doc_id="NVDA-FY2024",
                citation="NVDA FY2024 · Item 7",
            ),
        ),
        rationale="The cited chunk states the increase.",
    )


def test_observation_keeps_output_and_error_mutually_exclusive(AG):
    need(AG, "Observation")
    AG.Observation(call_id="call-1", name="search_filings", output_json="{}")
    AG.Observation(call_id="call-1", name="search_filings", error="boom")

    with pytest.raises(ValidationError):
        AG.Observation(call_id="call-1", name="search_filings")
    with pytest.raises(ValidationError):
        AG.Observation(call_id="call-1", name="search_filings", output_json="{}", error="boom")


def test_agent_step_rejects_observations_for_unknown_calls(AG):
    need(AG, "AgentStep", "Observation", "ToolCall", "StepUsage")
    with pytest.raises(ValidationError):
        AG.AgentStep(
            step=1,
            output_text="",
            tool_calls=(call(AG),),
            observations=(
                AG.Observation(call_id="other", name="search_filings", output_json="{}"),
            ),
            usage=usage(AG),
        )


def test_answer_label_contract_mirrors_the_m4_rules(AG):
    need(AG, "AgentAnswer", "AgentCitation")
    supported_answer(AG)
    AG.AgentAnswer(
        label="NOT_IN_DOCS",
        answer="NOT_IN_DOCS",
        citations=(),
        rationale="The filings do not discuss this topic.",
    )

    with pytest.raises(ValidationError):
        AG.AgentAnswer(
            label="SUPPORTED",
            answer="Revenue increased.",
            citations=(),
            rationale="No evidence attached.",
        )
    with pytest.raises(ValidationError):
        AG.AgentAnswer(
            label="NOT_IN_DOCS",
            answer="NOT_IN_DOCS",
            citations=supported_answer(AG).citations,
            rationale="Absent answers must not cite.",
        )


def test_result_keeps_success_and_failure_mutually_exclusive(AG):
    need(AG, "AgentResult")
    values = {
        "status": "ok",
        "answer": supported_answer(AG),
        "failure": None,
        "iterations": 1,
        "total_input_tokens": 10,
        "total_output_tokens": 5,
        "total_time_seconds": 0.1,
        "steps": (),
    }
    AG.AgentResult.model_validate(values)

    with pytest.raises(ValidationError):
        AG.AgentResult.model_validate({**values, "failure": "also failed"})
    with pytest.raises(ValidationError):
        AG.AgentResult.model_validate({**values, "status": "budget_exceeded", "failure": None})


def test_budget_rejects_unbounded_iterations(AG):
    need(AG, "AgentBudget")
    AG.AgentBudget(max_iterations=8)
    with pytest.raises(ValidationError):
        AG.AgentBudget(max_iterations=0)
    with pytest.raises(ValidationError):
        AG.AgentBudget(max_iterations=1_000)
