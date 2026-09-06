# M7 구현 — 배포하되 과장하지 않기

## 공개하는 순간 통제권을 잃는다

M6까지는 내 컴퓨터에서 돌았다. 누가 몇 번 부를지 내가 알았고, API 키는 내 `.env`에만 있었다.

공개 데모는 다르다.

- **아무나 아무 때나 호출한다.** 크롤러가 초당 수십 번 두드릴 수도 있다
- **자격 증명이 환경에 있을 수 있다.** Hugging Face Space에 키를 넣어뒀다면 누가 부르든 그 키로 유료 호출이 나간다
- **입력이 전부 신뢰할 수 없다**

그래서 M7의 첫 원칙이 이것이다. **자격 증명이 있다는 것과 그걸 써도 된다는 것은 다르다.**

키가 환경에 있어도 기본 동작은 무료 경로다. 유료 경로는 **명시적으로 선택**해야 켜지고, 켜져도 토큰·비용 상한이 걸린다.

## 패키징을 게시 성공으로 과장하지 않는다

두 번째 원칙은 포트폴리오의 정직성에 관한 것이다.

Dockerfile을 쓰고 메타데이터를 채우는 것과, 실제로 Space가 떠서 돌아가는 것은 다른 일이다. 문서에 "Hugging Face에 배포됨"이라고 쓰려면 정말 그래야 한다.

M7의 명령들은 **구성이 올바른지**를 검증하지 **게시가 됐는지**를 증명하지 않는다. 그 구분을 문서에 명시한다. 어느 장도 외부 계정을 변경하지 않는다.

## 세 단계

| 순서 | 단계 | 개념 | 주요 파일 | 상태 |
|---:|---|---|---|---|
| 1 | M7.1 | 무료 동작을 기본값으로, 유료 경로는 범위 제한 | `app/release/`, `app/demo.py`, `tests/release/` | 완료 |
| 2 | M7.2 | 같은 경계를 Docker Space 워커로 패키징 | `deploy/huggingface/`, `.dockerignore`, container/Compose | 완료 |
| 3 | M7.3 | 채워진 소스와 클린 소스 양쪽에서 릴리스 입증 | `scripts/verify_clean_checkout.sh`, status/index 문서 | 완료 |

M7.3이 특히 중요하다. **로컬 캐시나 비밀 값의 도움 없이** 릴리스가 재현되는지 본다. "내 컴퓨터에서는 되는데"를 걸러내는 유일한 방법이다.


---

## 튜토리얼 — 네 번에 나눠 만든다

M7은 파이썬 506줄과 인프라 226줄을 만든다. 각 문서는 **읽고 구현하는 데 30분 안쪽**을 목표로 한다.

| 문서 | 체크포인트 | 만드는 파일 | 대략 |
|---|---|---|---|
| [1. 공개 경계 강화](tutorial/01-hardening.md) | M7.1 | `release/config.py`, `limiter.py`, `middleware.py`, `secrets.py` | 30분 |
| [2. 릴리스 앱 조립](tutorial/02-release-app.md) | M7.1 | `release/app.py`, `__init__.py`, `space.py` | 25분 |
| [3. 컨테이너](tutorial/03-container.md) | M7.2 | `.dockerignore`, `Dockerfile`, `docker-compose.yml`, HF 자산 | 25분 |
| [4. 클린 체크아웃 검증](tutorial/04-clean-checkout.md) | M7.3 | `scripts/verify_clean_checkout.sh` | 20분 |

순서대로 따라간다. 각 구간 끝의 집중 테스트가 통과하지 않으면 다음으로 넘어가지 않는다.

---

## 최종 품질 게이트

```bash
unset OPENAI_API_KEY DOCREVIEW_OPENAI_API_KEY RUN_LIVE_OPENAI_TEST
uv run ruff check --no-fix app tests scripts
uv run ruff format --check app/release app/demo.py tests/release
uv run python scripts/check_doc_code.py docs/en/m7-deployment/03-build.md docs/ko/m7-deployment/03-build.md deploy/huggingface/README.md
uv run pytest tests/test_doc_sync.py tests/test_doc_parity.py -q
scripts/verify_clean_checkout.sh
git diff --check
```

예상 결과: 모든 명령이 종료 상태 0으로 끝나고, 격리 실행에서 잠금된 설정과 미리 준비된 컨테이너 스모크 테스트가 완료되며, 공급자 또는 호스팅 계정에는 접속하지 않는다.

첫 줄의 `unset`을 눈여겨보자. **자격 증명을 명시적으로 지우고** 게이트를 돌린다. 키가 있을 때만 통과하는 검증은 "키 없이도 된다"를 증명하지 못한다.

---

## 시작 조건

잠긴 환경을 설치하고 M5의 서비스 경계부터 검증한다.

```bash
uv sync --group dev
uv run pytest tests/api -q
```

이 장의 명령은 어느 것도 외부 계정을 변경하지 않는다. 컨테이너 빌드에는 Docker가 필요하지만, 없으면 해당 검증만 건너뛴다.

## 네 구간을 똑같이 어렵게 읽지 않는다

M7에도 새 알고리즘은 없다. 대신 **판단**이 많다. 무엇을 기본값으로 둘지, 무엇을 증명했다고 말할 수 있는지.

| 성격 | 문서 | 학습 행동 |
|---|---|---|
| 판정 규칙 | 1 | 한도와 가드를 **직접 구현** — 여기에 시간을 쓴다 |
| 배치 | 2, 3 | **구조 작성 후 호출 순서 검토** |
| 검증 절차 | 4 | 재현 절차를 **직접 구현** |

가장 중요한 것은 4번 문서다. 앞의 셋은 "내 환경에서 되는 것"을 만들고, 4번이 그것을 **아무것도 없는 환경에서 다시 세워** 확인한다.

## 처음 만나는 개념

**무료 기본값(canned mode).** 공개된 데모에 아무나 요청을 보낼 수 있다. 요청마다 LLM을 부르면 비용이 통제 불능이 된다. 그래서 기본 경로는 미리 준비된 응답으로 돌고, 실제 모델 호출은 명시적으로 켤 때만 일어난다. 데모가 정직하려면 화면에 **지금 어느 경로로 답했는지**가 보여야 한다.

**레이트 리밋과 비용 가드.** 레이트 리밋은 시간당 요청 수를 막고, 비용 가드는 누적 지출을 막는다. 둘은 다른 것을 지킨다 — 한 사람이 초당 100번 부르는 것과, 백 명이 하루 종일 조금씩 부르는 것은 다른 문제다.

**패키징과 게시의 구분.** Dockerfile을 쓰고 메타데이터를 채운 것은 **패키징**이다. 그것이 실제로 떠서 응답하는 것은 **게시**다. 이 장의 검증은 전자만 증명한다. 포트폴리오에 후자를 적으려면 실제로 띄워 보고 그 증거를 남겨야 한다.

## M7.1 — 무료 기본 경로, 레이트 리밋, 비용 가드

공개 경계는 통제할 수 없는 트래픽을 전제로 설계한다. 기본값은 요금이 발생하지 않는 경로여야 하고, 유료 경로는 명시적으로 켠 뒤에도 한도 안에서만 돈다. 비밀 값은 응답은 물론 오류 메시지와 로그에도 나가지 않아야 한다.

**문서:** [1. 공개 경계 강화](tutorial/01-hardening.md), [2. 릴리스 앱 조립](tutorial/02-release-app.md) · **통과 기준:** `uv run pytest tests/release/test_01_config.py tests/release/test_02_rate_limit.py -q`

## M7.2 — Hugging Face와 컨테이너 릴리스 자산

파이썬에서 지킨 약속을 이미지 안까지 운반한다. 잠긴 의존성, 같은 진입점, 같은 기본값이 컨테이너 안에서도 그대로여야 한다. `.dockerignore`가 특히 중요하다 — 로컬 캐시나 `.env`가 이미지에 딸려 들어가면 "내 환경에서만 되는" 이미지가 만들어진다.

**문서:** [3. 컨테이너](tutorial/03-container.md) · **통과 기준:** `uv run pytest tests/release/test_05_assets.py -q`

## M7.3 — 클린 아카이브 검증과 정직한 릴리스 게이트

마지막 관문이다. 저장소를 깨끗한 상태로 새로 꺼내 아무 캐시도 비밀 값도 없이 세운다. 여기서 실패하는 것은 대개 커밋되지 않은 파일이나 로컬에만 있는 환경 변수에 의존하던 부분이다. 이 검증을 통과해야 릴리스가 재현 가능하다고 말할 수 있다.

**문서:** [4. 클린 체크아웃 검증](tutorial/04-clean-checkout.md) · **통과 기준:** `uv run pytest tests/release -q`

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **공개 데모의 기본 경로가 무료여야 하는 이유는 무엇인가?**
  - **답:** 공개 엔드포인트는 누구나 호출할 수 있으므로 기본 요청마다 요금이 발생하면 소유자가 통제할 수 없는 트래픽이 지출을 결정한다. 기본값을 미리 준비된 모드로 두면 런타임을 명시적으로 켜기 전까지 공개 경로가 결정론적이고 무료다.
- **레이트 리밋과 비용 가드가 각각 막는 것은 어떻게 다른가?**
  - **답:** 레이트 리밋은 일정 시간의 요청 빈도를 제한하고, 비용 가드는 공급자 호출의 토큰이나 누적 지출을 제한한다. 여러 사용자가 낮은 빈도로 계속 호출하면 첫 한도는 지키면서 두 번째 한도를 소진할 수 있다.
- **비밀 값이 응답이 아니라 오류 메시지로 새는 경로는 어디인가?**
  - **답:** 공급자나 설정 예외에 비밀 값이 포함될 수 있고, 그 예외를 트레이스백이나 로그로 변환하면 정상 응답에 값이 없어도 노출된다. 따라서 오류와 로그 경로도 함께 편집해야 한다.
- **`.dockerignore`가 없으면 이미지에 무엇이 딸려 들어가는가?**
  - **답:** 빌드 컨텍스트에 로컬 가상환경, 캐시, 데이터, 비밀이 든 `.env` 파일이 포함될 수 있다. 이후 `COPY`가 이 로컬 산출물을 이미지 레이어에 넣으면 이미지가 안전하지 않고 특정 개발 환경에 의존하게 된다.
- **패키징을 마쳤을 때 문서에 쓸 수 있는 문장과 쓸 수 없는 문장은 무엇인가?**
  - **답:** 릴리스 자산을 패키징했고 구성을 검증했다고는 쓸 수 있다. 실제 실행 중인 배포를 확인하고 증거를 남기기 전에는 Hugging Face에 게시하거나 배포했다고 쓸 수 없다.
- **클린 체크아웃 검증이 잡아내는 실패는 구체적으로 어떤 모습인가?**
  - **답:** 새 아카이브에서 커밋되지 않은 모듈을 import하지 못하거나, 락 파일과 다른 의존성이 해석되거나, 로컬 비밀·데이터베이스·캐시가 없어 기동에 실패하는 모습이다. 개발자의 채워진 환경이 숨기던 의존성들이다.

## 이 모듈이 다음 모듈에 넘기는 것

M7까지로 배포 가능한 시스템이 됐다. 남은 한 장은 성격이 완전히 다르다.

| M7이 만든 것 | 받는 곳 | 거기서 하는 일 |
|---|---|---|
| 기본값이 고정된 배포 가능한 질의 경로 | **M8** | 다른 언어로 질문받는 같은 경로 |
| 여전히 무수정인 M3 평가 하니스 | **M8** | 채점기를 고치지 않아도 되는 언어별 실행 |
| 릴리스 게이트에서 익힌 정직 보고 습관 | **M8** | 주장 대신 바닥이 있는 동등성 비율 |

다음 장 M8은 **교차 언어 검색**이다. 코퍼스는 영어 공시 20건 그대로이고, 질문이 한국어로 들어온다. 핵심 질문은 이것이다 — **한국어 질문이 올바른 영어 구절을 찾아내는가, 그리고 그것을 어떻게 아는가.** lexical 인덱스는 영어 텍스트 검색 구성 하나로 만들어졌고, 벡터 실험군은 토큰 해시 벡터로만 측정된 적이 있으며, 두 사실 모두 응답에서는 보이지 않는다. M8은 그 미지를 측정된 표로 바꾸고 게이트를 건다.

## 기계 검증용 최종 기준본

위의 장들이 실행할 빌드 경로이다. 아래 자동 생성 절은 M7.1 전에 미리 작성할 묶음이 아니라 `reference_revision`과 맞춘 기계 검증용 최종 기준본이며, 외부 배포가 이루어졌다는 증거도 아니다.

<!-- complete-files:start -->
## 완성 기준본 — 정식 구현 전체

아래 정식 경로를 직접 생성하거나 교체한다. `_mine.py` 또는 별도의 학습자용 복사 모듈을 만들지 않는다. 앞의 발췌 코드는 개별 결정을 설명하고, 이 절의 코드 블록은 체크포인트를 마친 뒤 대조할 완성 파일이다. 표시된 타입 어노테이션과 영어 주석을 유지하며 `pyproject.toml`을 Ruff 정책의 기준으로 사용한다.

### M7.1 — 완성 체크포인트

#### 생성 또는 교체 `app/release/__init__.py`

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

#### 생성 또는 교체 `app/release/config.py`

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

#### 생성 또는 교체 `app/release/limiter.py`

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

#### 생성 또는 교체 `app/release/middleware.py`

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

#### 생성 또는 교체 `app/release/secrets.py`

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

#### 생성 또는 교체 `app/release/app.py`

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

#### 생성 또는 교체 `app/release/space.py`

<!-- file: app/release/space.py -->
```python
"""Hugging Face Docker Space entrypoint; canned mode is the default."""

from app.release import create_release_app

app = create_release_app()
```

체크포인트를 실행한다.

```bash
uv run pytest tests/release/test_01_config.py tests/release/test_02_rate_limit.py tests/release/test_03_guards.py tests/release/test_04_app.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M7.2 — 완성 체크포인트

#### 생성 또는 교체 `.dockerignore`

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

#### 생성 또는 교체 `Dockerfile`

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

#### 생성 또는 교체 `docker-compose.yml`

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

#### 생성 또는 교체 `deploy/huggingface/Dockerfile`

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

#### 생성 또는 교체 `deploy/huggingface/space.env.example`

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

체크포인트를 실행한다.

```bash
uv run pytest tests/release/test_05_assets.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M7.3 — 완성 체크포인트

#### 생성 또는 교체 `scripts/verify_clean_checkout.sh`

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

체크포인트를 실행한다.

```bash
uv run pytest tests/release -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

<!-- complete-files:end -->
