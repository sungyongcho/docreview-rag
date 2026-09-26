"""Redact credentials in text and JSON independently of database persistence."""

from collections.abc import Iterable, Mapping, Sequence
import re
from typing import overload

from pydantic import JsonValue

REDACTED = "[REDACTED]"
_SECRET_NAME = r"(?:api[_-]?key|crtfc[_-]?key|authorization|password|secret|access[_-]?token)"
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


def compile_secret_patterns(secret_values: Iterable[str]) -> re.Pattern[str] | None:
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


def redact_text(text: str, *, secrets: re.Pattern[str] | None) -> str:
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
    return redact_text(text, secrets=compile_secret_patterns(secret_values))


@overload
def sanitize_json(
    value: dict[str, JsonValue], *, secret_values: Iterable[str] = ()
) -> dict[str, JsonValue]: ...


@overload
def sanitize_json(value: JsonValue, *, secret_values: Iterable[str] = ()) -> JsonValue: ...


def sanitize_json(value: JsonValue, *, secret_values: Iterable[str] = ()) -> JsonValue:
    """Sanitize one JSON value with the same rules persistence applies.

    Public seam for boundaries that re-emit stored JSON, so every surface shares one
    walker — including the sensitive-key rule a value-only pass would miss.
    """
    return sanitize_value(value, secrets=compile_secret_patterns(secret_values))


def sanitize_value(value: JsonValue, *, secrets: re.Pattern[str] | None) -> JsonValue:
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
        return redact_text(value, secrets=secrets)
    if isinstance(value, Mapping):
        sanitized: dict[str, JsonValue] = {}
        for key, child in value.items():
            sanitized_key = redact_text(str(key), secrets=secrets)
            if sanitized_key in sanitized:
                raise ValueError(f"redaction produced duplicate JSON key: {sanitized_key!r}")
            sanitized[sanitized_key] = (
                REDACTED
                if _SENSITIVE_KEY.search(str(key))
                else sanitize_value(child, secrets=secrets)
            )
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_value(child, secrets=secrets) for child in value]
    return value
