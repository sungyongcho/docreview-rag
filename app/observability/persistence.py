"""Secret-safe mapping and transaction-neutral workflow persistence seams."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, Trace
from app.observability.types import JsonValue, RunReport

REDACTED = "[REDACTED]"
_SECRET_NAME = r"(?:api[_-]?key|authorization|password|secret|access[_-]?token)"
_AUTH_SCHEME = r"(?:Bearer|Basic|Token)"

_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_BEARER_TOKEN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
# The key may be quoted, because JSON is the shape most raw provider text arrives in,
# and an unquoted value stops at `&` so redacting one query parameter keeps the rest of
# the URL readable. An authorization scheme is consumed with its credential so the whole
# value is replaced once instead of twice.
_SECRET_ASSIGNMENT = re.compile(
    rf"""(?i)(["']?\b{_SECRET_NAME}\b["']?\s*[:=]\s*)"""
    rf"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|(?:{_AUTH_SCHEME}\s+)?[^\s,;&]+)"""
)
# Key names are matched without word boundaries so compounds such as `openai_api_key`
# are caught too; over-matching a key redacts one value, under-matching stores a secret.
_SENSITIVE_KEY = re.compile(rf"(?i){_SECRET_NAME}")


def _compiled_secrets(secret_values: Iterable[str]) -> re.Pattern[str] | None:
    """Compile the explicit secrets into one longest-first alternation.

    Replacing them in a single pass keeps a later secret from rewriting text an
    earlier replacement produced, and ordering by length then value keeps the result
    independent of the interpreter hash seed that governs set iteration.
    """
    secrets: list[str] = []
    for secret in secret_values:
        if not isinstance(secret, str) or not secret:
            raise ValueError("secret_values must contain nonempty strings")
        secrets.append(secret)
    if not secrets:
        return None
    ordered = sorted(set(secrets), key=lambda secret: (-len(secret), secret))
    return re.compile("|".join(re.escape(secret) for secret in ordered))


def _redact_sensitive_text(text: str, *, secrets: re.Pattern[str] | None) -> str:
    """Apply the prepared explicit secrets and the built-in credential patterns.

    Named assignments are replaced before the bare bearer-token pattern, so an
    ``Authorization: Bearer <token>`` header is redacted once as a whole value.
    """
    redacted = text if secrets is None else secrets.sub(REDACTED, text)
    redacted = _OPENAI_KEY.sub(REDACTED, redacted)
    redacted = _SECRET_ASSIGNMENT.sub(rf"\1{REDACTED}", redacted)
    return _BEARER_TOKEN.sub(rf"\1{REDACTED}", redacted)


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
        If an explicit secret is empty or non-string.
    """
    return _redact_sensitive_text(text, secrets=_compiled_secrets(secret_values))


def _sanitize_json(value: JsonValue, *, secrets: re.Pattern[str] | None) -> JsonValue:
    """Redact every JSON string and reject key collisions after redaction.

    Parameters
    ----------
    value : JsonValue
        JSON-compatible value to sanitize recursively.
    secrets : re.Pattern[str] | None
        Prepared explicit-secret alternation, or ``None`` when none were supplied.

    Returns
    -------
    JsonValue
        Sanitized value preserving the original container structure.

    Raises
    ------
    ValueError
        If two original mapping keys collapse to the same sanitized key.

    Notes
    -----
    Whatever a credential-shaped key holds is replaced wholesale. Redacting the value
    as free text would miss it, because a bare credential carries no assignment syntax
    once the key it belongs to is a separate JSON key.
    """
    if isinstance(value, str):
        return _redact_sensitive_text(value, secrets=secrets)
    if isinstance(value, Mapping):
        sanitized: dict[str, JsonValue] = {}
        for key, child in value.items():
            sanitized_key = _redact_sensitive_text(str(key), secrets=secrets)
            if sanitized_key in sanitized:
                raise ValueError(f"redaction produced duplicate JSON key: {sanitized_key!r}")
            sanitized[sanitized_key] = (
                REDACTED
                if _SENSITIVE_KEY.search(str(key))
                else _sanitize_json(child, secrets=secrets)
            )
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_json(child, secrets=secrets) for child in value]
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
        If the secret values are invalid, or redacted JSON keys collide.

    Notes
    -----
    Explicit secrets are validated and compiled once per report, before any ORM object
    receives text.
    """
    secrets = _compiled_secrets(secret_values)
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
        report=_sanitize_json(report.report, secrets=secrets),
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
            estimated_cost_usd=trace.estimated_cost_usd,
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
