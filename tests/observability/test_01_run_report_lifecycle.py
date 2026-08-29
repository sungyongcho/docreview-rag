"""Strict run-report lifecycle: traces, cumulative budgets, cost, and persistence."""

import asyncio
from decimal import Decimal
import os
from types import SimpleNamespace

from pydantic import ValidationError
import pytest
from sqlalchemy import CheckConstraint, Table, UniqueConstraint

from app.db import models
from tests.support import need, optional_module

OBS = optional_module(os.getenv("OBSERVABILITY_MODULE", "app.observability"))


def _trace(**overrides):
    """Build one step trace with optional replacements."""
    need(OBS, "StepTrace")
    values = {
        "step": 1,
        "node": "grade",
        "model_name": "gpt-4.1-mini",
        "api_url": "https://api.openai.com/v1/responses",
        "input_tokens": 100,
        "output_tokens": 20,
        "request_time_ms": 12.5,
        "llm_output": '{"label":"SUPPORTED"}',
        "retries": 0,
        "error": None,
    }
    values.update(overrides)
    return OBS.StepTrace(**values)


def _report(*, steps=None, **overrides):
    """Build one run report over the supplied traces."""
    need(OBS, "build_run_report")
    trace_values = [_trace()] if steps is None else steps
    values = {
        "run_id": "run-test-01",
        "status": "ok",
        "total_time_seconds": 0.5,
        "system_prompt": "Use only retrieved filing evidence.",
        "node_path": ["retrieve", "grade"],
        "steps": trace_values,
        "report": {"label": "SUPPORTED"},
    }
    values.update(overrides)
    return OBS.build_run_report(**values)


def test_step_trace_is_strict_frozen_and_preserves_raw_output():
    """Freeze one step trace and keep its raw provider output intact."""
    trace = _trace()

    assert trace.llm_output == '{"label":"SUPPORTED"}'
    with pytest.raises(ValidationError):
        trace.input_tokens = 999
    with pytest.raises(ValidationError):
        _trace(input_tokens="100")
    with pytest.raises(ValidationError):
        _trace(node="unknown")
    with pytest.raises(ValidationError):
        _trace(extra_field=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("step", 0),
        ("input_tokens", -1),
        ("output_tokens", True),
        ("request_time_ms", float("nan")),
        ("retries", -1),
        ("error", " "),
    ],
)
def test_step_trace_rejects_invalid_metrics(field, value):
    """Reject a step trace whose measured metrics are impossible."""
    with pytest.raises(ValidationError):
        _trace(**{field: value})


def test_run_report_derives_cumulative_tokens_requests_and_iterations():
    """Derive cumulative tokens, requests, and iterations from the traces themselves."""
    steps = [
        _trace(),
        _trace(
            step=2,
            node="check",
            input_tokens=40,
            output_tokens=8,
            retries=1,
        ),
    ]

    report = _report(steps=steps, node_path=["retrieve", "grade", "check"])

    assert report.iterations == 3
    assert report.total_requests == 3
    assert report.total_input_tokens == 140
    assert report.total_output_tokens == 28
    assert report.steps == tuple(steps)


def test_run_report_rejects_non_json_reports_and_inconsistent_direct_totals():
    """Reject a non-JSON report body or totals that disagree with the traces."""
    need(OBS, "RunReport")
    with pytest.raises(ValidationError):
        _report(report={"invalid": object()})
    with pytest.raises(ValidationError, match="finite JSON"):
        _report(report={"invalid": {"latency": float("nan")}})
    with pytest.raises(ValidationError, match="total_input_tokens"):
        OBS.RunReport(
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
            steps=(_trace(),),
        )


def test_pre_node_guard_allows_entry_while_every_budget_has_capacity():
    """Admit the next node while every budget still has capacity."""
    need(OBS, "Budget", "pre_node_budget_guard")
    result = OBS.pre_node_budget_guard(
        run_id="run-allowed",
        node="check",
        budget=OBS.Budget(
            max_iterations=3,
            max_input_tokens=101,
            max_output_tokens=21,
            max_wall_clock_s=2.0,
        ),
        elapsed_seconds=1.0,
        system_prompt="Ground every claim.",
        node_path=["retrieve", "grade"],
        steps=[_trace()],
    )

    assert result is None


@pytest.mark.parametrize(
    ("budget_overrides", "elapsed_seconds", "expected_resource"),
    [
        ({"max_iterations": 2}, 1.0, "iterations"),
        ({"max_input_tokens": 100}, 1.0, "input_tokens"),
        ({"max_output_tokens": 20}, 1.0, "output_tokens"),
        ({"max_wall_clock_s": 1.0}, 1.0, "wall_clock_s"),
    ],
)
def test_pre_node_guard_returns_structured_budget_exceeded_refusal(
    budget_overrides,
    elapsed_seconds,
    expected_resource,
):
    """Refuse the next node with structured evidence of the exhausted budget."""
    need(OBS, "Budget", "pre_node_budget_guard")
    values = {
        "max_iterations": 3,
        "max_input_tokens": 101,
        "max_output_tokens": 21,
        "max_wall_clock_s": 2.0,
    }
    values.update(budget_overrides)

    result = OBS.pre_node_budget_guard(
        run_id="run-refused",
        node="check",
        budget=OBS.Budget(**values),
        elapsed_seconds=elapsed_seconds,
        system_prompt="Ground every claim.",
        node_path=["retrieve", "grade"],
        steps=[_trace()],
    )

    assert result is not None
    assert result.status == "budget_exceeded"
    assert result.node_path == ("retrieve", "grade")
    assert result.report == {
        "reason": {
            "code": "budget_exceeded",
            "resource": expected_resource,
            "limit": values[f"max_{expected_resource}"],
            "observed": {
                "iterations": 2,
                "input_tokens": 100,
                "output_tokens": 20,
                "wall_clock_s": elapsed_seconds,
            }[expected_resource],
            "blocked_node": "check",
        }
    }


def test_zero_budget_refuses_the_first_node_and_negative_budgets_are_invalid():
    """Refuse the first node on a zero budget and reject a negative one outright."""
    need(OBS, "Budget", "pre_node_budget_guard")
    budget = OBS.Budget(
        max_iterations=0,
        max_input_tokens=0,
        max_output_tokens=0,
        max_wall_clock_s=0.0,
    )

    result = OBS.pre_node_budget_guard(
        run_id="run-zero",
        node="retrieve",
        budget=budget,
        elapsed_seconds=0.0,
        system_prompt="Ground every claim.",
        node_path=[],
        steps=[],
    )

    assert result is not None
    assert result.status == "budget_exceeded"
    assert result.report["reason"]["resource"] == "iterations"
    with pytest.raises(ValidationError):
        OBS.Budget(max_input_tokens=-1)
    with pytest.raises(ValidationError):
        OBS.Budget(max_iterations=True)
    with pytest.raises(ValidationError):
        OBS.Budget(max_wall_clock_s=float("inf"))


def test_cost_estimation_is_exact_accumulative_and_fail_closed():
    """Accumulate cost in exact decimals and fail closed on an unpriced model."""
    need(OBS, "UnknownModelPriceError", "estimate_cost_usd", "estimate_trace_cost_usd")
    million = 1_000_000

    assert OBS.estimate_cost_usd("gpt-4.1-mini", million, million) == Decimal("2.00")
    assert OBS.estimate_cost_usd("gpt-4.1-mini", 0, 0) == Decimal("0")
    assert OBS.estimate_trace_cost_usd([_trace()]) == Decimal("0.000072")
    with pytest.raises(OBS.UnknownModelPriceError):
        OBS.estimate_cost_usd("unpriced-model", 100, 20)
    with pytest.raises(ValueError):
        OBS.estimate_cost_usd("gpt-4.1-mini", -1, 0)
    with pytest.raises(ValueError):
        OBS.estimate_cost_usd("gpt-4.1-mini", True, 0)


def test_schema_refusal_keeps_prompt_and_raw_output_for_audit():
    """Keep the prompt and the raw output behind a schema refusal for audit."""
    refusal = _report(
        status="schema_rejected",
        report={"reason": {"code": "schema_rejected"}},
        steps=[_trace(llm_output="not json", error="schema validation failed", retries=1)],
    )

    assert refusal.system_prompt == "Use only retrieved filing evidence."
    assert refusal.steps[0].llm_output == "not json"
    assert refusal.steps[0].error == "schema validation failed"
    assert refusal.total_requests == 2


def test_provider_refusal_mapping_keeps_trace_metadata_and_typed_reason():
    """Map a provider refusal into a trace without losing its typed reason."""
    need(OBS, "step_trace_from_provider_result")
    metadata = SimpleNamespace(
        model_name="gpt-4.1-mini",
        api_url="https://api.openai.com/v1/responses",
        input_tokens=11,
        output_tokens=3,
        request_time_ms=4.5,
        llm_output="not json",
        retries=1,
    )
    result = SimpleNamespace(
        status="schema_rejected",
        metadata=metadata,
        refusal={"status": "schema_rejected", "errors": ["label is required"]},
    )

    trace = OBS.step_trace_from_provider_result(result, step=1, node="grade")

    assert trace.llm_output == "not json"
    assert trace.input_tokens == 11
    assert trace.output_tokens == 3
    assert trace.retries == 1
    assert trace.error == (
        '{"refusal":{"errors":["label is required"],"status":"schema_rejected"},'
        '"status":"schema_rejected"}'
    )


def test_persistence_mapping_preserves_provenance_and_redacts_secrets():
    """Preserve run provenance while redacting secrets on the way to storage."""
    need(OBS, "REDACTED", "report_to_records")
    secret = "sk-test-secret-123456"
    report = _report(
        status="schema_rejected",
        system_prompt=f"Use evidence. API_KEY={secret}",
        report={"reason": f"provider rejected Bearer {secret}"},
        steps=[
            _trace(
                api_url=f"https://example.test/responses?api_key={secret}",
                llm_output=f'{{"raw":"{secret}","kept":"evidence"}}',
                error=f"Authorization: Bearer {secret}",
            )
        ],
    )

    run, traces = OBS.report_to_records(report, secret_values=[secret])

    trace = traces[0]
    assert run.run_id == report.run_id
    assert run.status == "schema_rejected"
    assert run.node_path == ["retrieve", "grade"]
    assert "Use evidence." in run.system_prompt
    assert "evidence" in trace.llm_output
    assert secret not in run.system_prompt
    assert secret not in repr(run.report)
    assert secret not in trace.api_url
    assert secret not in trace.llm_output
    assert secret not in trace.error
    assert OBS.REDACTED in run.system_prompt
    assert OBS.REDACTED in trace.llm_output


def test_redaction_covers_quoted_assignments_and_rejects_key_collisions():
    """Redact quoted secret assignments and reject colliding redaction keys."""
    need(OBS, "REDACTED", "redact_sensitive_text", "report_to_records")

    assert OBS.redact_sensitive_text('password="alpha beta"') == "password=[REDACTED]"
    assert OBS.redact_sensitive_text("secret='alpha beta'") == "secret=[REDACTED]"
    assert (
        OBS.redact_sensitive_text(
            "pair abcdef123 abcdef",
            secret_values=["abcdef", "abcdef123"],
        )
        == "pair [REDACTED] [REDACTED]"
    )

    collision = _report(report={"api_key=foo": "first", "api_key=bar": "second"})
    with pytest.raises(ValueError, match="duplicate JSON key"):
        OBS.report_to_records(collision)


def test_database_models_match_run_and_trace_mapping_contracts():
    """Match the run and trace tables to the mapping the report persists."""
    need(models, "Run", "Trace")
    run_table = models.Run.__table__
    trace_table = models.Trace.__table__
    assert isinstance(run_table, Table)
    assert isinstance(trace_table, Table)
    run_columns = run_table.columns
    trace_columns = trace_table.columns

    assert set(run_columns.keys()) == {
        "run_id",
        "status",
        "iterations",
        "total_requests",
        "total_input_tokens",
        "total_output_tokens",
        "total_time_seconds",
        "system_prompt",
        "node_path",
        "report",
        "created_at",
    }
    assert {
        "run_id",
        "step",
        "node",
        "model_name",
        "api_url",
        "input_tokens",
        "output_tokens",
        "request_time_ms",
        "llm_output",
        "retries",
        "error",
    } <= set(trace_columns.keys())
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in trace_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    checks = {
        constraint.name
        for table in (run_table, trace_table)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert ("run_id", "step") in unique_columns
    assert {"ck_runs_status", "ck_traces_node", "ck_traces_step_positive"} <= checks


def test_persistence_flushes_without_committing_or_live_services():
    """Flush a run report without committing or reaching any live service."""
    need(OBS, "persist_run_report")
    need(models, "Run", "Trace")

    class RecordingSession:
        """Record what persistence adds and flushes, without a database."""

        def __init__(self):
            self.added = []
            self.added_many = []
            self.flushed = False

        def add(self, value):
            self.added.append(value)

        def add_all(self, values):
            self.added_many.extend(values)

        async def flush(self):
            self.flushed = True

    session = RecordingSession()
    persisted = asyncio.run(OBS.persist_run_report(session, _report()))

    assert persisted is session.added[0]
    assert isinstance(persisted, models.Run)
    assert len(session.added_many) == 1
    assert isinstance(session.added_many[0], models.Trace)
    assert session.flushed
