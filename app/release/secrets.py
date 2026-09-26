"""Log redaction applied to every record the process creates once secrets are configured."""

from collections.abc import Callable, Mapping
import logging

REDACTION = "[REDACTED]"


def redact_text(value: str, secrets: tuple[str, ...]) -> str:
    """Replace every configured nonblank secret without changing other text."""
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, REDACTION)
    return redacted


class SecretRedactor:
    """Redact configured secrets from one record in place, keeping its formatting contract.

    The message template and each argument are redacted separately, so a formatter that
    unpacks positional arguments (uvicorn's AccessFormatter reads five) still finds them.
    An exception is rendered once into ``exc_text`` and ``exc_info`` is cleared, so no
    formatter can render the unredacted traceback again.
    """

    def __init__(self, secrets: tuple[str, ...]) -> None:
        self.secrets = tuple(dict.fromkeys(secret for secret in secrets if secret))

    def _redact_value(self, value: object) -> object:
        """Redact a string, or a non-string whose rendering would reveal a secret.

        A non-string value that renders no secret is returned unchanged, so typed
        placeholders such as ``%d`` keep their argument.
        """
        if isinstance(value, str):
            return redact_text(value, self.secrets)
        try:
            rendered = str(value)
        except Exception:
            return value  # Formatting reports its own rendering failure later.
        redacted = redact_text(rendered, self.secrets)
        return value if redacted == rendered else redacted

    def redact(self, record: logging.LogRecord) -> None:
        """Redact the message, arguments, traceback and stack text of one record."""
        if not self.secrets:
            return
        record.msg = self._redact_value(record.msg)
        if isinstance(record.args, Mapping):
            record.args = {key: self._redact_value(value) for key, value in record.args.items()}
        elif record.args:
            record.args = tuple(self._redact_value(value) for value in record.args)
        if record.exc_info:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text, self.secrets)
        if record.stack_info:
            record.stack_info = redact_text(record.stack_info, self.secrets)


class SecretRedactingRecordFactory:
    """Create each log record through the previous factory, then redact it in place."""

    def __init__(self, base: Callable[..., logging.LogRecord], redactor: SecretRedactor) -> None:
        self.base = base
        self.redactor = redactor

    def __call__(self, *args: object, **kwargs: object) -> logging.LogRecord:
        """Build the record exactly as the previous factory would, then redact it."""
        record = self.base(*args, **kwargs)
        self.redactor.redact(record)
        return record


def install_secret_redaction(secrets: tuple[str, ...]) -> None:
    """Redact configured secrets from every log record this process creates afterwards.

    Parameters
    ----------
    secrets : tuple[str, ...]
        Secret values to replace; blank values are ignored and an empty tuple is a no-op.

    Notes
    -----
    Redaction runs in the logging record factory, so it covers every logger and handler
    alike: application loggers such as ``app.api.errors``, uvicorn's error and access
    loggers, root handlers and logging's last-resort handler. It does not cover ``extra``
    fields, which logging attaches after the factory returns, records built directly with
    ``logging.LogRecord``, or text written to a stream without logging. A repeated call
    adds its secrets to the installed factory instead of wrapping it again.
    """
    nonblank = tuple(secret for secret in secrets if secret)
    if not nonblank:
        return
    current = logging.getLogRecordFactory()
    if isinstance(current, SecretRedactingRecordFactory):
        # Extend the installed factory rather than wrap it, so each record is redacted once.
        current.redactor = SecretRedactor((*current.redactor.secrets, *nonblank))
    else:
        factory = SecretRedactingRecordFactory(current, SecretRedactor(nonblank))
        logging.setLogRecordFactory(factory)
