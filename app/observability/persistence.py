"""Secret-safe mapping and transaction-neutral workflow persistence seams."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import cast

from pydantic import JsonValue, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, Trace
from app.llm.schemas import LocalModelTiming
from app.observability.redaction import compile_secret_patterns, redact_text, sanitize_value
from app.observability.types import RunReport, RunStatus, StepTrace, WorkflowNode

_RUN_STATUS = TypeAdapter[RunStatus](RunStatus)
_WORKFLOW_NODE = TypeAdapter[WorkflowNode](WorkflowNode)


def report_to_records(
    report: RunReport,
    *,
    secret_values: Iterable[str] = (),
) -> tuple[Run, tuple[Trace, ...]]:
    """Map a strict report to secret-safe ORM records without database I/O.

    Parameters
    ----------
    report : RunReport
        Strict workflow result to map.
    secret_values : Iterable[str]
        Additional credentials that must not cross the persistence boundary.

    Returns
    -------
    tuple[Run, tuple[Trace, ...]]
        One run row and its ordered trace rows.

    Raises
    ------
    ValueError
        If the secret values are invalid, or redacted JSON keys collide.

    Notes
    -----
    Explicit secrets are validated and compiled once per report, before any ORM object
    receives text.
    """
    secrets = compile_secret_patterns(secret_values)
    context = dict(report.request_context or {})
    timing_metadata: dict[str, JsonValue] = {
        str(trace.step): [
            timing.model_dump(mode="json", exclude_none=True) for timing in trace.local_timings
        ]
        for trace in report.steps
        if trace.local_timings
    }
    if timing_metadata:
        context["trace_local_timings"] = timing_metadata
    request_counts: dict[str, JsonValue] = {
        str(trace.step): trace.requests
        for trace in report.steps
        if trace.requests != trace.retries + 1
    }
    if request_counts:
        context["trace_requests"] = request_counts
    run = Run(
        run_id=report.run_id,
        status=report.status,
        iterations=report.iterations,
        total_requests=report.total_requests,
        total_input_tokens=report.total_input_tokens,
        total_output_tokens=report.total_output_tokens,
        total_cached_input_tokens=report.total_cached_input_tokens,
        total_cache_write_input_tokens=report.total_cache_write_input_tokens,
        total_reasoning_tokens=report.total_reasoning_tokens,
        total_estimated_cost_usd=report.total_estimated_cost_usd,
        total_time_seconds=report.total_time_seconds,
        system_prompt=redact_text(report.system_prompt, secrets=secrets),
        node_path=list(report.node_path),
        report=sanitize_value(report.report, secrets=secrets),
        request_context=sanitize_value(
            context if context else report.request_context, secrets=secrets
        ),
    )
    traces = tuple(
        Trace(
            run_id=report.run_id,
            step=trace.step,
            node=trace.node,
            model_name=trace.model_name,
            api_url=redact_text(trace.api_url, secrets=secrets),
            input_tokens=trace.input_tokens,
            output_tokens=trace.output_tokens,
            cached_input_tokens=trace.cached_input_tokens,
            cache_write_input_tokens=trace.cache_write_input_tokens,
            reasoning_tokens=trace.reasoning_tokens,
            estimated_cost_usd=trace.estimated_cost_usd,
            request_time_ms=trace.request_time_ms,
            llm_output=redact_text(trace.llm_output, secrets=secrets),
            retries=trace.retries,
            error=(redact_text(trace.error, secrets=secrets) if trace.error is not None else None),
        )
        for trace in report.steps
    )
    return run, traces


def record_to_step(
    trace: Trace, *, request_context: Mapping[str, object] | None = None
) -> StepTrace:
    """Rebuild one stored trace row as the strict step it was recorded from."""
    counts = (request_context or {}).get("trace_requests", {})
    if not isinstance(counts, Mapping):
        raise ValueError("stored trace request counts must be an object")
    metadata = (request_context or {}).get("trace_local_timings", {})
    timings = metadata.get(str(trace.step), []) if isinstance(metadata, Mapping) else []
    return StepTrace(
        step=trace.step,
        node=_WORKFLOW_NODE.validate_python(trace.node, strict=True),
        model_name=trace.model_name,
        api_url=trace.api_url,
        input_tokens=trace.input_tokens,
        output_tokens=trace.output_tokens,
        cached_input_tokens=trace.cached_input_tokens,
        cache_write_input_tokens=trace.cache_write_input_tokens,
        reasoning_tokens=trace.reasoning_tokens,
        estimated_cost_usd=trace.estimated_cost_usd,
        request_time_ms=trace.request_time_ms,
        llm_output=trace.llm_output,
        retries=trace.retries,
        # The current storage format records only counts that differ from retries + 1.
        requests=counts.get(str(trace.step), trace.retries + 1),
        error=trace.error,
        local_timings=tuple(LocalModelTiming.model_validate(value) for value in timings),
    )


def records_to_report(run: Run, traces: Sequence[Trace]) -> RunReport:
    """Rebuild one stored run and its ordered traces as a strict report.

    This is the inverse of :func:`report_to_records` and lives beside it so a new
    ``Run`` or ``Trace`` column changes both directions in one module — a field added
    to one mapping and forgotten in the other fails the round-trip test here instead
    of a production read.
    """
    return RunReport(
        run_id=run.run_id,
        status=_RUN_STATUS.validate_python(run.status, strict=True),
        iterations=run.iterations,
        total_requests=run.total_requests,
        total_input_tokens=run.total_input_tokens,
        total_output_tokens=run.total_output_tokens,
        total_cached_input_tokens=run.total_cached_input_tokens,
        total_cache_write_input_tokens=run.total_cache_write_input_tokens,
        total_reasoning_tokens=run.total_reasoning_tokens,
        total_estimated_cost_usd=run.total_estimated_cost_usd,
        total_time_seconds=run.total_time_seconds,
        system_prompt=run.system_prompt,
        node_path=tuple(
            _WORKFLOW_NODE.validate_python(node, strict=True) for node in run.node_path
        ),
        # The JSONB column deserializes to JSON values; the ORM annotation is the
        # wider dict[str, object] only because SQLAlchemy cannot express JsonValue.
        report=cast("dict[str, JsonValue] | None", run.report),
        request_context=cast("dict[str, JsonValue] | None", run.request_context),
        steps=tuple(record_to_step(trace, request_context=run.request_context) for trace in traces),
    )


async def persist_run_records(
    session: AsyncSession,
    run: Run,
    traces: Sequence[Trace],
) -> Run:
    """Flush already-sanitized run records without committing the transaction.

    Parameters
    ----------
    session : AsyncSession
        Caller-owned transaction and flush boundary.
    run : Run
        Sanitized run row from :func:`report_to_records`.
    traces : Sequence[Trace]
        Sanitized ordered trace rows from the same mapping call.

    Returns
    -------
    Run
        Flushed run record.

    Notes
    -----
    The caller retains commit and rollback ownership. Records are persisted as given;
    sanitize once with :func:`report_to_records` instead of re-redacting per layer.
    """
    session.add(run)
    session.add_all(traces)
    await session.flush()
    return run
