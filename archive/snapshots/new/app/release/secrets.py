"""Defensive log redaction for explicitly configured server-side secrets."""

from __future__ import annotations

import logging

REDACTION = "[REDACTED]"


def redact_text(value: str, secrets: tuple[str, ...]) -> str:
    """Replace every configured nonblank secret without changing other text."""
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, REDACTION)
    return redacted


class SecretRedactionFilter(logging.Filter):
    """Render a log record once, then remove configured secret values."""

    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact message text before any attached handler formats the record."""
        if self._secrets:
            message = redact_text(record.getMessage(), self._secrets)
            if record.exc_info is not None:
                traceback = logging.Formatter().formatException(record.exc_info)
                message = f"{message}\n{redact_text(traceback, self._secrets)}"
                record.exc_info = None
                record.exc_text = None
            record.msg = message
            record.args = ()
        return True


def install_secret_redaction(secrets: tuple[str, ...]) -> None:
    """Attach redaction to release and Uvicorn loggers without logging values."""
    if not any(secrets):
        return
    for name in ("app.release", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addFilter(SecretRedactionFilter(secrets))
