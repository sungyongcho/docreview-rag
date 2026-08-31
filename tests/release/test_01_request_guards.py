"""Public middleware, headers, and secret-redaction tests."""

import logging
import sys

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.release.limiter import InProcessRateLimiter
from app.release.middleware import (
    ReleaseGuardMiddleware,
    SecurityHeadersMiddleware,
    client_host,
)
from app.release.secrets import REDACTION, SecretRedactionFilter


def _guarded_app() -> FastAPI:
    """Build one application behind the release guards."""
    app = FastAPI()
    app.add_middleware(
        ReleaseGuardMiddleware,
        limiter=InProcessRateLimiter(per_minute=1, per_day=2, max_clients=8),
        trust_proxy_headers=False,
        allow_ingest=False,
        salt=b"x" * 32,
    )
    app.add_middleware(SecurityHeadersMiddleware)

    @app.post("/work")
    async def work() -> dict[str, str]:
        """Return a trivial payload so the guards have something to wrap."""
        return {"status": "ok"}

    @app.post("/ingest")
    async def ingest() -> dict[str, str]:
        """Stand in for an ingestion route the guards must block."""
        return {"status": "unexpected"}

    return app


def test_security_headers_and_rate_limit_are_visible() -> None:
    """Set the security headers and publish the remaining allowance, denying past it."""
    with TestClient(_guarded_app()) as client:
        first = client.post("/work")
        denied = client.post("/work")

    assert first.status_code == 200
    assert first.headers["x-content-type-options"] == "nosniff"
    assert first.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert first.headers["x-ratelimit-remaining-minute"] == "0"
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "60"
    assert denied.headers["x-content-type-options"] == "nosniff"
    assert denied.headers["cache-control"] == "no-store"
    assert denied.json()["error"]["code"] == "rate_limited"


def test_public_ingestion_is_disabled_before_service_execution() -> None:
    """Refuse ingestion before the route runs, not after."""
    with TestClient(_guarded_app()) as client:
        response = client.post("/ingest")

    assert response.status_code == 403
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["code"] == "release_read_only"


def test_forwarded_client_input_requires_explicit_trust() -> None:
    """Ignore a forwarded client address unless proxy headers were explicitly trusted."""
    scope = {
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"x-forwarded-for", b"203.0.113.8, 10.0.0.1")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    request = Request(scope)

    assert client_host(request, trust_proxy_headers=False) == "127.0.0.1"
    assert client_host(request, trust_proxy_headers=True) == "203.0.113.8"


def test_server_secret_is_redacted_before_log_formatting() -> None:
    """Replace a configured secret in a log record before it is formatted."""
    secret = "sk-never-log-this"
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="provider failed for %s",
        args=(secret,),
        exc_info=None,
    )

    assert SecretRedactionFilter((secret,)).filter(record)
    assert record.getMessage() == f"provider failed for {REDACTION}"
    assert secret not in record.getMessage()
    trace_secret = "sk-never-trace-this"
    try:
        raise RuntimeError(f"provider rejected {trace_secret}")
    except RuntimeError:
        exception = sys.exc_info()
    exception_record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="provider failed",
        args=(),
        exc_info=exception,
    )

    assert SecretRedactionFilter((trace_secret,)).filter(exception_record)
    assert REDACTION in exception_record.getMessage()
    assert trace_secret not in exception_record.getMessage()
    assert exception_record.exc_info is None
