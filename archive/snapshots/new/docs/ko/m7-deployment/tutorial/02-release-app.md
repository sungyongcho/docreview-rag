# M7.1 튜토리얼 2 — 릴리스 앱을 조립한다

가드 네 개를 만들었으므로, 이제 그것들을 하나의 앱으로 묶고 Space 진입점을 노출한다.

**선행 조건:** 튜토리얼 1에서 `release/config.py`와 나머지 강화 모듈을 작성한 상태여야 한다.

### 노출해도 되는 상태와 안 되는 상태

`/release-info`는 릴리스 상태를 공개한다. 어떤 값을 포함할지가 이 절의 결정이다.

실행 모드, 속도 제한 값, 수집 허용 여부는 **공개한다.** **이 값들이 공개되어야 데모를 사용하는 사람이 응답이 고정인 이유와 429가 발생하는 조건을 확인할 수 있다.**

API 키는 존재 여부를 **불리언으로만** 노출한다. 키 값도, 앞부분 일부도 포함하지 않는다. 필드 구성도 키의 유무가 아니라 런타임 모드의 활성화 여부를 나타내도록 정의한다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `ReleaseHealth`·`ReleaseInfo` | **모델 선언 작성** | 공개해도 되는 상태의 경계 |
| `build_runtime_services` | 조건부 조립을 **직접 구현** | 런타임이 켜지는 정확한 조건 |
| `create_release_app` | 미들웨어 순서를 **직접 구현** | 바깥에서 안으로 감싸는 순서 |
| `__init__.py`·`space.py` | **구조 작성** | 단일 프로세스 진입점 |

### 1. 공개해도 되는 상태의 경계

#### `app/release/app.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** M5의 `create_api_app`과 M6의 데모를 함께 import한다는 점을 확인한다.

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

#### `app/release/app.py` 확장 — 상태 모델

**학습 행동 — 모델 선언 작성:** `ReleaseInfo`에 어떤 필드가 **없는지** 확인하며 작성한다.

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

**코드에서 꼭 볼 것**

- API 키 값이 없고 키의 일부도 없다. 포함되는 것은 실행 모드와 한도뿐이다.
- 속도 제한 값을 공개한다. 클라이언트가 어느 시점에 429를 받게 되는지 미리 계산할 수 있다.

### 2. 런타임이 켜지는 정확한 조건

#### `app/release/app.py` 확장 — 런타임 서비스 조립

**학습 행동 — 조건부 조립 구현:** 런타임 모드가 켜지려면 몇 가지 조건이 동시에 참이어야 하는지 세어 본다.

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

**코드에서 꼭 볼 것**

- **`mode == "runtime"`이면서 키가 있어야 런타임 서비스가 만들어진다.** 두 조건 중 하나만 충족되면 만들어지지 않는다.
- 설정 값에서 M4.1의 `ProviderBudget`을 조립한다. 공급자와 예산을 한 함수에서 함께 만들므로 M5.2의 XOR 제약이 이 경로에서 항상 충족된다.
- 조건이 맞지 않으면 `None`을 반환한다. 예외를 던지지 않으며, canned 모드로 동작하는 것이 정의된 기본 상태다.

### 3. 바깥에서 안으로 감싸는 순서

#### `app/release/app.py` 완성 — 릴리스 앱 생성

**학습 행동 — 미들웨어 순서 구현:** 두 미들웨어의 등록 순서를 직접 정해 보고 결과를 확인한다.

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

**코드에서 꼭 볼 것**

- `SecurityHeadersMiddleware`를 **나중에** 추가한다. **Starlette는 나중에 추가한 미들웨어를 바깥에 배치하므로, 이 순서라야 보안 헤더가 가드의 403·429 응답까지 감싼다.**
- `create_api_app`을 재사용한다. M5의 라우트가 그대로 공개되고 릴리스 전용 사본을 따로 두지 않는다.
- 수집 라우트를 제거하지 않고 **가드로 차단한다.** 라우트 목록이 M5와 같아 OpenAPI 문서가 일치하고, 차단 해제도 설정 값 하나로 처리된다.

### 4. 단일 프로세스 진입점

#### `app/release/__init__.py` 생성 — 패키지 표면

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

#### `app/release/space.py` 생성 — Space 진입점

**학습 행동 — 구조 작성:** 세 줄짜리 파일이다. 기본 모드가 canned라는 사실이 이 파일에서 확정된다.

```python
"""Hugging Face Docker Space entrypoint; canned mode is the default."""

from app.release import create_release_app

app = create_release_app()
```

**코드에서 꼭 볼 것**

- `create_release_app()`을 인자 없이 호출한다. 배포 환경이 아무 설정도 제공하지 않으면 **canned 모드로 기동한다.**
- 구조는 M5의 `app/main.py`와 같다. 모듈 수준에 `app`이 있지만 생성자가 연결을 열지 않는다.

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/release/test_01_config.py tests/release/test_02_rate_limit.py \
  tests/release/test_03_guards.py tests/release/test_04_app.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 키만 있고 모드는 canned | 키 존재가 유료 호출을 켜지 않는다. |
| 응답에 노출된 키 조각 | 비밀이 릴리스 상태에 나가지 않는다. |
| 헤더 없는 429 응답 | 차단 응답도 보안 헤더를 갖는다. |
| 신뢰 없이 읽은 `X-Forwarded-For` | 속도 제한을 헤더로 우회할 수 없다. |
| 공개 경로의 수집 요청 | 공개 엔드포인트가 코퍼스를 바꾸지 않는다. |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **속도 제한 값을 공개하는 것이 왜 해가 아니라 득인가?**
  - **답:** 한도는 비밀이 아니라 사용 정책이다. 값을 공개하면 자격증명을 노출하지 않으면서도 클라이언트가 429 발생 시점을 예측하고 공개 데모의 동작을 이해할 수 있다.
- **런타임이 켜지려면 무엇이 동시에 참이어야 하는가?**
  - **답:** 운영자가 런타임 모드를 명시적으로 선택하고 API 키도 제공해야 공급자 기반 검토가 활성화된다. 키만 존재해서는 유료 경로가 켜지지 않는다.
- **보안 헤더 미들웨어를 나중에 등록하는 이유는 무엇인가?**
  - **답:** Starlette는 나중에 추가한 미들웨어를 바깥에 배치한다. 이 순서여야 릴리스 가드가 일찍 반환한 403·429에도 보안 헤더를 붙일 수 있다.
- **수집 라우트를 지우지 않고 가드로 막는 이유는 무엇인가?**
  - **답:** M5 라우트를 유지하면 모드가 달라도 API와 OpenAPI 형태가 하나로 유지된다. 별도 릴리스 라우트를 복원하지 않고 설정 하나만 바꿔 공개 읽기 전용 정책을 해제할 수 있다.
- **`space.py`가 세 줄이어도 되는 이유는 무엇인가?**
  - **답:** 모든 조립과 기본값이 이미 `create_release_app()`에 들어 있다. 진입점은 그 팩터리를 가져와 모듈 수준의 `app`을 노출하기만 하므로 연결을 열거나 정책을 복제할 필요가 없다.

---

[← 이전: 공개 경계 강화](01-hardening.md) · [모듈 개요](../03-build.md) · [다음: 컨테이너 →](03-container.md)
