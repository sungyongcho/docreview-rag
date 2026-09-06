"""Secret-safe mapping and transaction-neutral workflow persistence seams."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, Trace
from app.observability.types import JsonValue, RunReport

REDACTED = "[REDACTED]"
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_BEARER_TOKEN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|password|secret|access[_-]?token)\b\s*[:=]\s*)"
    r"([^\s,;]+)"
)


def redact_sensitive_text(text: str, *, secret_values: Iterable[str] = ()) -> str:
    """Preserve ordinary text while removing explicit and recognizable credentials."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    secrets: list[str] = []
    for secret in secret_values:
        if not isinstance(secret, str) or not secret:
            raise ValueError("secret_values must contain nonempty strings")
        secrets.append(secret)
    redacted = text
    for secret in sorted(set(secrets), key=len, reverse=True):
        redacted = redacted.replace(secret, REDACTED)
    redacted = _OPENAI_KEY.sub(REDACTED, redacted)
    redacted = _BEARER_TOKEN.sub(rf"\1{REDACTED}", redacted)
    return _SECRET_ASSIGNMENT.sub(rf"\1{REDACTED}", redacted)


def _sanitize_json(value: JsonValue, *, secret_values: tuple[str, ...]) -> JsonValue:
    if isinstance(value, str):
        return redact_sensitive_text(value, secret_values=secret_values)
    if isinstance(value, Mapping):
        return {
            redact_sensitive_text(str(key), secret_values=secret_values): _sanitize_json(
                child,
                secret_values=secret_values,
            )
            for key, child in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_json(child, secret_values=secret_values) for child in value]
    return value


def report_to_records(
    report: RunReport,
    *,
    secret_values: Iterable[str] = (),
) -> tuple[Run, tuple[Trace, ...]]:
    """Map a strict report to secret-safe ORM records without database I/O."""
    if not isinstance(report, RunReport):
        raise ValueError("report must be a RunReport")
    secrets = tuple(secret_values)
    run = Run(
        run_id=report.run_id,
        status=report.status,
        iterations=report.iterations,
        total_requests=report.total_requests,
        total_input_tokens=report.total_input_tokens,
        total_output_tokens=report.total_output_tokens,
        total_time_seconds=report.total_time_seconds,
        system_prompt=redact_sensitive_text(
            report.system_prompt,
            secret_values=secrets,
        ),
        node_path=list(report.node_path),
        report=_sanitize_json(report.report, secret_values=secrets),
    )
    traces = tuple(
        Trace(
            run_id=report.run_id,
            step=trace.step,
            node=trace.node,
            model_name=trace.model_name,
            api_url=redact_sensitive_text(trace.api_url, secret_values=secrets),
            input_tokens=trace.input_tokens,
            output_tokens=trace.output_tokens,
            request_time_ms=trace.request_time_ms,
            llm_output=redact_sensitive_text(trace.llm_output, secret_values=secrets),
            retries=trace.retries,
            error=(
                redact_sensitive_text(trace.error, secret_values=secrets)
                if trace.error is not None
                else None
            ),
        )
        for trace in report.steps
    )
    return run, traces


async def persist_run_report(
    session: AsyncSession,
    report: RunReport,
    *,
    secret_values: Iterable[str] = (),
) -> Run:
    """Flush one run and its traces without committing the caller's transaction."""
    run, traces = report_to_records(report, secret_values=secret_values)
    session.add(run)
    session.add_all(traces)
    await session.flush()
    return run
