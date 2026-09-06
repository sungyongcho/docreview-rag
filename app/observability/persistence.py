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
    r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;]+)"""
)


def _validated_secrets(secret_values: Iterable[str]) -> tuple[str, ...]:
    """Return unique explicit secrets in longest-first replacement order."""
    secrets: list[str] = []
    for secret in secret_values:
        if not isinstance(secret, str) or not secret:
            raise ValueError("secret_values must contain nonempty strings")
        secrets.append(secret)
    return tuple(sorted(set(secrets), key=len, reverse=True))


def _redact_sensitive_text(text: str, *, secrets: tuple[str, ...]) -> str:
    """Apply prepared explicit secrets and built-in credential patterns."""
    redacted = text
    for secret in secrets:
        redacted = redacted.replace(secret, REDACTED)
    redacted = _OPENAI_KEY.sub(REDACTED, redacted)
    redacted = _BEARER_TOKEN.sub(rf"\1{REDACTED}", redacted)
    return _SECRET_ASSIGNMENT.sub(rf"\1{REDACTED}", redacted)


def redact_sensitive_text(text: str, *, secret_values: Iterable[str] = ()) -> str:
    """Preserve ordinary text while replacing recognizable credentials.

    Parameters
    ----------
    text : str
        Text that may contain credentials.
    secret_values : Iterable[str]
        Additional exact secrets replaced longest-first.

    Returns
    -------
    str
        Text with explicit secrets, API keys, bearer tokens, and secret assignments
        replaced by ``REDACTED``.

    Raises
    ------
    ValueError
        If text is not a string or an explicit secret is empty or non-string.
    """
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return _redact_sensitive_text(text, secrets=_validated_secrets(secret_values))


def _sanitize_json(value: JsonValue, *, secret_values: tuple[str, ...]) -> JsonValue:
    """Redact every JSON string and reject key collisions after redaction.

    Parameters
    ----------
    value : JsonValue
        JSON-compatible value to sanitize recursively.
    secret_values : tuple[str, ...]
        Validated explicit secrets in replacement order.

    Returns
    -------
    JsonValue
        Sanitized value preserving the original container structure.

    Raises
    ------
    ValueError
        If two original mapping keys collapse to the same sanitized key.
    """
    if isinstance(value, str):
        return _redact_sensitive_text(value, secrets=secret_values)
    if isinstance(value, Mapping):
        sanitized: dict[str, JsonValue] = {}
        for key, child in value.items():
            sanitized_key = _redact_sensitive_text(str(key), secrets=secret_values)
            if sanitized_key in sanitized:
                raise ValueError(f"redaction produced duplicate JSON key: {sanitized_key!r}")
            sanitized[sanitized_key] = _sanitize_json(child, secret_values=secret_values)
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_json(child, secret_values=secret_values) for child in value]
    return value


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
        If the report or secret values are invalid, or redacted JSON keys collide.

    Notes
    -----
    Explicit secrets are validated and sorted once per report, before any ORM object
    receives text.
    """
    if not isinstance(report, RunReport):
        raise ValueError("report must be a RunReport")
    secrets = _validated_secrets(secret_values)
    run = Run(
        run_id=report.run_id,
        status=report.status,
        iterations=report.iterations,
        total_requests=report.total_requests,
        total_input_tokens=report.total_input_tokens,
        total_output_tokens=report.total_output_tokens,
        total_time_seconds=report.total_time_seconds,
        system_prompt=_redact_sensitive_text(report.system_prompt, secrets=secrets),
        node_path=list(report.node_path),
        report=_sanitize_json(report.report, secret_values=secrets),
    )
    traces = tuple(
        Trace(
            run_id=report.run_id,
            step=trace.step,
            node=trace.node,
            model_name=trace.model_name,
            api_url=_redact_sensitive_text(trace.api_url, secrets=secrets),
            input_tokens=trace.input_tokens,
            output_tokens=trace.output_tokens,
            request_time_ms=trace.request_time_ms,
            llm_output=_redact_sensitive_text(trace.llm_output, secrets=secrets),
            retries=trace.retries,
            error=(
                _redact_sensitive_text(trace.error, secrets=secrets)
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
    """Flush one run and its traces without committing the transaction.

    Parameters
    ----------
    session : AsyncSession
        Caller-owned transaction and flush boundary.
    report : RunReport
        Strict workflow result to persist.
    secret_values : Iterable[str]
        Additional credentials removed before ORM construction.

    Returns
    -------
    Run
        Flushed run record.

    Notes
    -----
    The caller retains commit and rollback ownership.
    """
    run, traces = report_to_records(report, secret_values=secret_values)
    session.add(run)
    session.add_all(traces)
    await session.flush()
    return run
