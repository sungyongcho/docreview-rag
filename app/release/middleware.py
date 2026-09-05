"""Request guards: security headers, client identity, and blocked routes."""

from hashlib import blake2s
from ipaddress import ip_address
import secrets
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.review_profile import PromptPolicy
from app.observability.types import Budget
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


def _forbidden(code: str, message: str) -> JSONResponse:
    """Return the shared guard envelope without changing route-specific denial details."""
    return JSONResponse(
        status_code=403,
        content={"error": {"code": code, "message": message, "details": []}},
    )


def _custom_controls(payload: object, profile: dict[str, object]) -> bool:
    """Detect developer controls while leaving malformed fields to route validation."""
    policy = profile.get("prompt_policy")
    try:
        custom_policy = policy is not None and PromptPolicy.model_validate(policy) != PromptPolicy()
    except ValidationError:
        custom_policy = False  # The route returns its normal typed validation error.
    legacy_limits = False
    if isinstance(payload, dict):
        try:
            legacy_limits = (
                payload.get("budget") is not None
                and Budget.model_validate(payload["budget"]) != Budget()
            ) or payload.get("max_context_chars", 12_000) != 12_000
        except ValidationError:
            pass  # Request validation still reports malformed values.
    return (
        legacy_limits
        or custom_policy
        or profile.get("retrieval_preset") == "custom"
        or profile.get("snapshot_id") is not None
    )


def _loopback_origin(value: str) -> tuple[str, str, int] | None:
    """Parse a browser origin without accepting credentials, paths, or nonlocal hosts."""
    try:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.path
            or url.query
            or url.fragment
        ):
            return None
        host = url.hostname.lower()
        if host != "localhost" and not ip_address(host).is_loopback:
            return None
        port = url.port
        return (
            url.scheme,
            host,
            port if port is not None else (443 if url.scheme == "https" else 80),
        )
    except ValueError:
        return None


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
        public_read_only: bool = False,
        allow_local_engine: bool = True,
        local_connection_origin: str | None = None,
        cost_limiter: DailyCostLimiter | None = None,
        salt: bytes | None = None,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._trust_proxy_headers = trust_proxy_headers
        self._allow_ingest = allow_ingest
        self._enforce_rate_limit = enforce_rate_limit
        self._public_read_only = public_read_only
        self._allow_local_engine = allow_local_engine
        self._local_connection_origin = (
            _loopback_origin(local_connection_origin) if local_connection_origin else None
        )
        self._cost_limiter = cost_limiter
        self._salt = salt or secrets.token_bytes(32)

    def _client_key(self, request: Request) -> str:
        """Derive a keyed, non-reversible identity for one client host."""
        host = client_host(request, trust_proxy_headers=self._trust_proxy_headers)
        return blake2s(host.encode("utf-8"), key=self._salt, digest_size=16).hexdigest()

    def _local_connection_origin_allowed(self, request: Request) -> bool:
        """Admit headerless tools or explicit local browser origins, never forwarded guesses."""
        origin_header = request.headers.get("origin")
        if origin_header is None:
            # CLI and SSH clients do not carry browser ambient authority or an Origin.
            return True
        origin = _loopback_origin(origin_header)
        if origin is None:
            return False
        actual = _loopback_origin(f"{request.url.scheme}://{request.headers.get('host', '')}")
        if origin == actual:
            return True
        configured = self._local_connection_origin
        if configured is None:
            return False
        # Next rewrites Host to the backend service. The explicitly configured web
        # origin authorizes that path; untrusted X-Forwarded-* values cannot widen it.
        scheme, _, port = configured
        return origin in {
            configured,
            (scheme, "localhost", port),
            (scheme, "127.0.0.1", port),
        }

    async def _review_policy_response(self, request: Request, *, public: bool) -> Response | None:
        """Reject local or custom controls before rate and cost reservations are consumed."""
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        profile = payload.get("session_profile", {}) if isinstance(payload, dict) else {}
        profile = profile if isinstance(profile, dict) else {}
        custom = _custom_controls(payload, profile)
        local = profile.get("engine") == "local"
        if local and not self._allow_local_engine:
            return _forbidden("disabled_in_prod", "Local LLM is disabled in production.")
        if public and (custom or local):
            return _forbidden(
                "capability_disabled", "Production experiment controls are read-only."
            )
        return None

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
            return _forbidden(
                "release_read_only", "Ingestion is disabled on the public release surface."
            )

        public = self._public_read_only or request.headers.get("x-docreview-public") == "true"
        if public and (request.url.path == "/admin" or request.url.path.startswith("/admin/")):
            return _forbidden("capability_disabled", "Administrator resources are private.")
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.url.path.startswith("/admin/local-llm/")
            and not self._local_connection_origin_allowed(request)
        ):
            return _forbidden(
                "origin_not_allowed", "Local LLM settings require the configured local web origin."
            )
        if request.url.path in {"/retrieve", "/review", "/review/stream"}:
            denied = await self._review_policy_response(request, public=public)
            if denied is not None:
                return denied

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if not self._enforce_rate_limit and not public:
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
