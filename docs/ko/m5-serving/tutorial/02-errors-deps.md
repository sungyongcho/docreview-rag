# M5.1 튜토리얼 2 — 새지 않는 오류와 주입 이음매

스키마를 정의했으므로 이제 두 가지를 작성한다. 실패가 응답으로 나가는 통로와, 도메인 구현이 라우트로 주입되는 통로다.

**선행 조건:** 튜토리얼 1에서 `api/schemas.py`를 작성한 상태여야 한다. 테스트는 튜토리얼 3에서 함께 돈다.

### 스택 트레이스가 응답에 실리면 안 된다

FastAPI는 처리되지 않은 예외에 대해 500을 반환하고 서버 로그를 남긴다. 설정에 따라 **예외 메시지가 응답 본문에 포함될 수 있다.**

예외 메시지에는 데이터베이스 URL, 파일 경로, 내부 클래스 이름이 들어갈 수 있다. 그래서 마지막 핸들러를 하나 두고, 어떤 예외가 발생하든 `internal_error` 하나로 응답한다.

**원인은 로그에 남기고 응답 본문에는 남기지 않는다. 두 경로를 분리해야 운영자가 원인을 확인하면서도 내부 정보가 클라이언트로 나가지 않는다.**

### 라우트가 도메인을 부르는 유일한 통로

`ApiServices`는 `Protocol`이다. 라우트는 이 프로토콜에 선언된 메서드만 호출하고, 그 메서드의 실제 구현은 M5.2에서 정한다.

M4.2에서 관측 계층이 `Protocol`로 공급자를 받은 것과 같은 구조다. **라우트가 M2와 M4를 import하지 않으므로 의존이 한 방향으로만 흐른다.**

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `ApiProblemError` | **레코드 선언 작성** | 도메인 실패를 HTTP로 옮기는 값 |
| `install_error_handlers` | 핸들러 넷을 **직접 구현** | 마지막 핸들러가 막는 것 |
| `ApiServices` | **설계 결정 확인** | 프로토콜이 유지하는 의존 방향 |
| `get_api_services` | **구조 작성** | 조립 전에 실패시키는 기본값 |

### 1. 도메인 실패를 HTTP로 옮긴다

#### `app/api/errors.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록에 도메인 모듈이 없다는 점을 확인한다.

```python
"""Stable typed error handling for malformed and failed API requests."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas import ApiError, ErrorResponse, ValidationIssue

```

#### `app/api/errors.py` 확장 — 문제 예외와 응답 변환

**학습 행동 — 레코드 선언 작성:** `bad_request`와 `not_found`를 상수가 아니라 함수로 두는 이유를 확인한다.

<!-- src: app/api/errors.py::ApiProblemError,_validation_issue -->
```python
class ApiProblemError(Exception):
    """An expected HTTP failure with a stable machine code."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Sequence[ValidationIssue] = (),
    ) -> None:
        super().__init__(message)
        if not 400 <= status_code <= 599:
            raise ValueError("API problem status must be between 400 and 599")
        self.status_code = status_code
        self.error = ApiError(code=code, message=message, details=tuple(details))


def bad_request(code: str, message: str) -> ApiProblemError:
    """Build one typed client-input failure."""
    return ApiProblemError(status_code=400, code=code, message=message)


def not_found(resource: str, identity: str) -> ApiProblemError:
    """Build one typed missing-resource failure."""
    return ApiProblemError(
        status_code=404,
        code=f"{resource}_not_found",
        message=f"{resource} {identity} was not found.",
    )


def _response(status_code: int, error: ApiError) -> JSONResponse:
    body = ErrorResponse(error=error)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _validation_issue(error: dict[str, object]) -> ValidationIssue:
    raw_location = error.get("loc", ())
    if not isinstance(raw_location, tuple | list):
        raw_location = (str(raw_location),)
    location = tuple(value if isinstance(value, int) else str(value) for value in raw_location)
    return ValidationIssue(
        location=location,
        message=str(error.get("msg", "Invalid request.")),
        error_type=str(error.get("type", "validation_error")),
    )
```

**코드에서 꼭 볼 것**

- `ApiProblemError`는 상태 코드와 `ApiError`를 함께 담는다. 도메인 코드는 HTTP 상태 코드를 직접 다루지 않고 이 예외만 던진다.
- `bad_request`와 `not_found`는 팩터리 함수다. 상태 코드가 호출부마다 흩어지지 않고 이 함수 안에만 존재한다.
- `_validation_issue`가 FastAPI의 오류 딕셔너리를 이 프로젝트의 스키마로 변환한다. **이 변환을 거치지 않으면 검증 오류 응답에 내부 타입 이름이 그대로 포함된다.**

### 2. 마지막 핸들러가 막는 것

#### `app/api/errors.py` 완성 — 오류 핸들러 설치

**학습 행동 — 핸들러 구현:** 핸들러 네 개를 직접 구현하고, 등록 순서가 동작에 영향을 주는지 확인한다.

<!-- src: app/api/errors.py::install_error_handlers -->
```python
def install_error_handlers(app: FastAPI) -> None:
    """Install non-leaking error envelopes on one FastAPI application."""

    @app.exception_handler(ApiProblemError)
    async def api_problem_handler(request: Request, error: ApiProblemError) -> JSONResponse:
        return _response(error.status_code, error.error)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        details = tuple(_validation_issue(issue) for issue in error.errors())
        return _response(
            422,
            ApiError(
                code="request_validation_failed",
                message="Request validation failed.",
                details=details,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = "route_not_found" if error.status_code == 404 else "http_error"
        message = str(error.detail) if isinstance(error.detail, str) else "HTTP request failed."
        return _response(error.status_code, ApiError(code=code, message=message))

    @app.exception_handler(Exception)
    async def internal_handler(request: Request, error: Exception) -> JSONResponse:
        return _response(
            500,
            ApiError(
                code="internal_error",
                message="The request could not be completed.",
            ),
        )
```

**코드에서 꼭 볼 것**

- `@app.exception_handler(Exception)`이 마지막 처리 지점이다. **여기 도달한 예외는 메시지를 응답에 넣지 않는다.** `str(error)`의 내용이 무엇이든 응답 본문에는 포함되지 않는다.
- 404에만 `route_not_found` 코드를 따로 부여한다. 존재하지 않는 경로 요청과 다른 HTTP 오류를 클라이언트가 코드로 구분할 수 있다.
- `RequestValidationError`는 422로 응답한다. **요청 형식 자체는 올바르고 값이 스키마 제약을 만족하지 않는 경우이므로, 요청을 해석하지 못한 400과 구분한다.**
- 모든 핸들러가 `_response`를 거친다. 응답 봉투를 만드는 코드가 한 곳에만 존재한다.

### 3. 프로토콜이 유지하는 의존 방향

#### `app/api/deps.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** 이 파일은 도메인 타입을 import한다. 라우트가 아니라 도메인과 라우트를 연결하는 계층이기 때문이다.

```python
"""Injected application-service seam for the synchronous HTTP boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.api.errors import ApiProblemError
from app.api.schemas import (
    DocumentResource,
    EvalResultResource,
    IngestRequest,
    RetrieveRequest,
    ReviewRequest,
)
from app.ingestion.seed import SeedResult
from app.observability import RunReport, StepTrace
from app.retrieval import ChunkHit, RetrievalResult

```

#### `app/api/deps.py` 완성 — 서비스 프로토콜

**학습 행동 — 설계 결정 확인:** 메서드 일곱 개가 각각 어느 라우트에 대응하는지 정리하며 확인한다.

<!-- src: app/api/deps.py::ApiServices,get_api_services -->
```python
class ApiServices(Protocol):
    """All domain operations required by the seven HTTP resources."""

    async def retrieve(
        self,
        request: RetrieveRequest,
    ) -> RetrievalResult | Sequence[ChunkHit]:
        """Return ranked evidence without performing HTTP work."""
        ...

    async def list_documents(self) -> Sequence[DocumentResource]:
        """Return document resources in deterministic order."""
        ...

    async def ingest(self, request: IngestRequest) -> SeedResult:
        """Run one synchronous local-manifest ingestion operation."""
        ...

    async def review(self, request: ReviewRequest) -> RunReport:
        """Run and persist one complete evidence-checked workflow."""
        ...

    async def review_stream(
        self,
        request: ReviewRequest,
        on_node: NodeObserver,
    ) -> RunReport:
        """Run one reviewed workflow while reporting each completed node."""
        ...

    async def get_run(self, run_id: str) -> RunReport | None:
        """Return one persisted run or null when it does not exist."""
        ...

    async def get_traces(self, run_id: str) -> Sequence[StepTrace] | None:
        """Return ordered traces or null when the parent run does not exist."""
        ...

    async def list_eval_results(self, limit: int) -> Sequence[EvalResultResource]:
        """Return the newest persisted evaluation resources."""
        ...


def get_api_services() -> ApiServices:
    """Require production composition or a test override to inject services."""
    raise ApiProblemError(
        status_code=503,
        code="service_unavailable",
        message="API services are not configured.",
    )
```

**코드에서 꼭 볼 것**

- `Protocol`이므로 구현체가 상속을 선언하지 않는다. M5.2의 `RuntimeApiServices`는 메서드 모양만 맞추면 된다.
- 메서드를 모두 `async`로 선언한다. 동기 구현도 가능하지만, 이후 I/O를 추가할 때 시그니처와 호출부를 함께 바꾸지 않아도 된다.
- `get_api_services`의 기본 구현은 **예외를 던진다.** **의존성을 조립하지 않은 앱이 그대로 기동해 요청을 받는 대신, 첫 요청에서 명확한 오류로 실패한다.**

#### `app/api/__init__.py` 생성 — 패키지 표면

**학습 행동 — 구조 작성:** M5.1이 공개하는 표면을 확인하며 작성한다.

```python
"""Strict, injected synchronous HTTP boundary for M5."""

from app.api.app import create_api_app
from app.api.deps import ApiServices, get_api_services
from app.api.errors import ApiProblemError, bad_request, install_error_handlers, not_found
from app.api.routes import api_router
from app.api.runtime import RuntimeApiServices
from app.api.schemas import (
    ApiError,
    BudgetLimitFailure,
    DocumentListResponse,
    DocumentResource,
    ErrorResponse,
    EvalListResponse,
    EvalResultResource,
    EvidenceHit,
    IngestRequest,
    IngestResponse,
    RetrieveRequest,
    RetrieveResponse,
    ReviewRequest,
    RunResponse,
    TraceListResponse,
    ValidationIssue,
)

router = api_router

__all__ = [
    "ApiError",
    "ApiProblemError",
    "ApiServices",
    "BudgetLimitFailure",
    "DocumentListResponse",
    "DocumentResource",
    "ErrorResponse",
    "EvalListResponse",
    "EvalResultResource",
    "EvidenceHit",
    "IngestRequest",
    "IngestResponse",
    "RetrieveRequest",
    "RetrieveResponse",
    "ReviewRequest",
    "RuntimeApiServices",
    "RunResponse",
    "TraceListResponse",
    "ValidationIssue",
    "api_router",
    "bad_request",
    "create_api_app",
    "get_api_services",
    "install_error_handlers",
    "not_found",
    "router",
]
```

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 핸들러 또는 타입과 연결해 설명해 본다.

- **마지막 예외 핸들러가 메시지를 버리는 이유는 무엇인가?**
  - **답:** 예상하지 못한 예외에는 DB URL, 파일 경로 같은 내부 정보가 들어 있을 수 있어 일반화된 오류만 응답하는 것이 안전하기 때문이다.
- **검증 실패가 400이 아니라 422인 이유는 무엇인가?**
  - **답:** HTTP와 JSON 문법은 유효하지만 값이 선언된 의미적 스키마를 어긴 요청이기 때문이다.
- **`ApiServices`가 `Protocol`이어서 유지되는 의존 방향은 무엇인가?**
  - **답:** `ApiServices`를 통해 라우트는 전송 계층이 소유한 서비스 인터페이스를 호출하고, 런타임 어댑터가 도메인 코드로 이를 구현한다. 하지만 모든 라우트의 도메인 import가 사라지는 것은 아니다. `retrieve.py`는 응답 투영을 위해 `RetrievalResult`를 여전히 import한다.
- **`get_api_services` 기본 구현이 예외를 던지는 이유는 무엇인가?**
  - **답:** 조립되지 않은 앱이 서비스가 빠진 채 실행되는 척하지 않고 첫 요청에서 즉시 실패하게 하기 위해서다.
- **`deps.py`는 도메인을 import하는데 라우트는 하지 않는 이유는 무엇인가?**
  - **답:** 질문의 전제는 일부만 맞다. 서비스 호출은 `deps.py`의 프로토콜을 지나지만, `retrieve.py`는 API 응답으로 투영하기 위해 `RetrievalResult`를 직접 import한다. 이 경계가 격리하는 것은 실행이며 투영에 쓰는 모든 도메인 타입은 아니다.

---

[← 이전: API 스키마](01-schemas.md) · [모듈 개요](../03-build.md) · [다음: 라우트 →](03-routes.md)
