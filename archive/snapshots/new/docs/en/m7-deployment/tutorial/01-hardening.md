# M7.1 Tutorial 1 — Design for traffic you cannot control

The moment a link is public, there is no knowing who calls it or how often. So the release composition behaves this way by default.

- return **deterministic canned evidence** (no provider calls)
- **disable ingestion** — a public endpoint has no business touching the corpus
- **rate-limit POST-like work**
- expose **only non-secret release state**

Runtime mode turns on only by explicit selection, and even then token and estimated-cost ceilings apply.

**Prerequisite:** The M5 service works and `uv run pytest tests/api -q` passes.

### Why the defenses come in six layers

One layer is not enough. Each one stops a different failure.

1. `ReleaseSettings` validates mode, limits, and provider budgets. 2. `InProcessRateLimiter` tracks bounded rolling windows for one-process deployment. 3. `ReleaseGuardMiddleware` hashes client identity, blocks ingestion, and emits typed 403 or 429 responses. 4. `SecurityHeadersMiddleware` wraps every response, including guard failures. 5. `create_release_app()` composes canned or explicitly enabled runtime services. 6. `app/release/space.py` exposes the single-process Space entrypoint.

This document builds 1 through 4; the next builds 5 and 6.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `ReleaseSettings` | **Define the settings schema** | Writing the public cost boundary as a value |
| `InProcessRateLimiter` | **Implement** the window arithmetic yourself | Keeping memory from growing without bound |
| `client_host` | **Implement** the trust decision yourself | Why proxy headers are not trusted by default |
| `ReleaseGuardMiddleware` | **Implement** the guard order yourself | Whether blocking precedes or follows response headers |
| `SecretRedactionFilter` | **Implement** the redaction rules yourself | Why logs are the last leak path |

### 1. Writing the public cost boundary as a value

#### Create `app/release/config.py` — module header

**Learning action — define the structure:** it uses `BaseSettings`, meaning it reads from environment variables.

```python
"""Strict environment configuration for one low-cost demo instance."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.llm import ProviderBudget, TokenPricing

```

#### Complete `app/release/config.py` — release settings

**Learning action — define the settings schema:** read the fields grouped by responsibility rather than one at a time.

<!-- src: app/release/config.py::ReleaseSettings -->
```python
class ReleaseSettings(BaseSettings):
    """Release controls that default to a zero-provider-call canned demo."""

    model_config = SettingsConfigDict(
        env_prefix="DOCREVIEW_",
        extra="ignore",
        frozen=True,
    )

    mode: Literal["canned", "runtime"] = "canned"
    host: str = "0.0.0.0"
    port: int = Field(default=7860, ge=1, le=65_535)
    rate_limit_per_minute: int = Field(default=10, ge=1, le=1_000)
    rate_limit_per_day: int = Field(default=100, ge=1, le=100_000)
    rate_limit_max_clients: int = Field(default=1_024, ge=1, le=100_000)
    trust_proxy_headers: bool = False
    allow_ingest: bool = False

    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("DOCREVIEW_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    openai_model: str = "gpt-4.1-mini"
    openai_max_input_tokens: int = Field(default=12_000, ge=1, le=100_000)
    openai_max_output_tokens: int = Field(default=600, ge=1, le=4_000)
    openai_max_cost_usd: Decimal = Field(default=Decimal("0.01"), ge=0, le=1)
    openai_input_per_million_usd: Decimal = Field(default=Decimal("0.40"), ge=0)
    openai_output_per_million_usd: Decimal = Field(default=Decimal("1.60"), ge=0)

    @model_validator(mode="after")
    def validate_release_limits(self) -> Self:
        """Keep the rolling-day limit and public identity internally consistent."""
        if self.rate_limit_per_day < self.rate_limit_per_minute:
            raise ValueError("rate_limit_per_day must be at least rate_limit_per_minute")
        if not self.host.strip():
            raise ValueError("host must not be blank")
        if not self.openai_model.strip():
            raise ValueError("openai_model must not be blank")
        return self

    @property
    def openai_enabled(self) -> bool:
        """Report secret presence without exposing the secret value."""
        return self.mode == "runtime" and self.openai_api_key is not None

    def provider_budget(self) -> ProviderBudget:
        """Build the explicit provider cap used by every optional live review."""
        return ProviderBudget(
            max_input_tokens=self.openai_max_input_tokens,
            max_output_tokens=self.openai_max_output_tokens,
            max_cost_usd=self.openai_max_cost_usd,
            pricing=TokenPricing(
                input_per_million_usd=self.openai_input_per_million_usd,
                output_per_million_usd=self.openai_output_per_million_usd,
            ),
        )
```

| Settings group | Fields and defaults | Role |
|---|---|---|
| execution mode | `mode="canned"` | Makes the zero-provider-call path the default and requires explicit runtime selection. |
| listener | `host="0.0.0.0"`, `port=7860` | Defines the single public process address. |
| rate limits | `rate_limit_per_minute=10`, `rate_limit_per_day=100`, `rate_limit_max_clients=1024` | Bounds request volume and in-memory client state. |
| request trust | `trust_proxy_headers=False`, `allow_ingest=False` | Rejects untrusted forwarded identity and public corpus mutation by default. |
| provider identity | `openai_api_key=None`, `openai_model="gpt-4.1-mini"` | Keeps secret presence separate from explicit runtime activation. |
| provider budget | `openai_max_input_tokens`, `openai_max_output_tokens`, `openai_max_cost_usd` | Caps one optional live completion before it runs. |
| pricing | `openai_input_per_million_usd`, `openai_output_per_million_usd` | Makes the cost estimate explicit and reviewable. |

**What to look for in the code**

- `mode` defaults to `"canned"`. With no environment variable set at all, **no money leaves.**
- Even with an `openai_api_key` present, nothing is called while `mode` is `canned`. **Separating secret presence from activation** is the same family as M5.2's XOR constraint.
- `rate_limit_max_clients` is a field. Rate limiting costs memory, so that memory needs a ceiling too.

### 2. Keeping memory from growing without bound

#### Create `app/release/limiter.py` — module header and window record

**Learning action — define the structure:** two second-valued constants and one decision record.

```python
"""Bounded in-process rate limiting for a single demo worker."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
import math
import time
```

<!-- src: app/release/limiter.py::MINUTE_SECONDS,_ClientWindow -->
```python
MINUTE_SECONDS = 60.0
DAY_SECONDS = 86_400.0


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """One allow or deny decision with bounded retry metadata."""

    allowed: bool
    retry_after_seconds: int
    remaining_minute: int
    remaining_day: int


@dataclass(slots=True)
class _ClientWindow:
    timestamps: deque[float] = field(default_factory=deque)
    last_seen: float = 0.0
```

**What to look for in the code**

- `RateLimitDecision` returns retry metadata alongside the boolean. Report only the denial and the caller has no idea when to try again, so it retries immediately and gets denied again.
- `frozen=True` is on the decision, mutable `_ClientWindow` on the state. A verdict must not change and a window must — and the decorators say exactly that.
- A `deque` is used because dropping expired timestamps from the front is constant time. With a list, every `pop(0)` shifts the whole thing.
- `last_seen` exists so windows for long-quiet clients can be reclaimed. Without that field, every client that ever connected stays in memory forever.

#### Complete `app/release/limiter.py` — the in-process rate limiter

**Learning action — implement the window arithmetic:** implement how the minute window and the day window each advance.

<!-- src: app/release/limiter.py::InProcessRateLimiter -->
```python
class InProcessRateLimiter:
    """Enforce rolling minute/day limits with bounded LRU client state.

    This limiter intentionally targets one process. Multiple workers or replicas each own
    independent counters and require an external shared limiter before public scale-out.
    """

    def __init__(
        self,
        *,
        per_minute: int,
        per_day: int,
        max_clients: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min(per_minute, per_day, max_clients) <= 0:
            raise ValueError("rate limits and max_clients must be positive")
        if per_day < per_minute:
            raise ValueError("per_day must be at least per_minute")
        self._per_minute = per_minute
        self._per_day = per_day
        self._max_clients = max_clients
        self._clock = clock
        self._clients: OrderedDict[str, _ClientWindow] = OrderedDict()
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        """Return the current bounded state size for diagnostics and tests."""
        return len(self._clients)

    async def check(self, client_key: str) -> RateLimitDecision:
        """Atomically consume one request slot or return a retry decision."""
        if not isinstance(client_key, str) or not client_key:
            raise ValueError("client_key must be a nonblank string")
        now = self._clock()
        if not isinstance(now, int | float) or not math.isfinite(now) or now < 0:
            raise ValueError("clock must return a finite nonnegative value")

        async with self._lock:
            window = self._clients.pop(client_key, None)
            if window is None:
                if len(self._clients) >= self._max_clients:
                    self._clients.popitem(last=False)
                window = _ClientWindow()
            self._clients[client_key] = window
            window.last_seen = float(now)

            day_cutoff = now - DAY_SECONDS
            while window.timestamps and window.timestamps[0] <= day_cutoff:
                window.timestamps.popleft()

            minute_cutoff = now - MINUTE_SECONDS
            minute_count = sum(timestamp > minute_cutoff for timestamp in window.timestamps)
            day_count = len(window.timestamps)

            if minute_count >= self._per_minute:
                minute_start = next(
                    timestamp for timestamp in window.timestamps if timestamp > minute_cutoff
                )
                retry = max(1, math.ceil(minute_start + MINUTE_SECONDS - now))
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=retry,
                    remaining_minute=0,
                    remaining_day=max(0, self._per_day - day_count),
                )
            if day_count >= self._per_day:
                retry = max(1, math.ceil(window.timestamps[0] + DAY_SECONDS - now))
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=retry,
                    remaining_minute=max(0, self._per_minute - minute_count),
                    remaining_day=0,
                )

            window.timestamps.append(float(now))
            return RateLimitDecision(
                allowed=True,
                retry_after_seconds=0,
                remaining_minute=self._per_minute - minute_count - 1,
                remaining_day=self._per_day - day_count - 1,
            )
```

**What to look for in the code**

- It is **in-process**. There is no Redis. The single-process deployment assumption is baked into the name, so the fact that going multi-process requires replacing this class is never hidden.
- Client count has a ceiling. Past it, the oldest entries are dropped — that stops an attacker from filling memory by rotating IPs.
- `RateLimitDecision` carries `retry_after`. It goes straight into the 429 response.

### 3. Not trusting proxy headers by default

#### Create `app/release/middleware.py` — module header and security headers

**Learning action — implement the trust decision:** implement `client_host` yourself. Note what gets ignored when `trust_proxy_headers` is `False`.

```python
"""Public-instance request guards and response security headers."""

from __future__ import annotations

from hashlib import blake2s
from ipaddress import ip_address
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.release.limiter import InProcessRateLimiter
```

<!-- src: app/release/middleware.py::SECURITY_HEADERS,client_host -->
```python
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
        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", ()))
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
```

**What to look for in the code**

- `X-Forwarded-For` is **ignored by default.** A client can send that header freely, so until you declare that a trusted proxy sits in front, it is a bypass around rate limiting.
- `SECURITY_HEADERS` is a constant dictionary. The middleware attaches it to every response.

#### Complete `app/release/middleware.py` — the release guard

**Learning action — implement the guard order:** decide for yourself whether ingestion blocking or rate limiting comes first.

<!-- src: app/release/middleware.py::ReleaseGuardMiddleware -->
```python
class ReleaseGuardMiddleware(BaseHTTPMiddleware):
    """Protect state-changing and compute-bearing requests on one public worker."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: InProcessRateLimiter,
        trust_proxy_headers: bool,
        allow_ingest: bool,
        salt: bytes | None = None,
    ) -> None:
        super().__init__(app)
        self._limiter = limiter
        self._trust_proxy_headers = trust_proxy_headers
        self._allow_ingest = allow_ingest
        self._salt = salt or secrets.token_bytes(32)

    def _client_key(self, request: Request) -> str:
        host = client_host(request, trust_proxy_headers=self._trust_proxy_headers)
        return blake2s(host.encode("utf-8"), key=self._salt, digest_size=16).hexdigest()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
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

        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
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
                            "message": "The single-instance demo request limit was reached.",
                            "details": [],
                        }
                    },
                )
            response = await call_next(request)
            response.headers["X-RateLimit-Remaining-Minute"] = str(decision.remaining_minute)
            response.headers["X-RateLimit-Remaining-Day"] = str(decision.remaining_day)
            return response

        return await call_next(request)
```

**What to look for in the code**

- Client identity is **hashed** before use. Raw IPs never reach a log.
- Ingestion blocking precedes rate limiting. There is no reason to spend rate-limit budget on a request that will never be allowed.
- `SecurityHeadersMiddleware` sits outside, so **the guard's own 403s and 429s carry headers too.** Blocked responses missing headers would themselves be an information leak.

### 4. Logs are the last leak path

#### Create `app/release/secrets.py` — module header

**Learning action — define the structure:** it uses `logging.Filter`.

```python
"""Defensive log redaction for explicitly configured server-side secrets."""

from __future__ import annotations

import logging
```

#### Complete `app/release/secrets.py` — log redaction

**Learning action — implement the redaction rules:** compare it with M4.2's `redact_sensitive_text`.

<!-- src: app/release/secrets.py::REDACTION,install_secret_redaction -->
```python
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
```

**What to look for in the code**

- Where M4.2 redacted at the **database** boundary, this redacts at the **log** boundary. Two leak paths mean two defenses.
- Installing it as a `logging.Filter` means application code never has to know. Any module that accidentally logs a key is caught.
- The redaction constant is named differently from M4.2's (`[REDACTED]` matches, the name `REDACTION` does not). The two modules do not import each other.

### What you should be able to explain now

- **Why does no money leave even with an API key present?**
  - **Answer:** The default mode is canned, and key presence is deliberately separate from feature activation. A provider call becomes possible only after runtime mode is explicitly selected and its budget is applied.
- **Why does rate limiting need a ceiling on client count?**
  - **Answer:** The limiter stores a window for each client in memory. Without a ceiling, an attacker can rotate identifiers and grow that dictionary without bound, so old entries are evicted after `max_clients` is reached.
- **Why does `trust_proxy_headers` default to `False`?**
  - **Answer:** A client can supply `X-Forwarded-For` itself unless a trusted proxy is known to overwrite it. Trusting it by default would let callers change their apparent identity and bypass per-client limits.
- **Why must the security-header middleware sit outside the guard?**
  - **Answer:** The outer middleware sees every response, including the guard's own 403 and 429 responses. If it sat inside, blocked requests could return without the security headers applied to normal responses.
- **Why redact at both the database and the log?**
  - **Answer:** Persisted traces and formatted log records are independent leak paths. Redacting one does not protect the other, so each boundary must remove configured secrets before data leaves it.

---

[Module overview](../03-build.md) · [Next: Release app assembly →](02-release-app.md)
