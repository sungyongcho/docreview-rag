"""Request guards: security headers, client identity, and blocked routes."""

from hashlib import blake2s
from ipaddress import ip_address
from math import ceil
from time import monotonic
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.review.profiles import PromptPolicy, public_custom_retrieval_violation
from app.release.ai_allowance import (
    AIAllowanceError,
    SharedAIAllowance,
    active_allowance,
)

SECURITY_HEADERS = {
    "cache-control": "no-store",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-site",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
}
# The routes whose POST handlers may reach an embedding or text provider.
AI_ROUTES = frozenset({"/retrieve", "/review", "/review/stream"})
EXECUTION_BODY_LIMIT = 256 * 1024


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
    """Resolve one client address, trusting forwarded input only when configured.

    The trusted Caddy hop overwrites X-Forwarded-For with its immediate peer, which
    is a shared Worker egress address on the public path, not a visitor identity.
    Only the last entry is used; other visitor-address headers are never consulted.
    """
    direct = request.client.host if request.client is not None else "unknown"
    if not trust_proxy_headers:
        return direct
    forwarded = request.headers.get("x-forwarded-for", "").rsplit(",", maxsplit=1)[-1].strip()
    if not forwarded:
        return direct
    try:
        return str(ip_address(forwarded))
    except ValueError:
        return direct


def client_key(request: Request, *, trust_proxy_headers: bool, salt: bytes) -> str:
    """Derive the keyed, non-reversible client identity the allowance ledger tracks."""
    host = client_host(request, trust_proxy_headers=trust_proxy_headers)
    return blake2s(host.encode("utf-8"), key=salt, digest_size=16).hexdigest()


def _forbidden(code: str, message: str) -> JSONResponse:
    """Return the shared guard envelope without changing route-specific denial details."""
    return JSONResponse(
        status_code=403,
        content={"error": {"code": code, "message": message, "details": []}},
    )


PUBLIC_LOCK_MESSAGE = "This control runs in DEV mode only."


def _control_denial(profile: dict[str, object]) -> str | None:
    """Name the developer control a public request may not use, or None when it may proceed.

    Bounded Custom retrieval is public; malformed fields are left to route validation.
    """
    policy = profile.get("prompt_policy")
    try:
        if policy is not None and PromptPolicy.model_validate(policy) != PromptPolicy():
            return PUBLIC_LOCK_MESSAGE
    except ValidationError:
        pass  # The route returns its normal typed validation error.
    if profile.get("snapshot_id") is not None:
        return PUBLIC_LOCK_MESSAGE
    if profile.get("retrieval_preset") == "custom":
        retrieval = profile.get("custom_retrieval")
        violation = (
            public_custom_retrieval_violation(retrieval) if isinstance(retrieval, dict) else None
        )
        if violation is not None:
            return f"{PUBLIC_LOCK_MESSAGE} {violation}."
    return None


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
    """Guard public controls and meter provider-bearing requests with the shared AI allowance."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowance: SharedAIAllowance,
        trust_proxy_headers: bool,
        enforce_rate_limit: bool = True,
        public_read_only: bool = False,
        allow_local_engine: bool = True,
        local_connection_origin: str | None = None,
    ) -> None:
        super().__init__(app)
        self._allowance = allowance
        self._trust_proxy_headers = trust_proxy_headers
        self._enforce_rate_limit = enforce_rate_limit
        self._public_read_only = public_read_only
        self._allow_local_engine = allow_local_engine
        self._local_connection_origin = (
            _loopback_origin(local_connection_origin) if local_connection_origin else None
        )

    def _client_key(self, request: Request) -> str:
        """Key this client with the ledger's persisted salt so identities survive restarts."""
        return client_key(
            request, trust_proxy_headers=self._trust_proxy_headers, salt=self._allowance.salt
        )

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
        """Reject local or custom controls after admission but before execution or AI cost."""
        try:
            payload = await request.json()
        except ValueError:
            payload = {}
        profile = payload.get("session_profile", {}) if isinstance(payload, dict) else {}
        profile = profile if isinstance(profile, dict) else {}
        local = profile.get("engine") == "local"
        if local and not self._allow_local_engine:
            return _forbidden("disabled_in_prod", "Local LLM is disabled in production.")
        if public:
            denial = PUBLIC_LOCK_MESSAGE if local else _control_denial(profile)
            if denial is not None:
                return _forbidden("capability_disabled", denial)
        return None

    async def _allowance_response(self, request: Request, error: AIAllowanceError) -> Response:
        """Finish bounded body transfer before denial so Caddy can enforce its size limit.

        Caddy 2.10 detects max_size while forwarding a body. An immediate upstream
        response can win that race, so drain without parsing or executing anything.
        Direct requests are bounded too; disconnects propagate without refunding admission.
        """
        retry_at = monotonic() + error.retry_after
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > EXECUTION_BODY_LIMIT:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "request_too_large",
                            "message": "The execution request body exceeds 256 KiB.",
                            "details": [],
                        }
                    },
                )
        detail = {"code": error.code, "message": str(error), "details": []}
        if error.reset is not None:
            detail["reset_at"] = error.reset.isoformat()
        return JSONResponse(
            status_code=error.status_code,
            content={"error": detail},
            headers={"Retry-After": str(max(1, ceil(retry_at - monotonic())))},
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Gate one request through the public controls and the shared AI allowance.

        Parameters
        ----------
        request : Request
            Incoming request; its client address is hashed with the ledger's salt
            before it is used as an allowance key.
        call_next : RequestResponseEndpoint
            Continuation invoked only when every guard admits the request.

        Returns
        -------
        Response
            The downstream response with rate-limit headers, or a structured
            403/413/429/503 error body that never reaches the application.

        Notes
        -----
        POST execution requests consume a slot before their bodies are parsed, including
        invalid, cancelled, and provider-free requests. Reads stay unmetered. When public
        limits are not enforced, the loopback operator's own requests bypass the
        allowance entirely while proxy-marked public requests stay metered.
        """
        public = self._public_read_only or request.headers.get("x-docreview-public") == "true"
        if public and (request.url.path == "/admin" or request.url.path.startswith("/admin/")):
            return _forbidden("capability_disabled", "Administrator resources are private.")
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.url.path.startswith(("/admin/local-llm/", "/admin/openai/"))
            and not self._local_connection_origin_allowed(request)
        ):
            return _forbidden(
                "origin_not_allowed",
                "Local LLM and OpenAI cap settings require the configured local web origin.",
            )
        path = request.url.path.rstrip("/")
        if request.method != "POST" or path not in AI_ROUTES:
            return await call_next(request)
        # Route both spellings directly, so a 307 cannot debit one submission twice.
        request.scope["path"] = path
        request.scope["raw_path"] = path.encode("ascii")
        metered = self._enforce_rate_limit or public
        decision = None
        token = None
        try:
            if metered:
                decision = await self._allowance.admit(self._client_key(request))
                if not decision.allowed:
                    raise AIAllowanceError(
                        "rate_limited",
                        "The shared server request limit was reached.",
                        decision.retry_after_seconds,
                    )
                token = active_allowance.set(self._allowance)
            response = await self._review_policy_response(request, public=public)
            if response is None:
                response = await call_next(request)
        except AIAllowanceError as error:
            response = await self._allowance_response(request, error)
        finally:
            if token is not None:
                active_allowance.reset(token)
        if decision is not None:
            response.headers["X-RateLimit-Remaining-Minute"] = str(decision.remaining_minute)
            response.headers["X-RateLimit-Remaining-Day"] = str(decision.remaining_day)
        return response
