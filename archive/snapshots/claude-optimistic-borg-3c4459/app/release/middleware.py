"""Request guards: security headers, client identity, and blocked routes."""

from hashlib import blake2s
from ipaddress import ip_address
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.review_profile import PromptPolicy
from app.release.limiter import DailyCostLimiter, InProcessRateLimiter

SECURITY_HEADERS = {
    "cache-control": "no-store",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-site",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
}


class SecurityHeadersMiddleware:
    """Add conservative headers while preserving Hugging Face iframe embedding."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Forward the ASGI call, appending only headers the response did not set."""

        async def send_with_headers(message: Message) -> None:
            """Add each security header the response did not already set."""
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", ()))
                existing = {name.lower() for name, _ in headers}
                for name, value in SECURITY_HEADERS.items():
                    encoded_name = name.encode("latin-1")
                    if encoded_name not in existing:
                        headers.append((encoded_name, value.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


def client_host(request: Request, *, trust_proxy_headers: bool) -> str:
    """Resolve one client address, trusting forwarded input only when configured."""
    direct = request.client.host if request.client is not None else "unknown"
    if not trust_proxy_headers:
        return direct
    forwarded = request.headers.get("x-forwarded-for", "").split(",", maxsplit=1)[0].strip()
    if not forwarded:
        return direct
    try:
        return str(ip_address(forwarded))
    except ValueError:
        return direct


class ReleaseGuardMiddleware(BaseHTTPMiddleware):
    """Protect state-changing and compute-bearing requests on one public worker."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: InProcessRateLimiter,
        trust_proxy_headers: bool,
        allow_ingest: bool,
        enforce_rate_limit: bool = True,
        cost_limiter: DailyCostLimiter | None = None,
        salt: bytes | None = None,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._trust_proxy_headers = trust_proxy_headers
        self._allow_ingest = allow_ingest
        self._enforce_rate_limit = enforce_rate_limit
        self._cost_limiter = cost_limiter
        self._salt = salt or secrets.token_bytes(32)

    def _client_key(self, request: Request) -> str:
        """Derive a keyed, non-reversible identity for one client host."""
        host = client_host(request, trust_proxy_headers=self._trust_proxy_headers)
        return blake2s(host.encode("utf-8"), key=self._salt, digest_size=16).hexdigest()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Gate one request through the ingest lock and the per-client rate limit.

        Parameters
        ----------
        request : Request
            Incoming request; its client address is hashed with a per-process salt
            before it is used as a limiter key.
        call_next : RequestResponseEndpoint
            Continuation invoked only when every guard admits the request.

        Returns
        -------
        Response
            The downstream response with rate-limit headers, or a structured
            403/429 error body that never reaches the application.

        Notes
        -----
        Only state-changing methods consume the rate limit; reads pass through
        so probes and static assets stay unmetered.
        """
        if request.url.path == "/ingest" and not self._allow_ingest:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "release_read_only",
                        "message": "Ingestion is disabled on the public release surface.",
                        "details": [],
                    }
                },
            )

        if request.headers.get("x-docreview-public") == "true" and request.url.path in {
            "/review",
            "/review/stream",
        }:
            try:
                payload = await request.json()
            except ValueError:
                payload = {}
            profile = payload.get("session_profile", {}) if isinstance(payload, dict) else {}
            policy = profile.get("prompt_policy") if isinstance(profile, dict) else None
            custom_policy = (
                policy is not None and PromptPolicy.model_validate(policy) != PromptPolicy()
            )
            custom_retrieval = (
                isinstance(profile, dict) and profile.get("retrieval_preset") == "custom"
            )
            snapshot_query = isinstance(profile, dict) and profile.get("snapshot_id") is not None
            if custom_policy or custom_retrieval or snapshot_query:
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "capability_disabled",
                            "message": "Production experiment controls are read-only.",
                            "details": [],
                        }
                    },
                )

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if not self._enforce_rate_limit:
                return await call_next(request)
            decision = await self._limiter.check(self._client_key(request))
            if not decision.allowed:
                return JSONResponse(
                    status_code=429,
                    headers={
                        "Retry-After": str(decision.retry_after_seconds),
                        "X-RateLimit-Remaining-Minute": str(decision.remaining_minute),
                        "X-RateLimit-Remaining-Day": str(decision.remaining_day),
                    },
                    content={
                        "error": {
                            "code": "rate_limited",
                            "message": "The single-instance service request limit was reached.",
                            "details": [],
                        }
                    },
                )
            if request.url.path in {"/review", "/review/stream"} and self._cost_limiter is not None:
                allowed, remaining = await self._cost_limiter.reserve()
                if not allowed:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": {
                                "code": "daily_cost_limit",
                                "message": (
                                    "The public answer budget is exhausted; use retrieval evidence "
                                    "without an LLM answer."
                                ),
                                "details": [],
                            }
                        },
                        headers={"X-DocReview-Daily-Cost-Remaining-USD": format(remaining, "f")},
                    )
            response = await call_next(request)
            response.headers["X-RateLimit-Remaining-Minute"] = str(decision.remaining_minute)
            response.headers["X-RateLimit-Remaining-Day"] = str(decision.remaining_day)
            return response

        return await call_next(request)
