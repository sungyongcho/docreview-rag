"""Strict step traces, derived run-report totals, and their rejections."""

from decimal import Decimal

from pydantic import ValidationError
import pytest

from app.observability.types import RunReport, StepTrace
from tests.observability.support import run_report, step_trace


def test_step_trace_is_strict_frozen_and_preserves_raw_output():
    """Freeze one step trace and keep its raw provider output intact."""
    trace = step_trace()

    assert trace.llm_output == '{"label":"SUPPORTED"}'
    with pytest.raises(ValidationError):
        trace.input_tokens = 999
    with pytest.raises(ValidationError):
        step_trace(input_tokens="100")
    with pytest.raises(ValidationError):
        step_trace(node="unknown")
    with pytest.raises(ValidationError):
        step_trace(extra_field=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("step", 0),
        ("input_tokens", -1),
        ("output_tokens", True),
        ("estimated_cost_usd", 0.000072),
        ("request_time_ms", float("nan")),
        ("retries", -1),
        ("error", " "),
    ],
)
def test_step_trace_rejects_invalid_metrics(field, value):
    """Reject a step trace whose measured metrics are impossible."""
    with pytest.raises(ValidationError):
        step_trace(**{field: value})


def test_run_report_derives_cumulative_tokens_requests_and_iterations():
    """Derive cumulative tokens, requests, and iterations from the traces themselves."""
    steps = [
        step_trace(),
        step_trace(
            step=2,
            node="check",
            input_tokens=40,
            output_tokens=8,
            retries=1,
        ),
    ]

    report = run_report(steps=steps, node_path=["retrieve", "grade", "check"])

    assert report.iterations == 3
    assert report.total_requests == 3
    assert report.total_input_tokens == 140
    assert report.total_output_tokens == 28
    assert report.total_estimated_cost_usd == Decimal("0.000144")
    assert type(report.total_input_tokens) is int
    assert isinstance(report.total_estimated_cost_usd, Decimal)
    assert report.steps == tuple(steps)


def test_step_trace_counts_sent_requests_and_defaults_older_records_to_their_attempts():
    """A refusal before the call records zero requests; older records keep retries + 1."""
    assert step_trace().requests == 1
    assert step_trace(retries=1).requests == 2
    legacy = step_trace(retries=1).model_dump()
    del legacy["requests"]
    assert StepTrace.model_validate(legacy).requests == 2

    refused = step_trace(
        requests=0,
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=Decimal("0"),
        request_time_ms=0.0,
        llm_output="",
        error="input_tokens: used=0 limit=2000",
    )
    report = run_report(
        status="budget_exceeded",
        report={"reason": {"code": "budget_exceeded"}},
        steps=[step_trace(), refused.model_copy(update={"step": 2})],
    )

    assert refused.requests == 0
    assert report.total_requests == 1
    assert RunReport.model_validate(report.model_dump()).total_requests == 1
    with pytest.raises(ValidationError, match="retries plus one"):
        step_trace(requests=2)
    with pytest.raises(ValidationError, match="no usage"):
        step_trace(requests=0)
    with pytest.raises(ValidationError, match="total_requests"):
        RunReport.model_validate({**report.model_dump(), "total_requests": 2})


def test_run_report_rejects_non_json_reports_and_inconsistent_direct_totals():
    """Reject a non-JSON report body or totals that disagree with the traces."""
    with pytest.raises(ValidationError):
        run_report(report={"invalid": object()})
    with pytest.raises(ValidationError, match="finite JSON"):
        run_report(report={"invalid": {"latency": float("nan")}})
    with pytest.raises(ValidationError, match="total_input_tokens"):
        RunReport(
            run_id="run-invalid",
            status="ok",
            iterations=2,
            total_requests=1,
            total_input_tokens=999,
            total_output_tokens=20,
            total_time_seconds=1.0,
            system_prompt="Ground every claim.",
            node_path=("retrieve", "grade"),
            report=None,
            steps=(step_trace(),),
        )


def test_schema_refusal_keeps_prompt_and_raw_output_for_audit():
    """Keep the prompt and the raw output behind a schema refusal for audit."""
    refusal = run_report(
        status="schema_rejected",
        report={"reason": {"code": "schema_rejected"}},
        steps=[step_trace(llm_output="not json", error="schema validation failed", retries=1)],
    )

    assert refusal.system_prompt == "Use only retrieved filing evidence."
    assert refusal.steps[0].llm_output == "not json"
    assert refusal.steps[0].error == "schema validation failed"
    assert refusal.total_requests == 2
