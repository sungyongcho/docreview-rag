# M5.1 튜토리얼 3 — 일곱 개의 얇은 라우트

스키마와 주입 계층을 만들었으므로 이제 라우트를 작성한다. **일곱 파일을 합쳐 146줄이다.**

**라우트가 이보다 길어졌다면 검증·호출·투영 외의 로직, 즉 도메인 판단이 전송 계층으로 들어온 것이다.**

**선행 조건:** 튜토리얼 2까지 `api/errors.py`와 `deps.py`를 작성한 상태여야 한다.

### 라우트 하나의 모양

전부 같은 세 줄 구조다.

1. FastAPI가 요청을 엄격한 모델로 파싱한다. 2. 주입받은 서비스 메서드 하나를 부른다. 3. 응답 스키마로 투영한다.

`retrieve.py`에만 한 줄이 더 있다. 반환값이 `RetrievalResult`인지 일반 시퀀스인지 판별하는 줄이며, `ApiServices`가 두 형태를 모두 허용하도록 선언했기 때문이다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 라우트 일곱 개 | **구조 작성** | 라우트가 짧아야 하는 이유 |
| `routes/__init__.py` | **구조 작성** | 라우터 등록 순서 |
| `create_api_app` | **설계 결정 확인** | 팩터리가 전역 앱보다 나은 이유 |

### 1. 검색·문서·수집

#### `app/api/routes/retrieve.py` 생성 — 검색 라우트

**학습 행동 — 구조 작성:** `Services` 별칭이 무엇을 선언하는지 확인한다. 일곱 파일이 모두 같은 줄을 사용한다.

```python
"""Retrieve resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import EvidenceHit, RetrieveRequest, RetrieveResponse
from app.retrieval import RetrievalResult

router = APIRouter(tags=["retrieve"])
Services = Annotated[ApiServices, Depends(get_api_services)]


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_evidence(request: RetrieveRequest, services: Services) -> RetrieveResponse:
    """Return source-cited ranked evidence for one validated query."""
    result = await services.retrieve(request)
    hits = result.hits if isinstance(result, RetrievalResult) else tuple(result)
    return RetrieveResponse(
        query=request.query,
        results=tuple(EvidenceHit.from_chunk_hit(hit) for hit in hits),
    )
```

**코드에서 꼭 볼 것**

- `Services = Annotated[ApiServices, Depends(get_api_services)]`가 주입을 한 줄로 선언한다. 타입 힌트가 그대로 의존성 선언이 된다.
- 라우트가 `RetrievalResult`를 import하지만 **응답으로 투영하기 위해서만** 사용한다. 검색 동작에는 관여하지 않는다.
- `EvidenceHit.from_chunk_hit`이 변환을 담당한다. 라우트가 필드를 직접 옮기지 않으므로 필드가 추가돼도 라우트는 수정하지 않는다.

#### `app/api/routes/documents.py` 생성 — 문서 목록

```python
"""Document collection resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import DocumentListResponse

router = APIRouter(tags=["documents"])
Services = Annotated[ApiServices, Depends(get_api_services)]


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(services: Services) -> DocumentListResponse:
    """Return the deterministic collection of ingested filings."""
    documents = tuple(await services.list_documents())
    return DocumentListResponse(documents=documents)
```

#### `app/api/routes/ingest.py` 생성 — 수집

```python
"""Synchronous ingestion resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import IngestRequest, IngestResponse

router = APIRouter(tags=["ingest"])
Services = Annotated[ApiServices, Depends(get_api_services)]


@router.post("/ingest", response_model=IngestResponse)
async def ingest_manifest(request: IngestRequest, services: Services) -> IngestResponse:
    """Parse and persist one explicit local manifest before responding."""
    result = await services.ingest(request)
    return IngestResponse(documents=result.documents, chunks=result.chunks)
```

**코드에서 꼭 볼 것**

- 수집은 POST이고 동기로 처리한다. 큐나 백그라운드 태스크를 두지 않으며, M5는 동기 경계만 만든다.
- 두 라우트 모두 세 줄이다. 서비스가 반환한 값을 응답 스키마에 넣는 것이 전부다.

### 2. 검토·실행·트레이스·평가

#### `app/api/routes/review.py` 생성 — 워크플로 실행

**학습 행동 — 구조 작성:** M4의 네 종료 상태가 하나의 응답 타입으로 표현되는 방식을 확인한다.

```python
"""Synchronous evidence-review resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import ReviewRequest, RunResponse

router = APIRouter(tags=["review"])
Services = Annotated[ApiServices, Depends(get_api_services)]
STATUS_CODES = {
    "ok": 200,
    "budget_exceeded": 429,
    "schema_rejected": 502,
    "error": 503,
}


@router.post("/review", response_model=RunResponse)
async def review_query(
    request: ReviewRequest,
    response: Response,
    services: Services,
) -> RunResponse:
    """Complete one guarded workflow and return its terminal run resource."""
    result = RunResponse.from_run_report(await services.review(request))
    response.status_code = STATUS_CODES[result.status]
    return result
```

#### `app/api/routes/runs.py` 생성 — 실행 조회

```python
"""Persisted workflow run resource route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import ApiServices, get_api_services
from app.api.errors import not_found
from app.api.schemas import RunResponse

router = APIRouter(tags=["runs"])
Services = Annotated[ApiServices, Depends(get_api_services)]
RunPath = Annotated[
    str,
    Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: RunPath, services: Services) -> RunResponse:
    """Return one persisted run without executing it again."""
    result = await services.get_run(run_id)
    if result is None:
        raise not_found("run", run_id)
    return RunResponse.from_run_report(result)
```

#### `app/api/routes/traces.py` 생성 — 트레이스 조회

```python
"""Persisted provider trace collection route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import ApiServices, get_api_services
from app.api.errors import not_found
from app.api.schemas import TraceListResponse

router = APIRouter(tags=["traces"])
Services = Annotated[ApiServices, Depends(get_api_services)]
RunPath = Annotated[
    str,
    Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


@router.get("/runs/{run_id}/traces", response_model=TraceListResponse)
async def list_traces(run_id: RunPath, services: Services) -> TraceListResponse:
    """Return ordered raw provider traces for one persisted run."""
    traces = await services.get_traces(run_id)
    if traces is None:
        raise not_found("run", run_id)
    return TraceListResponse(run_id=run_id, traces=tuple(traces))
```

#### `app/api/routes/eval.py` 생성 — 평가 결과 조회

```python
"""Persisted evaluation result collection route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import EvalListResponse

router = APIRouter(tags=["eval"])
Services = Annotated[ApiServices, Depends(get_api_services)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/eval", response_model=EvalListResponse)
async def list_eval_results(
    services: Services,
    limit: Limit = 20,
) -> EvalListResponse:
    """Return the newest persisted retrieval evaluation results."""
    results = tuple(await services.list_eval_results(limit))
    return EvalListResponse(results=results)
```

**코드에서 꼭 볼 것**

- `review`는 워크플로가 실패해도 200을 반환한다. 실행 결과는 `status` 필드가 나타내며, 이 필드는 `RunResponse` 안에 있다. **예산 초과는 서버가 요청을 처리하지 못한 상태가 아니라 워크플로가 정의된 조건에서 멈춘 상태이므로 HTTP 오류로 보고하지 않는다.**
- 조회 라우트 세 개는 모두 `not_found` 판정을 서비스에서 받는다. 라우트가 리소스 존재 여부를 직접 판단하지 않는다.
- `eval.py`는 평가를 실행하지 않는다. M3가 저장한 결과를 읽기만 한다.

### 3. 라우터 등록과 앱 팩터리

#### `app/api/routes/__init__.py` 생성 — 라우터 모음

**학습 행동 — 구조 작성:** 라우터 등록 순서가 파일 이름 순이 아니라는 점을 확인한다.

```python
"""Resource-oriented M5 route collection."""

from fastapi import APIRouter

from app.api.routes import documents, eval, ingest, retrieve, review, runs, traces

api_router = APIRouter()
for module in (retrieve, documents, ingest, review, runs, traces, eval):
    api_router.include_router(module.router)

__all__ = ["api_router"]
```

**코드에서 꼭 볼 것**

- 등록 순서는 `retrieve, documents, ingest, review, runs, traces, eval`이다. **OpenAPI 문서의 엔드포인트 나열 순서가 이 등록 순서를 따르므로, 파일 이름순이 아니라 파이프라인 진행 순서로 배치한다.**

#### `app/api/app.py` 생성 — 애플리케이션 팩터리

**학습 행동 — 설계 결정 확인:** 모듈 수준의 `app = FastAPI()` 대신 팩터리 함수를 쓰는 이유를 확인한다.

```python
"""FastAPI application factory with explicit service injection."""

from fastapi import FastAPI

from app.api.deps import ApiServices, get_api_services
from app.api.errors import install_error_handlers
from app.api.routes import api_router


def create_api_app(services: ApiServices | None = None) -> FastAPI:
    """Create the synchronous M5 HTTP application without starting external services."""
    app = FastAPI(title="Document Review RAG API", version="0.1.0")
    install_error_handlers(app)
    app.include_router(api_router)
    if services is not None:
        app.dependency_overrides[get_api_services] = lambda: services
    return app
```

**코드에서 꼭 볼 것**

- 앱을 팩터리 함수로 만든다. **모듈 수준에 `app`을 두면 이 모듈을 import하는 것만으로 앱이 생성되고, 그 시점에 설정과 연결이 함께 만들어진다.** 다음 문서에서 그 결과를 다룬다.
- `services=None`이 기본값이다. 인자 없이 호출하면 `get_api_services`의 기본 구현이 그대로 남아 첫 요청에서 실패한다.
- 주입은 `dependency_overrides`로 한다. **테스트가 가짜 서비스를 넣는 경로와 운영이 실제 서비스를 넣는 경로가 같으므로, 테스트가 검증하는 조립 방식이 운영에서도 그대로 사용된다.**

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/api/test_01_schemas.py tests/api/test_02_errors.py \
  tests/api/test_03_resources.py tests/api/test_04_operations.py tests/api/test_05_routes.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 응답에 실린 예외 메시지 | 내부 정보가 클라이언트로 새지 않는다. |
| 도메인 타입을 import하는 라우트 | 전송 계층이 교체 가능하게 유지된다. |
| `budget_exceeded`에 대한 HTTP 500 | 예산 초과가 서버 오류로 보고되지 않는다. |
| 응답에 포함된 `index_text` | 내부 색인 방식이 계약이 되지 않는다. |
| 조립되지 않은 앱의 요청 | 조용히 도는 대신 첫 요청에서 실패한다. |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 라우트와 연결해 설명해 본다.

- **라우트가 길어지면 무엇이 새어 들어온 것인가?**
  - **답:** 서비스 경계 뒤에 있어야 할 도메인 규칙, 워크플로 제어 흐름, 인프라 처리가 전송 계층으로 새어 들어온 것이다.
- **`review`가 실패해도 200인 이유는 무엇인가?**
  - **답:** 현재 코드는 실패에 200을 반환하지 않는다. `ok`만 200이고, `budget_exceeded`는 429, `schema_rejected`는 502, `error`는 503으로 `STATUS_CODES`에서 매핑한다.
- **라우터 등록 순서가 무엇에 영향을 주는가?**
  - **답:** 생성된 OpenAPI 문서에 엔드포인트가 나오는 순서를 정하므로 독자가 API를 이해하는 흐름에 영향을 준다.
- **모듈 수준 `app` 대신 팩터리를 쓰는 이유는 무엇인가?**
  - **답:** 앱 생성과 서비스 주입을 명시적으로 만들고, 단순 import가 조립 작업을 수행하지 않은 채 격리된 앱을 만들 수 있게 하기 위해서다.
- **테스트가 가짜 서비스를 넣는 방법이 운영과 같아야 하는 이유는 무엇인가?**
  - **답:** 같은 의존성 재정의 경계를 사용해야 테스트 전용 우회로가 아니라 실제 조립 계약을 검증할 수 있기 때문이다.

---

[← 이전: 오류와 의존성](02-errors-deps.md) · [모듈 개요](../03-build.md) · [다음: 런타임 조립 →](04-runtime.md)
