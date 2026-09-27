"""Public middleware, headers, and secret-redaction tests."""

import asyncio
from collections.abc import Iterator
from decimal import Decimal
import io
import logging
import sys

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import httpx
import pytest
from uvicorn.logging import AccessFormatter

from app.api.errors import install_error_handlers
from app.release.ai_allowance import SharedAIAllowance, reserve_openai
from app.release.middleware import ReleaseGuardMiddleware, SecurityHeadersMiddleware, client_host
from app.release.secrets import REDACTION, SecretRedactor, install_secret_redaction


def _guarded_app(
    tmp_path,
    *,
    enforce_rate_limit: bool = True,
    trust_proxy_headers: bool = False,
    per_minute: int = 1,
    per_day: int = 2,
    daily_limit: Decimal = Decimal("1"),
    call_cost: Decimal = Decimal("0.01"),
) -> FastAPI:
    """Build one application behind the release guards with a private allowance ledger."""
    app = FastAPI()
    app.add_middleware(
        ReleaseGuardMiddleware,
        allowance=SharedAIAllowance(tmp_path / "limits.sqlite3", daily_limit, per_minute, per_day),
        trust_proxy_headers=trust_proxy_headers,
        enforce_rate_limit=enforce_rate_limit,
    )
    app.add_middleware(SecurityHeadersMiddleware)

    @app.post("/review")
    async def review() -> dict[str, str]:
        """Reserve one provider call so the guards have something to meter."""
        await reserve_openai(call_cost)
        return {"status": "ok"}

    @app.post("/work")
    async def work() -> dict[str, str]:
        """Return a trivial payload from a route outside the metered set."""
        return {"status": "ok"}

    return app


def test_routes_outside_the_metered_set_never_consume_the_allowance(tmp_path) -> None:
    """Leave provider-free routes untouched even once the client's request window is spent."""
    with TestClient(_guarded_app(tmp_path)) as client:
        assert client.post("/review").status_code == 200
        assert client.post("/review").status_code == 429
        work = [client.post("/work") for _ in range(3)]

    assert [response.status_code for response in work] == [200, 200, 200]
    assert all("x-ratelimit-remaining-minute" not in response.headers for response in work)


def _review_app(tmp_path) -> FastAPI:
    """Build one guarded review route that reports whether the guard admitted the request."""
    app = FastAPI()
    app.add_middleware(
        ReleaseGuardMiddleware,
        allowance=SharedAIAllowance(tmp_path / "limits.sqlite3", Decimal("1"), 50, 50),
        trust_proxy_headers=False,
    )

    @app.post("/review")
    async def review() -> dict[str, str]:
        """Stand in for the provider route behind the guard."""
        return {"status": "admitted"}

    return app


def _custom_profile(**retrieval: object) -> dict[str, object]:
    """Compose one Custom preset profile around the Balanced defaults."""
    return {
        "retrieval_preset": "custom",
        "custom_retrieval": {
            "strategy": "hybrid",
            "k": 5,
            "candidate_k": 20,
            "lexical_ranker": "ts_rank_cd",
            **retrieval,
        },
    }


def test_public_custom_retrieval_within_bounds_reaches_the_route(tmp_path) -> None:
    """Admit the Custom preset publicly while its depth stays at the built-in ceiling."""
    profile = _custom_profile(k=10, candidate_k=50, lexical_ranker="bm25", reranker="cross_encoder")
    with TestClient(_review_app(tmp_path)) as client:
        response = client.post(
            "/review",
            headers={"X-DocReview-Public": "true"},
            json={"query": "Revenue?", "session_profile": profile},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "admitted"}


@pytest.mark.parametrize(
    ("retrieval", "violation"),
    [
        ({"k": 11, "candidate_k": 50}, "custom_retrieval.k must be at most 10"),
        ({"k": 5, "candidate_k": 51}, "custom_retrieval.candidate_k must be at most 50"),
    ],
)
def test_public_custom_retrieval_above_bounds_names_the_field(
    tmp_path, retrieval, violation
) -> None:
    """Reject oversized Custom depth with the shared lock message naming the exceeded bound."""
    with TestClient(_review_app(tmp_path)) as client:
        response = client.post(
            "/review",
            headers={"X-DocReview-Public": "true"},
            json={"query": "Revenue?", "session_profile": _custom_profile(**retrieval)},
        )

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "capability_disabled"
    assert error["message"].startswith("This control runs in DEV mode only.")
    assert violation in error["message"]


@pytest.mark.parametrize(
    "profile",
    [
        {"prompt_policy": {"additional_instructions": "Be concise."}},
        {"engine": "local"},
        {"snapshot_id": 3},
    ],
)
def test_public_prompt_local_and_snapshot_controls_stay_locked(tmp_path, profile) -> None:
    """Keep every non-retrieval developer control behind the one DEV-mode lock envelope."""
    with TestClient(_review_app(tmp_path)) as client:
        response = client.post(
            "/review",
            headers={"X-DocReview-Public": "true"},
            json={"query": "Revenue?", "session_profile": profile},
        )

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "capability_disabled",
            "message": "This control runs in DEV mode only.",
            "details": [],
        }
    }


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
    assert client_host(request, trust_proxy_headers=True) == "10.0.0.1"


def test_spoofed_forwarded_entries_through_one_proxy_hop_share_one_rate_limit_key(
    tmp_path,
) -> None:
    """Key the client on the hop the trusted proxy appended, not on client-written entries."""
    app = _guarded_app(tmp_path, trust_proxy_headers=True, daily_limit=Decimal("0.02"))

    with TestClient(app) as client:
        first = client.post("/review", headers={"x-forwarded-for": "203.0.113.1, 10.0.0.1"})
        second = client.post("/review", headers={"x-forwarded-for": "203.0.113.2, 10.0.0.1"})
        other_hop = client.post("/review", headers={"x-forwarded-for": "203.0.113.1, 10.0.0.2"})
        other_cost = client.post("/review", headers={"x-forwarded-for": "10.0.0.3"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert other_hop.status_code == 200
    assert other_cost.status_code == 429
    assert other_cost.json()["error"]["code"] == "daily_cost_limit"


@pytest.mark.parametrize("path", ["/retrieve", "/review", "/review/stream"])
@pytest.mark.parametrize("suffix", ["", "/"])
def test_exhausted_requests_never_parse_the_body(tmp_path, monkeypatch, path, suffix):
    """Deny every public POST spelling before body parsing, retrieval, or a provider call."""
    app = _guarded_app(tmp_path)
    with TestClient(app) as client:
        assert client.post("/review", json={}).status_code == 200

        async def unexpected_body(self):
            """Fail if the guard attempts to decode an already denied request."""
            raise AssertionError("a denied request must not parse its body")

        monkeypatch.setattr(Request, "json", unexpected_body)
        response = client.post(path + suffix, content=b"malformed body")
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["retry-after"]) > 0


@pytest.mark.parametrize("size", [256 * 1024, 256 * 1024 + 1])
def test_denial_body_transfer_is_bounded_without_extending_retry(tmp_path, monkeypatch, size):
    """Reject oversized direct bodies and deduct transfer time from the original wait."""
    with TestClient(_guarded_app(tmp_path)) as client:
        assert client.post("/review", json={}).status_code == 200
        moments = iter((100.0, 110.0))
        monkeypatch.setattr("app.release.middleware.monotonic", lambda: next(moments))
        response = client.post("/review", content=b"x" * size)
    if size == 256 * 1024:
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "50"
    else:
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"
    assert response.headers["X-RateLimit-Remaining-Minute"] == "0"


def test_rejected_and_provider_free_requests_consume_slots_but_reads_do_not(tmp_path):
    """Validation, control rejection, and execution errors spend slots, while reads do not."""
    app = _guarded_app(tmp_path, per_minute=5, per_day=5)

    @app.post("/retrieve")
    async def retrieve(payload: dict):
        """Exercise route validation and a failing provider-free execution."""
        if payload.get("fail"):
            raise RuntimeError("failed search")
        return {"ok": True}

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post("/retrieve/", json={}).status_code == 200
        for path in ("/retrieve", "/limits", "/static/app.js"):
            assert client.get(path).status_code in {404, 405}
        malformed = client.post(
            "/retrieve", content=b"{", headers={"content-type": "application/json"}
        )
        assert malformed.status_code == 422
        assert malformed.headers["X-RateLimit-Remaining-Day"] == "3"
        denied = client.post(
            "/review/",
            json={"session_profile": {"engine": "local"}},
            headers={"x-docreview-public": "true"},
        )
        assert denied.status_code == 403
        assert denied.headers["X-RateLimit-Remaining-Day"] == "2"
        assert client.post("/retrieve", json={"fail": True}).status_code == 500
        final = client.post("/retrieve", json={})
        assert final.status_code == 200
        assert final.headers["X-RateLimit-Remaining-Day"] == "0"
        assert client.post("/retrieve", json={}).status_code == 429


def test_cancelled_execution_retains_its_request_slot(tmp_path):
    """Cancelling an admitted HTTP request does not refund its durable admission."""

    async def scenario():
        """Cancel through the real ASGI transport once the endpoint has started."""
        ledger = SharedAIAllowance(tmp_path / "cancel.sqlite3", Decimal("1"), 1, 1)
        app = FastAPI()
        app.add_middleware(ReleaseGuardMiddleware, allowance=ledger, trust_proxy_headers=False)
        started = asyncio.Event()
        cancelled = asyncio.Event()

        @app.post("/retrieve")
        async def retrieve():
            """Wait indefinitely until this request's transport is cancelled."""
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            pending = asyncio.create_task(client.post("/retrieve", json={}))
            await asyncio.wait_for(started.wait(), timeout=5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert cancelled.is_set()
            assert (await client.post("/retrieve", json={})).status_code == 429
            assert (await ledger.status())[0] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_stage", ["admission", "provider"])
def test_ledger_failure_blocks_work_with_503(tmp_path, monkeypatch, failure_stage):
    """An actual SQLite open failure blocks body parsing or the pending provider call."""
    ledger = SharedAIAllowance(tmp_path / "failed.sqlite3", Decimal("1"), 5, 5)
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(ReleaseGuardMiddleware, allowance=ledger, trust_proxy_headers=False)

    @app.post("/review")
    async def review():
        """Fail the cost ledger after admission, before any provider would be dispatched."""
        ledger.path = tmp_path
        await reserve_openai(Decimal("0.1"))
        raise AssertionError("provider must not run")

    if failure_stage == "admission":
        ledger.path = tmp_path  # Opening a directory as SQLite fails without altering any data.

        async def unexpected_body(self):
            """No request body may be parsed when admission cannot be enforced."""
            raise AssertionError("body must not be parsed")

        monkeypatch.setattr(Request, "json", unexpected_body)
    with TestClient(app) as client:
        response = client.post("/review", json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "allowance_unavailable"
    assert str(tmp_path) not in response.text


def test_server_secret_is_redacted_before_log_formatting() -> None:
    """Replace a configured secret in a log record before it is formatted."""
    secret = "sk-never-log-this"
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="provider failed for %(token)s",
        args=({"token": secret},),
        exc_info=None,
    )

    SecretRedactor((secret,)).redact(record)
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
        sinfo=f"Stack of request carrying {trace_secret}",
    )

    SecretRedactor((trace_secret,)).redact(exception_record)
    formatted = logging.Formatter().format(exception_record)
    assert exception_record.getMessage() == "provider failed"
    assert f"RuntimeError: provider rejected {REDACTION}" in formatted
    assert f"Stack of request carrying {REDACTION}" in formatted
    assert trace_secret not in formatted
    assert exception_record.exc_info is None


@pytest.fixture
def stock_record_factory() -> Iterator[None]:
    """Start from the stock record factory and restore whatever was installed before."""
    previous = logging.getLogRecordFactory()
    logging.setLogRecordFactory(logging.LogRecord)
    yield
    logging.setLogRecordFactory(previous)


@pytest.mark.usefixtures("stock_record_factory")
def test_installed_redaction_keeps_uvicorn_access_lines_formattable() -> None:
    """Redact a secret in an access line while uvicorn's formatter still unpacks its args."""
    secret = "sk-in-the-query"
    install_secret_redaction((secret,))
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        AccessFormatter(
            fmt='%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            use_colors=False,
        )
    )
    logger = logging.getLogger("uvicorn.access")
    level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1234",
            "GET",
            f"/health?key={secret}",
            "1.1",
            200,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)

    assert f'127.0.0.1:1234 - "GET /health?key={REDACTION} HTTP/1.1" 200' in stream.getvalue()
    assert secret not in stream.getvalue()


@pytest.mark.usefixtures("stock_record_factory")
def test_installed_redaction_covers_application_logger_tracebacks() -> None:
    """Redact the message and traceback an application logger hands to the root handlers."""
    secret, later_secret = "sk-in-the-traceback", "sk-installed-later"
    install_secret_redaction((secret,))
    install_secret_redaction((later_secret,))
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        try:
            raise RuntimeError(f"provider rejected {secret}")
        except RuntimeError as error:
            logging.getLogger("app.api.errors").error(
                "Unhandled API error on %s",
                f"/review?key={later_secret}",
                exc_info=(type(error), error, error.__traceback__),
            )
    finally:
        root.removeHandler(handler)

    assert f"Unhandled API error on /review?key={REDACTION}" in stream.getvalue()
    assert f"RuntimeError: provider rejected {REDACTION}" in stream.getvalue()
    assert secret not in stream.getvalue()
    assert later_secret not in stream.getvalue()


def test_public_proxy_marker_retains_cost_limits_without_charging_private_requests(
    tmp_path,
) -> None:
    """Only proxy-marked public reviews spend the cap when a private runtime serves both paths."""
    app = _guarded_app(
        tmp_path,
        enforce_rate_limit=False,
        per_minute=10,
        per_day=20,
        daily_limit=Decimal("0.04"),
        call_cost=Decimal("0.04"),
    )

    with TestClient(app) as client:
        for _ in range(2):
            assert client.post("/review", json={}).status_code == 200
        headers = {"x-docreview-public": "true"}
        assert client.post("/review", json={}, headers=headers).status_code == 200
        blocked = client.post("/review", json={}, headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "daily_cost_limit"
        assert client.post("/review", json={}).status_code == 200
