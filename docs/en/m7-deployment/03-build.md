# M7 Build — Deploy Without Overstating It

## Going public means losing control

Until M6 it ran on your machine. You knew who would call it and how often, and the API key lived only in your `.env`.

A public demo is different.

- **anyone calls it, at any time.** A crawler may hammer it dozens of times a second
- **credentials may be in the environment.** Put a key in a Hugging Face Space and paid calls go out under that key no matter who calls
- **all input is untrusted**

So M7's first principle is this. **Having credentials and being allowed to use them are different things.**

Even with a key in the environment, default behavior takes the free path. The paid path turns on only by **explicit selection**, and even then it carries token and cost ceilings.

## Do not overstate packaging as publication

The second principle concerns portfolio honesty.

Writing a Dockerfile and filling in metadata is not the same as a Space actually running. To claim "deployed to Hugging Face" in documentation, it has to be true.

M7's commands verify **that the configuration is correct**, not **that publication happened**. That distinction is stated in the documentation. No chapter changes an external account.

## Three steps

| Order | Step | Concept | Main files | State |
|---:|---|---|---|---|
| 1 | M7.1 | Make zero-cost behavior the default and bound every optional paid path | `app/release/`, `app/demo.py`, `tests/release/` | Complete |
| 2 | M7.2 | Package the same boundary as one Docker Space worker | `deploy/huggingface/`, `.dockerignore`, container/Compose | Complete |
| 3 | M7.3 | Prove the release from both populated and clean source states | `scripts/verify_clean_checkout.sh`, status/index documents | Complete |

M7.3 matters most. It checks whether the release reproduces **without help from local caches or secrets** — the only way to filter out "it works on my machine."


---

## Tutorial — built in four sittings

M7 produces 506 lines of Python and 226 of infrastructure. Each document targets **under 30 minutes** to read and implement.

| Document | Checkpoint | Files built | Approx. |
|---|---|---|---|
| [1. Hardening the public boundary](tutorial/01-hardening.md) | M7.1 | `release/config.py`, `limiter.py`, `middleware.py`, `secrets.py` | 30 min |
| [2. Release app assembly](tutorial/02-release-app.md) | M7.1 | `release/app.py`, `__init__.py`, `space.py` | 25 min |
| [3. Container](tutorial/03-container.md) | M7.2 | `.dockerignore`, `Dockerfile`, `docker-compose.yml`, HF assets | 25 min |
| [4. Clean-checkout verification](tutorial/04-clean-checkout.md) | M7.3 | `scripts/verify_clean_checkout.sh` | 20 min |

Follow them in order. Do not move on while a stretch's focused test is failing.

---

## Final quality gate

```bash
unset OPENAI_API_KEY DOCREVIEW_OPENAI_API_KEY RUN_LIVE_OPENAI_TEST
uv run ruff check --no-fix app tests scripts
uv run ruff format --check app/release app/demo.py tests/release
uv run python scripts/check_doc_code.py docs/en/m7-deployment/03-build.md docs/ko/m7-deployment/03-build.md deploy/huggingface/README.md
uv run pytest tests/test_doc_sync.py tests/test_doc_parity.py -q
scripts/verify_clean_checkout.sh
git diff --check
```

Expected result: every command exits with status 0, the isolated run completes its locked setup and canned container smoke, and no provider or hosting account is contacted.

Note the `unset` on the first line. The gate runs with **credentials explicitly cleared.** A verification that passes only when a key is present does not prove "it works without one."

---

## Starting conditions

Install the locked environment and verify the M5 service boundary first.

```bash
uv sync --group dev
uv run pytest tests/api -q
```

None of the commands in this chapter modify an external account. The container build needs Docker; without it, only that verification is skipped.

## Not all four stretches are equally hard

M7 has no new algorithm either. What it has is **judgment**: what to make the default, and what may honestly be called proven.

| Kind | Documents | Learning action |
|---|---|---|
| Decision rules | 1 | **Implement** the limits and guards yourself — spend the time here |
| Arrangement | 2, 3 | **Write the structure, then review the call order** |
| Verification procedure | 4 | **Implement** the reproduction procedure yourself |

Document 4 matters most. The first three produce something that works in your environment; document 4 **rebuilds it from nothing** and checks.

## Concepts you meet here first

**Canned mode as the default.** Anyone can send requests to a public demo. Calling an LLM per request puts cost out of control. So the default path serves prepared responses, and real model calls happen only when explicitly enabled. For the demo to be honest, the screen has to show **which path answered just now**.

**Rate limits and cost guards.** A rate limit caps requests per unit of time; a cost guard caps accumulated spend. They protect against different things — one person calling a hundred times a second and a hundred people calling a little all day are separate problems.

**Packaging versus publication.** Writing a Dockerfile and filling in metadata is **packaging**. Having it actually run and respond is **publication**. The verification in this chapter proves only the former. Claiming the latter in a portfolio requires actually standing it up and keeping the evidence.

## M7.1 — Canned mode, rate limiting, and cost guards

A public boundary is designed on the assumption that traffic cannot be controlled. The default has to be a path that bills nothing, and the paid path runs only within limits even after being explicitly enabled. Secrets must stay out of responses, and equally out of error messages and logs.

**Document:** [1. Hardening the public boundary](tutorial/01-hardening.md), [2. Assembling the release app](tutorial/02-release-app.md) · **Passing:** `uv run pytest tests/release/test_01_config.py tests/release/test_02_rate_limit.py -q`

## M7.2 — Hugging Face and container release assets

Carry the promises kept in Python all the way into the image. Locked dependencies, the same entrypoint, and the same defaults have to hold inside the container too. `.dockerignore` matters most here — let a local cache or an `.env` ride into the image and you have built an image that works only on your machine.

**Document:** [3. Container](tutorial/03-container.md) · **Passing:** `uv run pytest tests/release/test_05_assets.py -q`

## M7.3 — Clean archive verification and honest release gate

The final gate. Take a fresh, clean copy of the repository and stand it up with no cache and no secrets. What fails here is usually a dependency on an uncommitted file or an environment variable that only exists locally. Passing this verification is what allows the release to be called reproducible.

**Document:** [4. Clean-checkout verification](tutorial/04-clean-checkout.md) · **Passing:** `uv run pytest tests/release -q`

## What you should be able to explain now

- **Why must the default path of a public demo be free?**
  - **Answer:** Anyone can call a public endpoint, so charging for every default request makes spending depend on traffic the owner cannot control. A canned default keeps the public path deterministic and free until runtime is explicitly enabled.
- **How do the things a rate limit and a cost guard block differ?**
  - **Answer:** A rate limit caps request frequency over time, while a cost guard caps the tokens or accumulated spend of provider calls. Distributed low-rate traffic can stay within the first limit and still exhaust the second.
- **By which path does a secret leak through an error message rather than a response?**
  - **Answer:** A provider or configuration exception can contain a configured secret, and formatting that exception into a traceback or log exposes it even when normal responses omit the value. Error and log paths therefore need redaction too.
- **What rides into the image when `.dockerignore` is missing?**
  - **Answer:** The build context can include local virtual environments, caches, data, and `.env` files containing secrets. A later `COPY` can bake those local artifacts into an image layer and make the image both unsafe and machine-dependent.
- **Which sentences may and may not be written in the documentation once packaging is done?**
  - **Answer:** The documentation may say that release assets were packaged and their configuration was verified. It may not say the service was published or deployed to Hugging Face until a running deployment has actually been checked and evidenced.
- **What does a failure caught by clean-checkout verification concretely look like?**
  - **Answer:** A fresh archive may fail to import an uncommitted module, resolve dependencies differently from the lock file, or fail to start without a local secret, database, or cache. These are dependencies the populated developer machine had been hiding.

## What this module hands to the next one

M7 makes the system deployable. One chapter remains, and it is different in kind.

| What M7 produced | Receiver | What happens there |
|---|---|---|
| a deployable query path with fixed defaults | **M8** | the same path asked a question in another language |
| the M3 evaluation harness, still unmodified | **M8** | language-sliced runs that need no change to the scorer |
| the honest-reporting habit from the release gate | **M8** | a parity ratio with a floor instead of a claim |

The next chapter, M8, is **cross-lingual retrieval**. The corpus stays twenty English filings; the questions arrive in Korean. The central question is this — **does a Korean question find the right English passage, and how would you know?** The lexical index is built with one English text-search configuration, the vector arm has only ever been measured with token-hash vectors, and neither of those facts is visible from a response. M8 turns the unknown into a measured table and gates it.

## Machine-verified final reference

The chapters above are the executable build path. The generated section below is the machine-verified final reference against `reference_revision`; it is not a bundle to use before M7.1 and it is not evidence of an external deployment.

<!-- complete-files:start -->
## Reference baseline — the complete canonical files

Create or replace the canonical paths below directly. Do not create `_mine.py` or another learner-copy module. The earlier excerpts explain individual decisions; the blocks in this section are the finished files to compare against once a checkpoint is done. Preserve the shown type annotations and English comments; `pyproject.toml` is the authoritative Ruff policy.

### M7.1 — Complete checkpoint

#### Create or replace `app/release/__init__.py`

<!-- file: app/release/__init__.py -->
```python
"""Deployment-safe composition for the public portfolio demo."""

from app.release.app import create_release_app
from app.release.config import ReleaseSettings
from app.release.limiter import InProcessRateLimiter, RateLimitDecision

__all__ = [
    "InProcessRateLimiter",
    "RateLimitDecision",
    "ReleaseSettings",
    "create_release_app",
]
```

#### Create or replace `app/release/config.py`

<!-- file: app/release/config.py -->
```python
"""Strict environment configuration for one low-cost demo instance."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.llm import ProviderBudget, TokenPricing


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

#### Create or replace `app/release/limiter.py`

<!-- file: app/release/limiter.py -->
```python
"""Bounded in-process rate limiting for a single demo worker."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
import math
import time

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

#### Create or replace `app/release/middleware.py`

<!-- file: app/release/middleware.py -->
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

#### Create or replace `app/release/secrets.py`

<!-- file: app/release/secrets.py -->
```python
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
```

#### Create or replace `app/release/app.py`

<!-- file: app/release/app.py -->
```python
"""FastAPI and Gradio composition for a bounded public portfolio instance."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from app.api import ApiServices, RuntimeApiServices, create_api_app
from app.demo import CannedDemoService, RuntimeDemoService, build_demo
from app.llm import LLMProvider, OpenAILLMProvider
from app.release.config import ReleaseSettings
from app.release.limiter import InProcessRateLimiter
from app.release.middleware import ReleaseGuardMiddleware, SecurityHeadersMiddleware
from app.release.secrets import install_secret_redaction

ProviderFactory = Callable[..., LLMProvider]


class ReleaseHealth(BaseModel):
    """Non-secret liveness state for container and platform probes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"
    mode: Literal["canned", "runtime"]


class ReleaseInfo(BaseModel):
    """Public release controls without credentials or provider internals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["canned", "runtime"]
    openai_enabled: bool
    key_handling: Literal["server_environment_only"] = "server_environment_only"
    key_persisted: Literal[False] = False
    rate_limit_scope: Literal["single_process"] = "single_process"
    rate_limit_per_minute: int
    rate_limit_per_day: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: str


def build_runtime_services(
    settings: ReleaseSettings,
    *,
    provider_factory: ProviderFactory = OpenAILLMProvider,
) -> RuntimeApiServices:
    """Compose runtime services without activating a provider from key presence alone."""
    if settings.mode != "runtime":
        raise ValueError("runtime services require DOCREVIEW_MODE=runtime")
    if settings.openai_api_key is None:
        return RuntimeApiServices()

    api_key = settings.openai_api_key.get_secret_value()
    provider = provider_factory(
        model_name=settings.openai_model,
        api_key=api_key,
    )
    install_secret_redaction((api_key,))
    return RuntimeApiServices(
        llm_provider=provider,
        provider_budget=settings.provider_budget(),
        secret_values=(api_key,),
    )


def _release_info(settings: ReleaseSettings) -> ReleaseInfo:
    return ReleaseInfo(
        mode=settings.mode,
        openai_enabled=settings.openai_enabled,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        rate_limit_per_day=settings.rate_limit_per_day,
        max_input_tokens=settings.openai_max_input_tokens,
        max_output_tokens=settings.openai_max_output_tokens,
        max_cost_usd=format(settings.openai_max_cost_usd, "f"),
    )


def create_release_app(
    settings: ReleaseSettings | None = None,
    *,
    services: ApiServices | None = None,
) -> FastAPI:
    """Create one canned-default release app without external calls at import time."""
    import gradio as gr

    active_settings = settings or ReleaseSettings()
    active_services = services
    if active_settings.mode == "runtime" and active_services is None:
        active_services = build_runtime_services(active_settings)

    application = create_api_app(active_services)
    limiter = InProcessRateLimiter(
        per_minute=active_settings.rate_limit_per_minute,
        per_day=active_settings.rate_limit_per_day,
        max_clients=active_settings.rate_limit_max_clients,
    )
    application.add_middleware(
        ReleaseGuardMiddleware,
        limiter=limiter,
        trust_proxy_headers=active_settings.trust_proxy_headers,
        allow_ingest=active_settings.allow_ingest,
    )
    application.add_middleware(SecurityHeadersMiddleware)

    @application.get("/health", response_model=ReleaseHealth, tags=["release"])
    async def health() -> ReleaseHealth:
        return ReleaseHealth(mode=active_settings.mode)

    @application.get("/release", response_model=ReleaseInfo, tags=["release"])
    async def release_info() -> ReleaseInfo:
        return _release_info(active_settings)

    if active_settings.mode == "runtime":
        assert active_services is not None
        demo_service = RuntimeDemoService(active_services)
        notice = (
            "Deployment mode: local runtime review with an operator-supplied server secret."
            if active_settings.openai_enabled
            else "Deployment mode: local runtime retrieval; review is fail-closed."
        )
    else:
        demo_service = CannedDemoService()
        notice = "Deployment mode: canned fixture; provider requests and cost are zero."

    blocks = build_demo(demo_service, release_notice=notice)
    return gr.mount_gradio_app(
        application,
        blocks,
        path="/",
        allowed_paths=[],
        blocked_paths=[".env", ".git"],
        show_error=False,
        enable_monitoring=False,
        app_kwargs={"docs_url": "/docs", "redoc_url": None},
    )
```

#### Create or replace `app/release/space.py`

<!-- file: app/release/space.py -->
```python
"""Hugging Face Docker Space entrypoint; canned mode is the default."""

from app.release import create_release_app

app = create_release_app()
```

Run the checkpoint:

```bash
uv run pytest tests/release/test_01_config.py tests/release/test_02_rate_limit.py tests/release/test_03_guards.py tests/release/test_04_app.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M7.2 — Complete checkpoint

#### Create or replace `.dockerignore`

<!-- file: .dockerignore -->
```gitignore
.git
.venv
.env
.env.*
__pycache__
*.pyc
.pytest_cache
.ruff_cache
.mypy_cache
htmlcov
old
42_curriculum
data/corpus/**/*.html
data/eval_runs
```

#### Create or replace `Dockerfile`

<!-- file: Dockerfile -->
```dockerfile
FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser data ./data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"

CMD ["uv", "run", "--no-sync", "python", "-m", "app.cli", "serve", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

#### Create or replace `docker-compose.yml`

<!-- file: docker-compose.yml -->
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: filing
      POSTGRES_USER: filing
      POSTGRES_PASSWORD: filing
    ports: ["${DB_PORT:-5432}:5432"]
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U filing -d filing"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      CORPUS_DIR: /app/data/corpus
      DATABASE_URL: postgresql+asyncpg://filing:filing@db:5432/filing
      EMBEDDING_PROVIDER: deterministic
    depends_on:
      db:
        condition: service_healthy
    ports: ["${APP_PORT:-8000}:8000"]
    init: true
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()",
        ]
      interval: 10s
      timeout: 3s
      start_period: 10s
      retries: 5

volumes:
  pg_data:
```

#### Create or replace `deploy/huggingface/Dockerfile`

<!-- file: deploy/huggingface/Dockerfile -->
```dockerfile
FROM ghcr.io/astral-sh/uv:0.11.19 AS uv

FROM python:3.14-slim

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DOCREVIEW_MODE=canned \
    DOCREVIEW_PORT=7860

RUN useradd --create-home --uid 1000 user \
    && mkdir --parents /home/user/app \
    && chown user:user /home/user/app
WORKDIR /home/user/app

COPY --from=uv /uv /uvx /bin/
COPY --chown=user:user pyproject.toml uv.lock README.md ./

USER user
RUN uv sync --locked --no-dev --extra demo --no-install-project

COPY --chown=user:user app ./app

EXPOSE 7860

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=2).read()"

CMD ["uv", "run", "--no-sync", "uvicorn", "app.release.space:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--log-level", "warning"]
```

#### Create or replace `deploy/huggingface/space.env.example`

<!-- file: deploy/huggingface/space.env.example -->
```dotenv
# Public Spaces should remain canned unless runtime dependencies are explicitly provisioned.
DOCREVIEW_MODE=canned
DOCREVIEW_RATE_LIMIT_PER_MINUTE=10
DOCREVIEW_RATE_LIMIT_PER_DAY=100
DOCREVIEW_RATE_LIMIT_MAX_CLIENTS=1024
DOCREVIEW_TRUST_PROXY_HEADERS=false
DOCREVIEW_ALLOW_INGEST=false

# Runtime review is opt-in and still bounded by all three caps.
DOCREVIEW_OPENAI_MODEL=gpt-4.1-mini
DOCREVIEW_OPENAI_MAX_INPUT_TOKENS=12000
DOCREVIEW_OPENAI_MAX_OUTPUT_TOKENS=600
DOCREVIEW_OPENAI_MAX_COST_USD=0.01
DOCREVIEW_OPENAI_INPUT_PER_MILLION_USD=0.40
DOCREVIEW_OPENAI_OUTPUT_PER_MILLION_USD=1.60

# Configure OPENAI_API_KEY only as a server-side Space secret, never as a public variable.
```

Run the checkpoint:

```bash
uv run pytest tests/release/test_05_assets.py -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

### M7.3 — Complete checkpoint

#### Create or replace `scripts/verify_clean_checkout.sh`

<!-- file: scripts/verify_clean_checkout.sh -->
```bash
#!/usr/bin/env bash
set -euo pipefail

M7_SOURCE_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
M7_TEMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/docreview-m7-clean.XXXXXX")
M7_ARCHIVE_ROOT="$M7_TEMP_ROOT/repository"
M7_FILE_LIST="$M7_TEMP_ROOT/files.list"
M7_PROJECT="docreview_m7_${$}"
M7_SPACE_IMAGE="docreview-m7-space:${$}"
M7_SPACE_CONTAINER="docreview-m7-space-${$}"

cleanup() {
    docker rm -f "$M7_SPACE_CONTAINER" >/dev/null 2>&1 || true
    if [[ -d "$M7_ARCHIVE_ROOT" ]]; then
        docker compose --project-directory "$M7_ARCHIVE_ROOT" \
            -p "$M7_PROJECT" down --volumes --remove-orphans --rmi local \
            >/dev/null 2>&1 || true
    fi
    docker image rm "$M7_SPACE_IMAGE" >/dev/null 2>&1 || true
    case "$M7_TEMP_ROOT" in
        "${TMPDIR:-/tmp}"/docreview-m7-clean.*) rm -rf -- "$M7_TEMP_ROOT" ;;
        *) printf 'Refusing to remove unexpected temporary path: %s\n' "$M7_TEMP_ROOT" >&2 ;;
    esac
}
trap cleanup EXIT INT TERM

mkdir -p "$M7_ARCHIVE_ROOT"
while IFS= read -r -d '' path; do
    if [[ -f "$M7_SOURCE_ROOT/$path" || -L "$M7_SOURCE_ROOT/$path" ]]; then
        printf '%s\0' "$path"
    fi
done < <(
    git -C "$M7_SOURCE_ROOT" ls-files --cached --others --exclude-standard -z
) > "$M7_FILE_LIST"

tar --null --create --file=- --directory="$M7_SOURCE_ROOT" \
    --files-from="$M7_FILE_LIST" | tar --extract --file=- --directory="$M7_ARCHIVE_ROOT"

cd "$M7_ARCHIVE_ROOT"
unset OPENAI_API_KEY DOCREVIEW_OPENAI_API_KEY
export DOCREVIEW_MODE=canned
export UV_PROJECT_ENVIRONMENT="$M7_ARCHIVE_ROOT/.venv"

printf 'Clean archive: fresh locked dependency sync\n'
uv sync --locked --extra demo

printf 'Clean archive: focused release, demo, and API tests\n'
uv run pytest -o addopts="" tests/release tests/demo tests/api -q

printf 'Clean archive: lint, owned format, and documentation sync\n'
uv run ruff check --no-fix app tests scripts
uv run ruff format --check app/release app/demo.py tests/release
uv run python scripts/check_doc_code.py README.md docs deploy/huggingface/README.md
uv run python scripts/check_doc_parity.py inventory
uv run python scripts/check_doc_parity.py parity
uv run python scripts/check_doc_parity.py language
uv run pytest -o addopts="" tests/test_doc_sync.py tests/test_doc_parity.py -q

printf 'Clean archive: Compose configuration and application image build\n'
docker compose -p "$M7_PROJECT" config --quiet
docker compose -p "$M7_PROJECT" build app

printf 'Clean archive: Hugging Face image build and canned local smoke\n'
docker build --file deploy/huggingface/Dockerfile --tag "$M7_SPACE_IMAGE" .
docker run --detach --name "$M7_SPACE_CONTAINER" \
    --publish 127.0.0.1::7860 "$M7_SPACE_IMAGE" >/dev/null

M7_PORT=$(docker port "$M7_SPACE_CONTAINER" 7860/tcp | tail -n 1 | sed 's/.*://')
for attempt in $(seq 1 45); do
    if M7_PORT="$M7_PORT" python - <<'PY'
import json
import os
import urllib.error
import urllib.request

port = os.environ["M7_PORT"]
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
        health = json.load(response)
except (OSError, TimeoutError, urllib.error.URLError):
    raise SystemExit(1) from None
if health != {"status": "ok", "mode": "canned"}:
    raise SystemExit(f"unexpected health response: {health}")
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
        body = response.read().decode("utf-8")
except (OSError, TimeoutError, urllib.error.URLError):
    raise SystemExit(1) from None
if "Document Review Evidence Demo" not in body:
    raise SystemExit("Gradio landing page marker is missing")
PY
    then
        printf 'Clean archive: canned health and Gradio smoke passed on port %s\n' "$M7_PORT"
        exit 0
    fi
    if [[ "$attempt" == "45" ]]; then
        docker logs "$M7_SPACE_CONTAINER" >&2 || true
        printf 'Container smoke timed out\n' >&2
        exit 1
    fi
    sleep 1
done
```

Run the checkpoint:

```bash
uv run pytest tests/release -q
```

**Expected:** every selected offline test passes. A declared integration test may skip only when its external service is unavailable.

**Stop:** do not continue if a test fails or skips because a required symbol is missing.

**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix the first failing contract before continuing.

<!-- complete-files:end -->
