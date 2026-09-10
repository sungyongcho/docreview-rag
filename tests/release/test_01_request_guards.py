"""Public middleware, headers, and secret-redaction tests."""

import asyncio
import logging
import sys

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from app.release.limiter import DailyCostLimiter, InProcessRateLimiter
from app.release.middleware import (
    ReleaseGuardMiddleware,
    SecurityHeadersMiddleware,
    client_host,
)
from app.release.secrets import REDACTION, SecretRedactionFilter


def _guarded_app(*, enforce_rate_limit: bool = True) -> FastAPI:
    """Build one application behind the release guards."""
    app = FastAPI()
    app.add_middleware(
        ReleaseGuardMiddleware,
        limiter=InProcessRateLimiter(per_minute=1, per_day=2, max_clients=8),
        trust_proxy_headers=False,
        allow_ingest=False,
        enforce_rate_limit=enforce_rate_limit,
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


def test_local_operator_bypasses_public_rate_limit_but_not_ingest_guard() -> None:
    """Keep loopback operator work unlimited without opening the public ingest route."""
    with TestClient(_guarded_app(enforce_rate_limit=False)) as client:
        responses = [client.post("/work") for _ in range(3)]
        ingest = client.post("/ingest")

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert all("x-ratelimit-remaining-minute" not in response.headers for response in responses)
    assert ingest.status_code == 403


def test_daily_cost_limiter_reserves_worst_case_and_resets_by_day() -> None:
    """Refuse provider work once worst-case reservations exhaust the UTC-day budget."""
    from datetime import date
    from decimal import Decimal

    day = [date(2026, 9, 1)]
    limiter = DailyCostLimiter(
        daily_limit_usd=Decimal("0.02"),
        reservation_usd=Decimal("0.01"),
        today=lambda: day[0],
    )

    assert asyncio.run(limiter.reserve()) == (True, Decimal("0.01"))
    assert asyncio.run(limiter.reserve()) == (True, Decimal("0.00"))
    assert asyncio.run(limiter.reserve()) == (False, Decimal("0.00"))
    remaining, reset = asyncio.run(limiter.status())
    assert remaining == Decimal("0.00")
    assert reset.isoformat() == "2026-09-02T00:00:00+00:00"
    day[0] = date(2026, 9, 2)
    assert asyncio.run(limiter.reserve()) == (True, Decimal("0.01"))


def test_review_route_fails_closed_after_daily_cost_reservation() -> None:
    """Return a typed fallback signal before a provider route exceeds the daily cap."""
    from decimal import Decimal

    app = FastAPI()
    app.add_middleware(
        ReleaseGuardMiddleware,
        limiter=InProcessRateLimiter(per_minute=10, per_day=10, max_clients=4),
        trust_proxy_headers=False,
        allow_ingest=False,
        cost_limiter=DailyCostLimiter(
            daily_limit_usd=Decimal("0.01"),
            reservation_usd=Decimal("0.01"),
        ),
    )

    @app.post("/review")
    async def review() -> dict[str, str]:
        """Stand in for one cost-bearing provider route."""
        return {"status": "ok"}

    with TestClient(app) as client:
        first = client.post("/review")
        blocked = client.post("/review")

    assert first.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "daily_cost_limit"


def test_public_proxy_marker_blocks_dev_only_review_policy() -> None:
    """Reject custom prompt, retrieval, and snapshot controls before route execution."""
    app = FastAPI()
    app.add_middleware(
        ReleaseGuardMiddleware,
        limiter=InProcessRateLimiter(per_minute=10, per_day=10, max_clients=4),
        trust_proxy_headers=False,
        allow_ingest=False,
    )

    @app.post("/review")
    async def review() -> dict[str, str]:
        """Stand in for a provider route that must remain unreachable."""
        return {"status": "unexpected"}

    with TestClient(app) as client:
        response = client.post(
            "/review",
            headers={"X-DocReview-Public": "true"},
            json={
                "query": "Revenue?",
                "session_profile": {
                    "retrieval_preset": "balanced",
                    "snapshot_id": 3,
                },
            },
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "capability_disabled"
    assert response.json()["error"]["message"] == "This control runs in DEV mode only."


def _review_app() -> FastAPI:
    """Build one guarded review route that reports whether the guard admitted the request."""
    app = FastAPI()
    app.add_middleware(
        ReleaseGuardMiddleware,
        limiter=InProcessRateLimiter(per_minute=50, per_day=50, max_clients=4),
        trust_proxy_headers=False,
        allow_ingest=False,
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


@pytest.mark.parametrize(
    "retrieval",
    [
        {},
        {"k": 10, "candidate_k": 50, "lexical_ranker": "bm25", "reranker": "cross_encoder"},
        {"strategy": "vector", "lexical_ranker": None},
    ],
)
def test_public_custom_retrieval_within_bounds_reaches_the_route(retrieval) -> None:
    """Admit the Custom preset publicly while its depth stays inside the built-in envelope."""
    with TestClient(_review_app()) as client:
        response = client.post(
            "/review",
            headers={"X-DocReview-Public": "true"},
            json={"query": "Revenue?", "session_profile": _custom_profile(**retrieval)},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "admitted"}


@pytest.mark.parametrize(
    ("retrieval", "field"),
    [
        ({"k": 11, "candidate_k": 50}, "custom_retrieval.k"),
        ({"k": 5, "candidate_k": 51}, "custom_retrieval.candidate_k"),
    ],
)
def test_public_custom_retrieval_above_bounds_names_the_field(retrieval, field) -> None:
    """Reject oversized Custom depth with the shared lock message naming the exceeded field."""
    with TestClient(_review_app()) as client:
        response = client.post(
            "/review",
            headers={"X-DocReview-Public": "true"},
            json={"query": "Revenue?", "session_profile": _custom_profile(**retrieval)},
        )

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "capability_disabled"
    assert error["message"].startswith("This control runs in DEV mode only.")
    assert field in error["message"]


@pytest.mark.parametrize(
    ("payload", "profile"),
    [
        ({}, {"prompt_policy": {"additional_instructions": "Be concise."}}),
        ({"budget": {"max_iterations": 1}}, {}),
        ({}, {"engine": "local"}),
        ({}, {"snapshot_id": 3}),
    ],
)
def test_public_prompt_budget_local_and_snapshot_controls_stay_locked(payload, profile) -> None:
    """Keep every non-retrieval developer control behind the one DEV-mode lock."""
    with TestClient(_review_app()) as client:
        response = client.post(
            "/review",
            headers={"X-DocReview-Public": "true"},
            json={"query": "Revenue?", "session_profile": profile, **payload},
        )

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "capability_disabled"
    assert error["message"] == "This control runs in DEV mode only."


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


def test_public_proxy_marker_retains_rate_limits_on_a_private_admin_runtime() -> None:
    """A public request remains metered even when the same process serves private SSH admin."""
    with TestClient(_guarded_app(enforce_rate_limit=False)) as client:
        headers = {"x-docreview-public": "true"}
        assert client.post("/work", headers=headers).status_code == 200
        assert client.post("/work", headers=headers).status_code == 429
        assert client.post("/work").status_code == 200


def test_public_proxy_marker_retains_cost_limits_without_charging_private_requests() -> None:
    """Only proxy-marked public reviews reserve cost when a private runtime serves both paths."""
    from decimal import Decimal

    app = FastAPI()
    app.add_middleware(
        ReleaseGuardMiddleware,
        limiter=InProcessRateLimiter(per_minute=10, per_day=20, max_clients=8),
        trust_proxy_headers=False,
        allow_ingest=False,
        enforce_rate_limit=False,
        cost_limiter=DailyCostLimiter(
            daily_limit_usd=Decimal("0.04"),
            reservation_usd=Decimal("0.04"),
        ),
    )

    @app.post("/review")
    async def review() -> dict[str, str]:
        """Return without provider calls so only the cost guard determines admission."""
        return {"status": "ok"}

    with TestClient(app) as client:
        for _ in range(2):
            assert client.post("/review", json={}).status_code == 200
        headers = {"x-docreview-public": "true"}
        assert client.post("/review", json={}, headers=headers).status_code == 200
        blocked = client.post("/review", json={}, headers=headers)
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "daily_cost_limit"
        assert client.post("/review", json={}).status_code == 200
