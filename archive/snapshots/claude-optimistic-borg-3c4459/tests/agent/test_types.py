"""M9.1 strict agent value-object contracts."""

import json

from pydantic import ValidationError
import pytest

from app.agent.types import (
    AgentAnswer,
    AgentBudget,
    AgentCitation,
    AgentResult,
    AgentStep,
    Observation,
    StepUsage,
    ToolCall,
)


def usage(**changes):
    """Build one step usage record with optional field replacements."""
    values = {
        "model_name": "deterministic-agent",
        "api_url": "deterministic://local",
        "input_tokens": 10,
        "output_tokens": 5,
        "request_time_ms": 1.0,
    }
    values.update(changes)
    return StepUsage(**values)


def call(*, call_id="call-1", name="search_filings", arguments=None):
    """Build one tool call, defaulting to a search with a query."""
    return ToolCall(
        call_id=call_id,
        name=name,
        arguments_json=json.dumps(arguments or {"query": "revenue"}),
    )


def supported_answer(*, chunk_id=7):
    """Build one supported answer carrying a single citation."""
    return AgentAnswer(
        label="SUPPORTED",
        answer="Revenue increased by ten percent.",
        citations=(
            AgentCitation(
                chunk_id=chunk_id,
                doc_id="NVDA-FY2024",
                citation="NVDA FY2024 · Item 7",
                start_char=700,
                end_char=750,
                source_sha256="a" * 64,
            ),
        ),
        rationale="The cited chunk states the increase.",
    )


def test_observation_keeps_output_and_error_mutually_exclusive():
    """Require an observation to carry exactly one of output or error."""
    Observation(call_id="call-1", name="search_filings", output_json="{}")
    Observation(call_id="call-1", name="search_filings", error="boom")

    with pytest.raises(ValidationError):
        Observation(call_id="call-1", name="search_filings")
    with pytest.raises(ValidationError):
        Observation(call_id="call-1", name="search_filings", output_json="{}", error="boom")


def test_agent_step_rejects_observations_for_unknown_calls():
    """Reject an observation whose call id or name matches no call in the step."""
    with pytest.raises(ValidationError):
        AgentStep(
            step=1,
            output_text="",
            tool_calls=(call(),),
            observations=(Observation(call_id="other", name="search_filings", output_json="{}"),),
            usage=usage(),
        )

    with pytest.raises(ValidationError, match="unique"):
        AgentStep(
            step=1,
            output_text="",
            tool_calls=(call(), call()),
            observations=(),
            usage=usage(),
        )

    with pytest.raises(ValidationError, match="name"):
        AgentStep(
            step=1,
            output_text="",
            tool_calls=(call(),),
            observations=(Observation(call_id="call-1", name="wrong", output_json="{}"),),
            usage=usage(),
        )


def test_answer_label_contract_mirrors_the_m4_rules():
    """Require citations for a supported answer and forbid them for an absent one."""
    supported_answer()
    AgentAnswer(
        label="NOT_IN_DOCS",
        answer="NOT_IN_DOCS",
        citations=(),
        rationale="The filings do not discuss this topic.",
    )

    with pytest.raises(ValidationError):
        AgentAnswer(
            label="SUPPORTED",
            answer="Revenue increased.",
            citations=(),
            rationale="No evidence attached.",
        )
    with pytest.raises(ValidationError):
        AgentAnswer(
            label="NOT_IN_DOCS",
            answer="NOT_IN_DOCS",
            citations=supported_answer().citations,
            rationale="Absent answers must not cite.",
        )


def test_result_keeps_success_and_failure_mutually_exclusive():
    """Require the status to agree with whether a failure is present."""
    values = {
        "status": "ok",
        "answer": supported_answer(),
        "failure": None,
        "iterations": 1,
        "total_input_tokens": 10,
        "total_output_tokens": 5,
        "total_time_seconds": 0.1,
        "steps": (),
    }
    AgentResult.model_validate(values)

    with pytest.raises(ValidationError):
        AgentResult.model_validate({**values, "failure": "also failed"})
    with pytest.raises(ValidationError):
        AgentResult.model_validate({**values, "status": "budget_exceeded", "failure": None})


def test_budget_rejects_unbounded_iterations():
    """Reject an iteration budget of zero or one far past any real run."""
    AgentBudget(max_iterations=8)
    with pytest.raises(ValidationError):
        AgentBudget(max_iterations=0)
    with pytest.raises(ValidationError):
        AgentBudget(max_iterations=1_000)
