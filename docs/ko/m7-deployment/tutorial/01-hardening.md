# M7.1 튜토리얼 1 — 통제할 수 없는 트래픽을 전제로 설계한다

공개 링크를 배포하면 요청량과 요청자를 통제할 수 없다. 그래서 공개용 조립은 기본값에서 다음과 같이 동작한다.

- **결정론적 고정 근거**를 돌려준다 (공급자 호출 없음)
- **수집을 막는다** — 공개 엔드포인트가 코퍼스를 건드릴 이유가 없다
- POST성 작업에 **속도 제한**을 건다
- **비밀이 아닌 릴리스 상태만** 노출한다

런타임 모드는 명시적으로 선택해야 켜지고, 켜도 토큰과 추정 비용 상한이 걸린다.

**선행 조건:** M5의 서비스가 동작하고 `uv run pytest tests/api -q`가 통과해야 한다.

### 방어가 여섯 겹인 이유

각 계층이 막는 실패가 서로 다르므로, 하나만으로는 나머지 실패를 막지 못한다.

1. `ReleaseSettings`가 모드·한도·공급자 예산을 검증한다. 2. `InProcessRateLimiter`가 단일 프로세스용 롤링 윈도를 센다. 3. `ReleaseGuardMiddleware`가 클라이언트 식별을 해싱하고 수집을 막고 403·429를 낸다. 4. `SecurityHeadersMiddleware`가 가드 실패까지 포함해 모든 응답을 감싼다. 5. `create_release_app()`이 canned 또는 명시적으로 켠 runtime 서비스를 조립한다. 6. `app/release/space.py`가 단일 프로세스 Space 진입점을 노출한다.

이 문서는 1~4를, 다음 문서가 5~6을 만든다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `ReleaseSettings` | **설정 스키마 정의** | 공개 비용 경계가 값으로 적히는 법 |
| `InProcessRateLimiter` | 윈도 계산을 **직접 구현** | 메모리가 무한히 늘지 않게 하는 법 |
| `client_host` | 신뢰 판단을 **직접 구현** | 프록시 헤더를 기본으로 믿지 않는 이유 |
| `ReleaseGuardMiddleware` | 가드 순서를 **직접 구현** | 차단이 응답 헤더보다 먼저인지 나중인지 |
| `SecretRedactionFilter` | 편집 규칙을 **직접 구현** | 로그가 마지막 유출 경로인 이유 |

### 1. 공개 비용 경계를 값으로 적는다

#### `app/release/config.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** `BaseSettings`를 사용한다. 설정 값을 환경 변수에서 읽는다는 뜻이다.

```python
"""Strict environment configuration for one low-cost demo instance."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.llm import ProviderBudget, TokenPricing

```

#### `app/release/config.py` 완성 — 릴리스 설정

**학습 행동 — 설정 스키마 정의:** 필드를 개별로 보지 말고 책임별로 묶어 정리하며 작성한다.

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

| 설정 그룹 | 필드와 기본값 | 역할 |
|---|---|---|
| 실행 모드 | `mode="canned"` | 공급자 호출 0인 경로를 기본으로 만들고 런타임은 명시 선택을 요구한다. |
| 리스너 | `host="0.0.0.0"`, `port=7860` | 단일 공개 프로세스 주소를 정의한다. |
| 속도 제한 | `rate_limit_per_minute=10`, `rate_limit_per_day=100`, `rate_limit_max_clients=1024` | 요청량과 메모리 내 클라이언트 상태를 제한한다. |
| 요청 신뢰 | `trust_proxy_headers=False`, `allow_ingest=False` | 신뢰할 수 없는 전달 식별과 공개 코퍼스 변경을 기본 거부한다. |
| 공급자 식별 | `openai_api_key=None`, `openai_model="gpt-4.1-mini"` | 비밀 존재 여부와 명시적 런타임 활성화를 분리한다. |
| 공급자 예산 | `openai_max_input_tokens`, `openai_max_output_tokens`, `openai_max_cost_usd` | 선택적 실시간 완성 하나를 실행 전에 제한한다. |
| 가격 | `openai_input_per_million_usd`, `openai_output_per_million_usd` | 비용 추정을 명시적이고 검토 가능하게 만든다. |

**코드에서 꼭 볼 것**

- `mode`의 기본값은 `"canned"`다. **환경 변수를 하나도 설정하지 않은 배포는 공급자를 호출하지 않으므로 비용이 발생하지 않는다.**
- `openai_api_key`가 설정돼 있어도 `mode`가 `canned`이면 호출하지 않는다. **비밀 값의 존재와 기능 활성화를 분리한 것**으로, M5.2의 XOR 제약과 같은 판단이다.
- `rate_limit_max_clients`가 별도 필드다. 속도 제한이 클라이언트별 상태를 메모리에 두므로 그 메모리 사용량에도 상한이 필요하다.

### 2. 메모리가 무한히 늘지 않게 한다

#### `app/release/limiter.py` 생성 — 모듈 헤더와 창 레코드

**학습 행동 — 구조 작성:** 초 단위 상수 두 개와 판정 결과 레코드 하나를 작성한다.

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

**코드에서 꼭 볼 것**

- `RateLimitDecision`은 불리언 하나가 아니라 재시도 정보까지 함께 반환한다. **거부 사실만 전달하면 호출자는 재시도 시점을 알 수 없어 즉시 다시 요청하고, 그 요청도 같은 창에서 거부된다.**
- `frozen=True`는 판정 결과에 붙고 `_ClientWindow`는 가변이다. 판정은 만들어진 뒤 바뀌지 않아야 하고 창은 요청마다 갱신되어야 하므로, 두 성격을 선언으로 구분한다.
- `deque`를 쓰는 이유는 앞쪽에서 만료된 타임스탬프를 제거하는 연산이 상수 시간이기 때문이다. 리스트를 쓰면 `pop(0)`이 매번 나머지 원소를 앞으로 옮긴다.
- `last_seen`을 따로 두는 이유는 오랫동안 요청이 없는 클라이언트의 창을 회수하기 위해서다. **이 필드가 없으면 한 번이라도 요청한 클라이언트의 상태가 프로세스가 살아 있는 동안 계속 남는다.**

#### `app/release/limiter.py` 완성 — 인프로세스 속도 제한

**학습 행동 — 윈도 계산 구현:** 분 단위 창과 일 단위 창을 각각 어떻게 이동시키는지 직접 구현한다.

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

**코드에서 꼭 볼 것**

- 상태를 **프로세스 안에** 둔다. Redis 같은 외부 저장소를 쓰지 않는다. 단일 프로세스 배포라는 전제를 클래스 이름에 명시했으므로, 프로세스를 늘릴 때 이 클래스를 교체해야 한다는 사실이 이름에서 드러난다.
- 클라이언트 수에 상한이 있고, 상한을 넘으면 오래된 항목부터 제거한다. **상한이 없으면 요청자가 식별자를 바꿔 가며 요청하는 것만으로 이 딕셔너리가 계속 커진다.**
- `RateLimitDecision`이 `retry_after`를 담는다. 이 값이 429 응답 헤더에 그대로 실린다.

### 3. 프록시 헤더를 기본으로 믿지 않는다

#### `app/release/middleware.py` 생성 — 모듈 헤더와 보안 헤더

**학습 행동 — 신뢰 판단 구현:** `client_host`를 직접 구현하고, `trust_proxy_headers`가 `False`일 때 어떤 값을 무시하는지 확인한다.

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

**코드에서 꼭 볼 것**

- `X-Forwarded-For`를 **기본으로 무시한다.** **이 헤더는 클라이언트가 임의의 값으로 보낼 수 있으므로, 신뢰할 수 있는 프록시 뒤에 있다고 명시하기 전에 이 값을 식별자로 쓰면 요청자가 값을 바꾸는 것만으로 속도 제한을 우회한다.**
- `SECURITY_HEADERS`는 상수 딕셔너리다. 미들웨어가 모든 응답에 이 헤더를 붙인다.

#### `app/release/middleware.py` 완성 — 릴리스 가드

**학습 행동 — 가드 순서 구현:** 수집 차단과 속도 제한 중 어느 것을 먼저 적용할지 직접 판단해 본다.

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

**코드에서 꼭 볼 것**

- 클라이언트 식별자를 **해싱해서** 사용한다. IP 주소가 로그에 원본 그대로 남지 않는다.
- 수집 차단을 속도 제한보다 먼저 적용한다. 어떤 경우에도 허용하지 않을 요청이 속도 제한 창의 자리를 차지하지 않는다.
- `SecurityHeadersMiddleware`가 바깥에 있으므로 **가드가 반환한 403과 429 응답에도 보안 헤더가 붙는다.** **차단 응답에만 헤더가 빠지면 응답 헤더의 유무로 차단 여부를 구분할 수 있게 된다.**

### 4. 로그가 마지막 유출 경로다

#### `app/release/secrets.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** `logging.Filter`를 사용한다. 편집이 로깅 계층에서 일어난다는 뜻이다.

```python
"""Defensive log redaction for explicitly configured server-side secrets."""

from __future__ import annotations

import logging
```

#### `app/release/secrets.py` 완성 — 로그 편집

**학습 행동 — 편집 규칙 구현:** M4.2의 `redact_sensitive_text`와 비교하며 작성한다.

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

**코드에서 꼭 볼 것**

- M4.2는 **데이터베이스** 경계에서 편집했고, 이 필터는 **로그** 경계에서 편집한다. **자격증명이 나갈 수 있는 경로가 둘이므로 한쪽만 막으면 다른 경로로 그대로 나간다.**
- `logging.Filter`로 설치하므로 애플리케이션 코드가 이 필터의 존재를 알 필요가 없다. 어느 모듈이 키를 로그에 남겨도 이 지점에서 편집된다.
- 치환 문자열 `[REDACTED]`는 M4.2와 같지만 상수 이름은 `REDACTION`으로 다르다. 두 모듈이 서로를 import하지 않고 각자 상수를 정의한다는 뜻이다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 코드와 연결해 설명해 본다.

- **API 키가 있는데도 돈이 나가지 않는 이유는 무엇인가?**
  - **답:** 기본 모드는 미리 준비된 모드이며, 키의 존재와 기능 활성화를 의도적으로 분리했다. 런타임 모드를 명시적으로 선택하고 예산을 적용한 뒤에만 공급자 호출이 가능해진다.
- **속도 제한에 클라이언트 수 상한이 필요한 이유는 무엇인가?**
  - **답:** 제한기는 클라이언트마다 요청 윈도를 메모리에 저장한다. 상한이 없으면 공격자가 식별자를 바꾸며 딕셔너리를 무한히 키울 수 있으므로 `max_clients`에 도달하면 오래된 항목을 제거한다.
- **`trust_proxy_headers`가 기본 `False`인 이유는 무엇인가?**
  - **답:** 신뢰할 수 있는 프록시가 값을 덮어쓴다고 보장되지 않으면 클라이언트가 `X-Forwarded-For`를 직접 보낼 수 있다. 기본으로 신뢰하면 호출자가 겉보기 식별자를 바꿔 클라이언트별 제한을 우회한다.
- **보안 헤더 미들웨어가 가드보다 바깥에 있어야 하는 이유는 무엇인가?**
  - **답:** 바깥 미들웨어는 가드가 직접 만든 403·429를 포함한 모든 응답을 통과시킨다. 안쪽에 있으면 차단된 요청만 정상 응답과 달리 보안 헤더 없이 반환될 수 있다.
- **데이터베이스와 로그 양쪽에서 편집해야 하는 이유는 무엇인가?**
  - **답:** 저장되는 추적 정보와 형식화된 로그 레코드는 서로 독립된 유출 경로다. 한쪽을 편집해도 다른 쪽은 보호되지 않으므로 각 경계에서 비밀 값을 제거해야 한다.

---

[모듈 개요](../03-build.md) · [다음: 릴리스 앱 조립 →](02-release-app.md)
