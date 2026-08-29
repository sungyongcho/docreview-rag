"""Shared step-trace and run-report builders for the observability tests."""

from decimal import Decimal

from app.observability.types import StepTrace, build_run_report


def step_trace(**overrides):
    """Build one step trace with optional replacements."""
    values = {
        "step": 1,
        "node": "grade",
        "model_name": "gpt-4.1-mini",
        "api_url": "https://api.openai.com/v1/responses",
        "input_tokens": 100,
        "output_tokens": 20,
        # The pinned gpt-4.1-mini price for the token counts above.
        "estimated_cost_usd": Decimal("0.000072"),
        "request_time_ms": 12.5,
        "llm_output": '{"label":"SUPPORTED"}',
        "retries": 0,
        "error": None,
    }
    values.update(overrides)
    return StepTrace(**values)


def run_report(*, steps=None, **overrides):
    """Build one run report over the supplied traces."""
    trace_values = [step_trace()] if steps is None else steps
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
    return build_run_report(**values)
