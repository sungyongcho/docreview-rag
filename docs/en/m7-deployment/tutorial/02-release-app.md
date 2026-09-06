# M7.1 Tutorial 2 — Assembling the release app

The four guards are ready. Now they get bound into one app and a Space entrypoint gets exposed.

**Prerequisite:** `release/config.py` and the rest of the hardening modules from tutorial 1 are written.

### State that may be exposed and state that may not

`/release-info` exposes release state. But what exactly?

Mode, rate-limit values, and whether ingestion is allowed **may be public.** Publishing them is in fact better — whoever views the demo understands why responses are fixed and why a 429 appeared.

Whether an API key exists leaves **only as a boolean.** Not the key, not its first four characters. And even that boolean is shaped to read as "runtime mode is on" rather than "a key exists."

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| `ReleaseHealth` and `ReleaseInfo` | **Write the model declarations** | The boundary of state that may be exposed |
| `build_runtime_services` | **Implement** the conditional assembly yourself | The exact condition that turns runtime on |
| `create_release_app` | **Implement** the middleware order yourself | The order of wrapping from outside in |
| `__init__.py` and `space.py` | **Define the structure** | The single-process entrypoint |

### 1. The boundary of state that may be exposed

#### Create `app/release/app.py` — module header

**Learning action — define the structure:** M5's `create_api_app` and M6's demo are imported together.

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

```

#### Extend `app/release/app.py` — state models

**Learning action — write the model declarations:** note what is **absent** from `ReleaseInfo`.

<!-- src: app/release/app.py::ReleaseHealth,ReleaseInfo -->
```python
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
```

**What to look for in the code**

- There is no API key. Not even part of one. What is there is mode and limits.
- Rate-limit values are published. A client can predict when it will receive a 429.

### 2. The exact condition that turns runtime on

#### Extend `app/release/app.py` — runtime service assembly

**Learning action — implement the conditional assembly:** count how many things must be simultaneously true for runtime to turn on.

<!-- src: app/release/app.py::build_runtime_services,_release_info -->
```python
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
```

**What to look for in the code**

- `mode == "runtime"` **and** a key must be present. Either alone is not enough.
- The budget is assembled from settings into M4.1's `ProviderBudget`. M5.2's XOR constraint is satisfied automatically here — provider and budget are built together in one function.
- When the conditions do not hold it returns `None`, not an exception. Running canned is the normal outcome.

### 3. The order of wrapping from outside in

#### Complete `app/release/app.py` — creating the release app

**Learning action — implement the middleware order:** decide for yourself which order the two middlewares register in.

<!-- src: app/release/app.py::create_release_app -->
```python
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

**What to look for in the code**

- `SecurityHeadersMiddleware` is added **later**. In Starlette the later addition sits outside, so security headers wrap even the guard's 403s and 429s.
- `create_api_app` is reused. M5's routes are published unchanged — there is no release-specific copy.
- Ingestion routes are not deleted; **the guard blocks them.** The route list matches M5, so OpenAPI stays consistent and the block lifts with one settings change.

### 4. The single-process entrypoint

#### Create `app/release/__init__.py` — package surface

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

#### Create `app/release/space.py` — the Space entrypoint

**Learning action — define the structure:** three lines. The canned default is settled here.

```python
"""Hugging Face Docker Space entrypoint; canned mode is the default."""

from app.release import create_release_app

app = create_release_app()
```

**What to look for in the code**

- `create_release_app()` is called with no arguments. If a deployment configures nothing, it **comes up canned.**
- The same shape as M5's `app/main.py`. There is a module-level `app`, and the constructor opens no connection.

### Focused tests and the contracts they protect

```bash
uv run pytest tests/release/test_01_config.py tests/release/test_02_rate_limit.py \
  tests/release/test_03_guards.py tests/release/test_04_app.py -q
```

| Value the test breaks | Contract being protected |
|---|---|
| A key present while mode stays canned | Key presence never turns on a paid call. |
| A key fragment exposed in a response | No secret leaves in release state. |
| A 429 response without headers | Blocked responses carry security headers too. |
| `X-Forwarded-For` read without trust | Rate limiting cannot be bypassed by a header. |
| An ingestion request on the public path | A public endpoint never mutates the corpus. |

### What you should be able to explain now

- **Why is publishing the rate-limit values a benefit rather than a harm?**
  - **Answer:** The limits are policy, not secrets. Publishing them lets clients predict when a 429 will occur and understand the public demo's behavior without exposing any credential.
- **What must be simultaneously true for runtime to turn on?**
  - **Answer:** The operator must explicitly set runtime mode and provide an API key before provider-backed review is enabled. A key alone never turns a paid path on.
- **Why is the security-header middleware registered later?**
  - **Answer:** Starlette places the later-added middleware on the outside. That order lets it attach headers even to 403 and 429 responses returned early by the release guard.
- **Why is ingestion blocked by a guard rather than by deleting the route?**
  - **Answer:** Keeping the M5 route preserves one API and one OpenAPI shape across modes. The public read-only policy can then be lifted with one setting instead of restoring a separate release-specific route set.
- **Why is three lines enough for `space.py`?**
  - **Answer:** All composition and defaults already live in `create_release_app()`. The entrypoint only imports that factory and exposes the module-level `app`, opening no connection and duplicating no policy.

---

[← Previous: Hardening the public boundary](01-hardening.md) · [Module overview](../03-build.md) · [Next: Container →](03-container.md)
