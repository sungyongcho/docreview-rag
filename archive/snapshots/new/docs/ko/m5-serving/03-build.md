# M5 구현 — 다른 프로그램이 믿고 부를 수 있는 표면 만들기

## 지금까지는 파이썬 함수였다

M4가 끝나면 `run_workflow()`를 호출해서 근거에 묶인 답을 받을 수 있다. 그런데 그건 파이썬 프로세스 안에서만 가능하다.

이제 HTTP로 연다. 그러면 M6의 데모 UI도, 외부 클라이언트도 쓸 수 있다.

단순히 FastAPI 라우트를 얹으면 될 것 같지만, 경계를 열면 새로운 문제들이 따라온다.

- 요청이 **동시에** 여러 개 들어온다. 세션과 예산이 섞이면 안 된다
- 입력이 **신뢰할 수 없다.** 아무 JSON이나 들어온다
- 실패했을 때 **내부 정보가 새면 안 된다.** 스택 트레이스나 SQL이 응답에 나가면 곤란하다
- M4의 네 가지 종료 상태를 **HTTP 코드로 옮겨야** 한다

## 체크포인트 지도

| 순서 | 체크포인트 | 목표 | 정식 파일 |
|---:|---|---|---|
| 1 | M5.1 | 엄격한 타입 기반 HTTP 경계 추가 | `app/api/` |
| 2 | M5.2 | 결정론적 런타임 진입점 추가 | `app/config.py`, `app/api/runtime.py`, `app/main.py`, `app/cli.py` |
| 3 | M5.3 | M2·M4·CLI·HTTP를 연결하는 프로덕션 구성 입증 | 기존 M5 정식 파일 |
| 4 | M5.4 | server-sent events로 실행 진행 스트리밍 | `app/api/routes/stream.py` |

요청이 이동하는 순서 그대로 만든다. 검증 명령보다 정식 파일이 먼저 나오므로, 깨끗한 학습 브랜치가 다음 단계 모듈을 미리 import하다 멈추는 일이 없다.


---

## 튜토리얼 — 여섯 번에 나눠 만든다

M5는 파일 열일곱, 소스 1,647줄을 만든다. 각 문서는 **읽고 구현하는 데 30분 안쪽**을 목표로 한다.

| 문서 | 체크포인트 | 만드는 파일 | 대략 |
|---|---|---|---|
| [1. API 스키마](tutorial/01-schemas.md) | M5.1 | `api/schemas.py` | 30분 |
| [2. 오류와 의존성](tutorial/02-errors-deps.md) | M5.1 | `api/errors.py`, `deps.py`, `__init__.py` | 25분 |
| [3. 라우트](tutorial/03-routes.md) | M5.1 | `api/routes/` 7개, `routes/__init__.py`, `app.py` | 25분 |
| [4. 런타임 조립](tutorial/04-runtime.md) | M5.2 | `api/runtime.py`, `main.py` | 30분 |
| [5. CLI와 조립 검증](tutorial/05-cli.md) | M5.2–M5.3 | `cli.py` | 30분 |
| [6. 스트리밍](tutorial/06-streaming.md) | M5.4 | `api/routes/stream.py` | 25분 |

순서대로 따라간다. 각 구간 끝의 집중 테스트가 통과하지 않으면 다음으로 넘어가지 않는다.

---

## 최종 품질 게이트

```bash
uv run pytest -o addopts="" -q
uv run ruff check .
uv run ruff format --check app/api app/cli.py app/main.py tests/api
uv run python scripts/check_doc_code.py docs/en/m5-serving/03-build.md docs/ko/m5-serving/03-build.md
git diff --check
```

예상 결과: 모든 명령이 종료 상태 0으로 끝난다. 이전 테스트 개수를 복사하지 말고 측정한 결과를 기록하며, 이 게이트에는 유료 호출이 포함되지 않는다.

---

## 시작 조건

잠긴 환경을 설치하고 M4 경계부터 검증한다.

```bash
uv sync --group dev
uv run pytest tests/workflow -q
```

이 장의 테스트는 실제 서버를 띄우지 않고 FastAPI 테스트 클라이언트로 돈다. 데이터베이스와 LLM은 주입된 대역으로 대체되므로 요금이 발생하지 않는다.

## 여섯 구간을 똑같이 어렵게 읽지 않는다

M5에는 새로운 알고리즘이 없다. 전부 경계와 배치다. 그래서 읽는 법이 앞 장들과 다르다.

| 성격 | 문서 | 학습 행동 |
|---|---|---|
| 계약 선언 | 1 | **모델 선언 작성** — 공개 스키마가 도메인 타입과 다른 이유 확인 |
| 경계 규칙 | 2 | 오류 매핑을 **직접 구현** — 여기에 시간을 쓴다 |
| 배치 | 3, 4, 5, 6 | **구조 작성 후 호출 순서 검토** |

시간을 아껴야 한다면 2번 문서에 머문다. **무엇이 응답에 나가고 무엇이 나가면 안 되는지**를 정하는 자리이고, 여기서 새면 나머지를 아무리 잘 만들어도 소용이 없다.

## 처음 만나는 개념

**공개 스키마와 도메인 타입을 왜 나누는가.** M2의 `ChunkHit`이나 M4의 워크플로 상태를 그대로 JSON으로 내보내면 편하다. 그런데 그렇게 하면 내부 타입을 바꾸는 순간 API 계약이 깨지고, 내부에만 있어야 할 필드가 외부로 새어 나간다. 그래서 경계에 별도의 응답 스키마를 두고 변환을 명시한다.

**의존성 주입.** 라우트 함수가 데이터베이스 세션이나 워크플로 러너를 직접 만들지 않고, 프레임워크가 넣어 주는 것을 받아 쓴다. 테스트에서 그 자리에 대역을 넣을 수 있고, 요청 하나가 세션 하나를 소유한다는 M2.7의 규칙을 HTTP 경계까지 그대로 이어 갈 수 있다.

## M5.1 — 타입이 강제되는 HTTP 자원

라우트는 도메인을 몰라야 한다. 요청을 받아 검증하고, 주입된 의존성에 넘기고, 결과를 공개 스키마로 바꿔 돌려줄 뿐이다. 여기서 가장 조심할 것은 오류 경로다. 예외를 그대로 흘리면 스택 트레이스나 SQL이 응답 본문에 실려 나간다. 그래서 M4의 종료 상태를 HTTP 코드로 옮기는 매핑을 명시적으로 만들고, 매핑에 없는 예외는 내부 정보 없이 500으로 닫는다.

**문서:** [1. API 스키마](tutorial/01-schemas.md) ~ [3. 라우트](tutorial/03-routes.md) · **통과 기준:** `uv run pytest tests/api/test_01_schemas.py tests/api/test_02_errors.py -q`

## M5.2 — 결정론적 런타임 진입점

`import app.main`만으로는 아무 일도 일어나면 안 된다. 모듈을 가져오는 것만으로 데이터베이스에 붙거나 설정을 읽으면 테스트가 환경에 끌려다니고, 임포트 순서가 동작을 바꾼다. 그래서 조립을 팩토리 함수 안으로 모으고, 설정은 한 곳에서만 읽는다. CLI도 같은 팩토리를 쓰므로 HTTP로 부르든 명령줄로 부르든 같은 근거가 나온다.

**문서:** [4. 런타임 조립](tutorial/04-runtime.md), [5. CLI](tutorial/05-cli.md) · **통과 기준:** `uv run pytest tests/api/test_06_runtime.py tests/api/test_07_cli.py -q`

## M5.3 — 프로덕션 구성 입증

마지막으로 M2의 검색, M4의 워크플로, CLI, HTTP가 실제로 한 줄로 이어지는지 확인한다. 앞의 두 체크포인트는 각 조각을 따로 검증했고, 여기서는 조각들이 같은 설정과 같은 세션 규칙 위에서 함께 도는지를 본다.

**문서:** [5. CLI](tutorial/05-cli.md) · **통과 기준:** `uv run pytest tests/api/test_08_integration.py -q`

## M5.4 — 실행을 실행 중에 스트리밍한다

동기 리뷰 엔드포인트는 검색 한 번과 가드된 LLM 호출 두 번이 끝난 뒤 한 번만 답한다. M5.4는 `POST /review/stream`을 더한다. 러너가 커밋된 노드마다 옵저버로 보고하고, 서비스 시임이 이를 실어 나르며, 라우트가 server-sent events로 다리를 놓는다 — 진행은 `node`, 종결 실행은 `report`, 명시적 종료는 `done`이다. 실패한 실행은 여전히 구조화된 리포트이고, `error`는 실행 자체를 만들지 못한 예외에만 예약된다.

**문서:** [6. 스트리밍](tutorial/06-streaming.md) · **통과 기준:** `uv run pytest tests/api/test_09_stream.py -q`

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **도메인 타입을 그대로 응답으로 내보내면 무엇이 문제인가?**
  - **답:** 내부 타입이 공개 API 계약이 되어 내부 필드 변경이 의도치 않게 데이터를 노출하거나 클라이언트를 깨뜨린다.
- **매핑에 없는 예외를 500으로 닫으면서 본문에 아무것도 싣지 않는 이유는 무엇인가?**
  - **답:** 현재 핸들러는 빈 본문을 반환하지 않는다. 상태 500과 일반화된 `internal_error` JSON 봉투를 보내되, 경로·SQL·자격 증명이 새지 않도록 원본 예외 메시지는 뺀다.
- **`import`만으로 부작용이 생기면 테스트에서 정확히 무엇이 불안정해지는가?**
  - **답:** 테스트 수집과 단순 import부터 실제 DB나 공급자에 의존해, 테스트가 통제된 의존성을 주입하기도 전에 실패할 수 있다.
- **CLI와 HTTP가 같은 팩토리를 쓰는 근거는 무엇인가?**
  - **답:** 현재 CLI와 HTTP 진입점은 하나의 팩토리를 공유하지 않는다. CLI가 검색·수집 함수를 직접 조립하므로, 동작 차이는 일치성 테스트나 향후 공통 조립 경계로 따로 막아야 한다.
- **요청 하나가 세션 하나를 소유한다는 규칙이 HTTP 경계에서 어떻게 유지되는가?**
  - **답:** 라우트는 주입된 서비스를 호출하고, 각 서비스 메서드가 전역이나 라우트 수준 세션을 공유하지 않고 해당 요청용 세션을 열고 닫는다.

## 이 모듈이 다음 모듈에 넘기는 것

M5까지로 **동작하는 서비스**가 완성됐다. HTTP로 부를 수 있고, CLI로 부를 수 있고, 어느 쪽이든 같은 근거를 돌려준다.

| M5가 만든 것 | 받는 곳 | 거기서 하는 일 |
|---|---|---|
| `/retrieve`, `/review` 엔드포인트 | **M6** | 데모 UI가 호출 |
| `EvidenceHit` 공개 스키마 | **M6** | 근거 카드 렌더링 |
| `/health` | **M7** | 컨테이너 헬스 체크 |
| OpenAPI 문서 | **M6, M7** | 클라이언트 계약 |
| `app/cli.py` 종료 코드 | **M7** | 배포 스크립트의 분기 |
| `create_app()` 팩토리 | **M7** | 컨테이너 진입점 |

다음 두 장은 성격이 다르다. **M6는 사람에게 보여주는 화면**을 만든다. 여기서 "근거를 원문과 대조할 수 있다"는 이 프로젝트의 핵심 주장이 눈에 보이는 형태가 된다. **M7은 배포**다. 컨테이너 패키징을 M5에서 일부러 미룬 이유가 거기서 드러난다.

## 기계 검증용 최종 기준본

위의 장들이 실제 빌드 경로이다. 아래 자동 생성 절은 M5.1 전에 통째로 작성하는 지름길이 아니라 `reference_revision`과 바이트 단위로 맞춘 최종 기준본이다. 모든 체크포인트를 마친 뒤 누적한 파일과 비교하고, 차이가 있으면 그 차이가 처음 생긴 체크포인트로 돌아가 고친다.

<!-- complete-files:start -->
## 완성 기준본 — 정식 구현 전체

아래 정식 경로를 직접 생성하거나 교체한다. `_mine.py` 또는 별도의 학습자용 복사 모듈을 만들지 않는다. 앞의 발췌 코드는 개별 결정을 설명하고, 이 절의 코드 블록은 체크포인트를 마친 뒤 대조할 완성 파일이다. 표시된 타입 어노테이션과 영어 주석을 유지하며 `pyproject.toml`을 Ruff 정책의 기준으로 사용한다.

### M5.1 — 완성 체크포인트

#### 생성 또는 교체 `app/api/__init__.py`

<!-- file: app/api/__init__.py -->
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

#### 생성 또는 교체 `app/api/schemas.py`

<!-- file: app/api/schemas.py -->
```python
"""Strict HTTP request and response schemas for the M5 API."""

from __future__ import annotations

from datetime import datetime
import json
import math
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictFloat,
    StrictInt,
    StrictStr,
    TypeAdapter,
)
from pydantic.functional_validators import field_validator, model_validator

from app.observability import Budget, RunReport, StepTrace, WorkflowNode
from app.retrieval import ChunkHit, RetrievalFilters
from app.workflow import NodeError, ProviderFailure, WorkflowReport

NonBlank = Annotated[StrictStr, Field(min_length=1)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
NonnegativeFloat = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
RunId = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
SourceSha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
JsonObject = dict[str, JsonValue]


class StrictApiModel(BaseModel):
    """Frozen, non-coercing base for every API body."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ValidationIssue(StrictApiModel):
    """One stable request-validation detail without echoing submitted values."""

    location: tuple[StrictStr | StrictInt, ...]
    message: NonBlank
    error_type: NonBlank


class ApiError(StrictApiModel):
    """Machine-readable HTTP failure shared by all routes."""

    code: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    message: NonBlank
    details: tuple[ValidationIssue, ...] = ()

    @field_validator("message", mode="after")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        """Reject error envelopes that cannot explain their failure."""
        if not value.strip():
            raise ValueError("error message must not be blank")
        return value


class ErrorResponse(StrictApiModel):
    """Top-level typed error envelope."""

    error: ApiError


class EvidenceHit(StrictApiModel):
    """One retrieved evidence unit with complete source identity."""

    chunk_id: PositiveInt
    doc_id: NonBlank
    item: NonBlank | None
    kind: Literal["text", "table"]
    citation: NonBlank
    start_char: NonnegativeInt
    end_char: PositiveInt
    source_sha256: SourceSha256
    body: NonBlank
    context_header: StrictStr
    score: Annotated[StrictFloat, Field(allow_inf_nan=False)]

    @field_validator("doc_id", "item", "citation", "body", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        """Reject whitespace-only evidence identity and content."""
        if value is not None and not value.strip():
            raise ValueError("evidence text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        """Require a nonempty half-open source span."""
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self

    @classmethod
    def from_chunk_hit(cls, hit: ChunkHit) -> Self:
        """Project the public evidence fields from one validated retrieval hit."""
        if not isinstance(hit, ChunkHit):
            raise TypeError("evidence responses require ChunkHit values")
        return cls(
            chunk_id=hit.chunk_id,
            doc_id=hit.doc_id,
            item=hit.item,
            kind=hit.kind,
            citation=hit.citation,
            start_char=hit.start_char,
            end_char=hit.end_char,
            source_sha256=hit.source_sha256,
            body=hit.body,
            context_header=hit.context_header,
            score=hit.score,
        )


class RetrieveRequest(StrictApiModel):
    """One bounded evidence retrieval request."""

    query: NonBlank
    k: Annotated[StrictInt, Field(gt=0, le=100)] = 5
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)

    @field_validator("query", mode="after")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        """Reject queries containing only whitespace."""
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class RetrieveResponse(StrictApiModel):
    """Ranked evidence for one query."""

    query: NonBlank
    results: tuple[EvidenceHit, ...]


class DocumentResource(StrictApiModel):
    """One ingested filing and its source identity."""

    doc_id: NonBlank
    ticker: NonBlank
    cik: PositiveInt
    fiscal_year: PositiveInt
    form: NonBlank
    filing_date: NonBlank
    report_period: NonBlank
    accession: NonBlank
    url: NonBlank
    parse_status: Literal["parsed", "needs_profile_update"]
    source_length: PositiveInt
    source_sha256: SourceSha256
    chunk_count: NonnegativeInt


class DocumentListResponse(StrictApiModel):
    """Deterministically ordered document resources."""

    documents: tuple[DocumentResource, ...]


class IngestRequest(StrictApiModel):
    """One explicit local manifest ingestion request."""

    manifest_path: NonBlank
    expected_documents: PositiveInt = 20
    chunk_batch_size: PositiveInt = 500

    @field_validator("manifest_path", mode="after")
    @classmethod
    def reject_blank_path(cls, value: str) -> str:
        """Reject an absent or whitespace-only manifest path."""
        if not value.strip():
            raise ValueError("manifest_path must not be blank")
        return value


class IngestResponse(StrictApiModel):
    """Committed corpus row counts from synchronous ingestion."""

    documents: NonnegativeInt
    chunks: NonnegativeInt


class ReviewRequest(StrictApiModel):
    """One synchronous evidence-checked workflow request."""

    query: NonBlank
    k: Annotated[StrictInt, Field(gt=0, le=100)] = 5
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    budget: Budget = Field(default_factory=Budget)
    max_context_chars: NonnegativeInt = 12_000

    @field_validator("query", mode="after")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        """Reject review requests without an actual question."""
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class BudgetLimitFailure(StrictApiModel):
    """A workflow node blocked by one exhausted cumulative resource."""

    code: Literal["budget_exceeded"] = "budget_exceeded"
    resource: Literal["iterations", "input_tokens", "output_tokens", "wall_clock_s"]
    limit: StrictInt | StrictFloat
    observed: StrictInt | StrictFloat
    blocked_node: WorkflowNode

    @model_validator(mode="after")
    def validate_values(self) -> Self:
        """Keep budget evidence finite and nonnegative."""
        if any(
            isinstance(value, float) and not math.isfinite(value)
            for value in (self.limit, self.observed)
        ):
            raise ValueError("budget values must be finite")
        if self.limit < 0 or self.observed < 0:
            raise ValueError("budget values must be nonnegative")
        return self


RunFailure = Annotated[
    BudgetLimitFailure | ProviderFailure | NodeError,
    Field(discriminator="code"),
]
_RUN_FAILURE_ADAPTER = TypeAdapter(RunFailure)


class RunResponse(StrictApiModel):
    """One completed workflow run or its structured terminal failure."""

    run_id: RunId
    status: Literal["ok", "budget_exceeded", "schema_rejected", "error"]
    iterations: NonnegativeInt
    total_requests: NonnegativeInt
    total_input_tokens: NonnegativeInt
    total_output_tokens: NonnegativeInt
    total_time_seconds: NonnegativeFloat
    system_prompt: NonBlank
    node_path: tuple[WorkflowNode, ...]
    report: WorkflowReport | None
    failure: RunFailure | None

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        """Keep successful reports and terminal failures mutually exclusive."""
        if self.status == "ok":
            if self.report is None or self.failure is not None:
                raise ValueError("successful runs require only a workflow report")
        elif self.failure is None or self.report is not None:
            raise ValueError("failed runs require only a typed failure")
        return self

    @classmethod
    def from_run_report(cls, run: RunReport) -> Self:
        """Validate an observability report into its public resource shape."""
        if not isinstance(run, RunReport):
            raise TypeError("run responses require a RunReport")
        payload = run.report
        report: WorkflowReport | None = None
        failure: RunFailure | None = None
        if run.status == "ok":
            if payload is None:
                raise ValueError("successful run report payload is missing")
            report = WorkflowReport.model_validate_json(
                json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
            )
        else:
            if payload is None:
                raise ValueError("failed run report payload is missing")
            raw_failure = payload.get("failure", payload.get("reason"))
            if raw_failure is None:
                raise ValueError("failed run report has no typed failure")
            failure = _RUN_FAILURE_ADAPTER.validate_json(
                json.dumps(raw_failure, allow_nan=False, separators=(",", ":"), sort_keys=True)
            )
        return cls(
            run_id=run.run_id,
            status=run.status,
            iterations=run.iterations,
            total_requests=run.total_requests,
            total_input_tokens=run.total_input_tokens,
            total_output_tokens=run.total_output_tokens,
            total_time_seconds=run.total_time_seconds,
            system_prompt=run.system_prompt,
            node_path=run.node_path,
            report=report,
            failure=failure,
        )


class StreamNodeEvent(StrictApiModel):
    """One completed workflow node reported while a streamed review is running."""

    node: WorkflowNode
    evidence_count: NonnegativeInt
    relevant_count: NonnegativeInt
    step_count: NonnegativeInt


class TraceListResponse(StrictApiModel):
    """Ordered raw provider traces for one persisted run."""

    run_id: RunId
    traces: tuple[StepTrace, ...]

    @model_validator(mode="after")
    def validate_trace_order(self) -> Self:
        """Require trace steps to be contiguous and start at one."""
        expected = tuple(range(1, len(self.traces) + 1))
        if tuple(trace.step for trace in self.traces) != expected:
            raise ValueError("trace steps must be contiguous and start at 1")
        return self


class EvalResultResource(StrictApiModel):
    """One persisted retrieval evaluation result."""

    result_id: PositiveInt
    suite: NonBlank
    config: JsonObject
    metrics: dict[NonBlank, StrictFloat]
    raw_artifact_path: NonBlank
    created_at: datetime

    @field_validator("suite", "raw_artifact_path", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject evaluation identity fields containing only whitespace."""
        if not value.strip():
            raise ValueError("evaluation text must not be blank")
        return value

    @field_validator("metrics", mode="after")
    @classmethod
    def validate_metrics(cls, values: dict[str, float]) -> dict[str, float]:
        """Reject blank metric names and nonfinite values."""
        if any(not key.strip() for key in values):
            raise ValueError("metric names must not be blank")
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError("metric values must be finite")
        return values


class EvalListResponse(StrictApiModel):
    """Newest persisted evaluation resources first."""

    results: tuple[EvalResultResource, ...]
```

#### 생성 또는 교체 `app/api/deps.py`

<!-- file: app/api/deps.py -->
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
from app.workflow import NodeObserver


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

#### 생성 또는 교체 `app/api/errors.py`

<!-- file: app/api/errors.py -->
```python
"""Stable typed error handling for malformed and failed API requests."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas import ApiError, ErrorResponse, ValidationIssue


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

#### 생성 또는 교체 `app/api/routes/__init__.py`

<!-- file: app/api/routes/__init__.py -->
```python
"""Resource-oriented M5 route collection."""

from fastapi import APIRouter

from app.api.routes import documents, eval, ingest, retrieve, review, runs, stream, traces

api_router = APIRouter()
for module in (retrieve, documents, ingest, review, stream, runs, traces, eval):
    api_router.include_router(module.router)

__all__ = ["api_router"]
```

#### 생성 또는 교체 `app/api/routes/documents.py`

<!-- file: app/api/routes/documents.py -->
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

#### 생성 또는 교체 `app/api/routes/eval.py`

<!-- file: app/api/routes/eval.py -->
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

#### 생성 또는 교체 `app/api/routes/ingest.py`

<!-- file: app/api/routes/ingest.py -->
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

#### 생성 또는 교체 `app/api/routes/retrieve.py`

<!-- file: app/api/routes/retrieve.py -->
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

#### 생성 또는 교체 `app/api/routes/review.py`

<!-- file: app/api/routes/review.py -->
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

#### 생성 또는 교체 `app/api/routes/runs.py`

<!-- file: app/api/routes/runs.py -->
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

#### 생성 또는 교체 `app/api/routes/traces.py`

<!-- file: app/api/routes/traces.py -->
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

#### 생성 또는 교체 `app/api/app.py`

<!-- file: app/api/app.py -->
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

체크포인트를 실행한다.

```bash
uv run pytest tests/api/test_01_schemas.py tests/api/test_02_errors.py tests/api/test_03_resources.py tests/api/test_04_operations.py tests/api/test_05_routes.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M5.2 — 완성 체크포인트

#### 생성 또는 교체 `app/config.py`

<!-- file: app/config.py -->
```python
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LexicalRanker = Literal["ts_rank_cd", "bm25"]
BM25Idf = Literal["lucene", "robertson"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://filing:filing@localhost:5432/filing"
    corpus_dir: Path = Path("data/corpus")
    embedding_provider: Literal["openai", "deterministic", "sbert"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    # Local sentence-transformer used when embedding_provider is "sbert". The
    # default produces exactly 384 dimensions, matching embed_dim and the
    # database column, so no migration is needed to switch.
    sbert_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embed_dim: Literal[384] = 384
    embedding_batch_size: int = Field(default=128, gt=0, le=2048)
    openai_api_key: SecretStr | None = None
    lexical_ranker: LexicalRanker = "ts_rank_cd"
    # The lexical index is built with the "english" text-search configuration, so a
    # Korean query produces no lexical candidates and hybrid fusion silently degrades
    # to the vector arm. Enabling this makes retrieve() skip the lexical component for
    # a Korean query instead, which is observable in ComponentRankings. Off by default:
    # M8 measures the collapse before changing the shipped query path.
    query_language_routing: bool = False
    bm25_k1: float = Field(default=1.2, gt=0)
    bm25_b: float = Field(default=0.75, ge=0, le=1)
    bm25_idf: BM25Idf = "lucene"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

#### 생성 또는 교체 `app/api/runtime.py`

<!-- file: app/api/runtime.py -->
```python
"""Production database composition for the synchronous M5 HTTP resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
import json
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from openai import OpenAIError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.deps import ApiServices
from app.api.errors import ApiProblemError, bad_request
from app.api.schemas import (
    DocumentResource,
    EvalResultResource,
    IngestRequest,
    RetrieveRequest,
    ReviewRequest,
)
from app.db.bootstrap import bootstrap_schema
from app.db.models import Chunk, Document, EvalResult, Run, Trace
from app.db.session import Session, engine
from app.ingestion.seed import SeedResult, persist_seed_batch, prepare_seed_batch
from app.llm import LLMProvider, ProviderBudget
from app.observability import RunReport, StepTrace, persist_run_report
from app.retrieval import (
    ChunkHit,
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    RetrievalFilters,
    RetrievalResult,
    retrieve,
)
from app.workflow import NodeObserver, WorkflowRequest, run_workflow


class SessionFactory(Protocol):
    """Build one caller-owned async session context."""

    def __call__(self) -> AsyncSession: ...


class RetrievalService(Protocol):
    """M2 retrieval call shape used by both retrieve and review resources."""

    def __call__(
        self,
        session: AsyncSession,
        query: str,
        *,
        provider: EmbeddingProvider | None,
        k: int,
        filters: RetrievalFilters,
    ) -> Awaitable[RetrievalResult]: ...


class WorkflowService(Protocol):
    """M4 workflow call shape used by the review resource."""

    def __call__(
        self,
        request: WorkflowRequest,
        *,
        retriever: Callable[
            [str, int, RetrievalFilters],
            Awaitable[RetrievalResult | Sequence[ChunkHit]],
        ],
        provider: LLMProvider,
        on_node: NodeObserver | None = None,
    ) -> Awaitable[RunReport]: ...


class RunPersister(Protocol):
    """M4 persistence call shape used after a workflow completes."""

    def __call__(
        self,
        session: AsyncSession,
        report: RunReport,
        *,
        secret_values: Iterable[str],
    ) -> Awaitable[Run]: ...


def _unavailable(code: str, message: str) -> ApiProblemError:
    return ApiProblemError(status_code=503, code=code, message=message)


def _document_resource(document: Document, chunk_count: int) -> DocumentResource:
    return DocumentResource(
        doc_id=document.doc_id,
        ticker=document.ticker,
        cik=document.cik,
        fiscal_year=document.fiscal_year,
        form=document.form,
        filing_date=document.filing_date,
        report_period=document.report_period,
        accession=document.accession,
        url=document.url,
        parse_status=document.parse_status,
        source_length=document.source_length,
        source_sha256=document.source_sha256,
        chunk_count=chunk_count,
    )


def _step_trace(trace: Trace) -> StepTrace:
    return StepTrace(
        step=trace.step,
        node=trace.node,
        model_name=trace.model_name,
        api_url=trace.api_url,
        input_tokens=trace.input_tokens,
        output_tokens=trace.output_tokens,
        request_time_ms=trace.request_time_ms,
        llm_output=trace.llm_output,
        retries=trace.retries,
        error=trace.error,
    )


def _run_report(run: Run, traces: Sequence[Trace]) -> RunReport:
    return RunReport(
        run_id=run.run_id,
        status=run.status,
        iterations=run.iterations,
        total_requests=run.total_requests,
        total_input_tokens=run.total_input_tokens,
        total_output_tokens=run.total_output_tokens,
        total_time_seconds=run.total_time_seconds,
        system_prompt=run.system_prompt,
        node_path=tuple(run.node_path),
        report=run.report,
        steps=tuple(_step_trace(trace) for trace in traces),
    )


class RuntimeApiServices(ApiServices):
    """Compose API resources over one session per synchronous request.

    Retrieval defaults to the configured embedding provider. Review is fail-closed until
    an LLM provider and its explicit budget are injected; the container therefore cannot
    make a paid model call from environment defaults alone.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory = Session,
        database_engine: AsyncEngine = engine,
        embedding_provider: EmbeddingProvider | None = None,
        llm_provider: LLMProvider | None = None,
        provider_budget: ProviderBudget | None = None,
        retrieval_service: RetrievalService = retrieve,
        workflow_service: WorkflowService = run_workflow,
        run_persister: RunPersister = persist_run_report,
        run_id_factory: Callable[[], str] | None = None,
        secret_values: Iterable[str] = (),
    ) -> None:
        if (llm_provider is None) != (provider_budget is None):
            raise ValueError("llm_provider and provider_budget must be configured together")
        self._session_factory = session_factory
        self._database_engine = database_engine
        self._embedding_provider = (
            DeterministicEmbeddingProvider() if embedding_provider is None else embedding_provider
        )
        self._llm_provider = llm_provider
        self._provider_budget = provider_budget
        self._retrieval_service = retrieval_service
        self._workflow_service = workflow_service
        self._run_persister = run_persister
        self._run_id_factory = run_id_factory or (lambda: f"run-{uuid4().hex}")
        self._secret_values = tuple(secret_values)

    async def _retrieve_with_session(
        self,
        session: AsyncSession,
        query: str,
        k: int,
        filters: RetrievalFilters,
    ) -> RetrievalResult:
        return await self._retrieval_service(
            session,
            query,
            provider=self._embedding_provider,
            k=k,
            filters=filters,
        )

    async def retrieve(self, request: RetrieveRequest) -> RetrievalResult:
        """Call the M2 service through one request-owned database session."""
        try:
            async with self._session_factory() as session:
                return await self._retrieve_with_session(
                    session,
                    request.query,
                    request.k,
                    request.filters,
                )
        except OpenAIError as error:
            raise _unavailable(
                "provider_unavailable",
                f"Embedding provider is unavailable ({type(error).__name__}).",
            ) from error
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def list_documents(self) -> Sequence[DocumentResource]:
        """Return filing resources with deterministic chunk counts."""
        statement = (
            select(Document, func.count(Chunk.id).label("chunk_count"))
            .outerjoin(Chunk, Chunk.doc_id == Document.doc_id)
            .group_by(Document.doc_id)
            .order_by(Document.ticker, Document.fiscal_year, Document.doc_id)
        )
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(statement)).all()
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error
        return tuple(_document_resource(document, count) for document, count in rows)

    async def ingest(self, request: IngestRequest) -> SeedResult:
        """Prepare locally, bootstrap explicitly, and preserve the M1 atomic upsert."""
        path = Path(request.manifest_path)
        if not path.is_file():
            raise bad_request("manifest_not_found", f"Manifest file was not found: {path}")
        try:
            batch = prepare_seed_batch(path, expected_documents=request.expected_documents)
        except json.JSONDecodeError as error:
            raise bad_request(
                "invalid_manifest_json",
                f"Manifest is not valid JSON at line {error.lineno} column {error.colno}.",
            ) from error
        except UnicodeDecodeError as error:
            raise bad_request(
                "invalid_manifest_encoding",
                "Manifest must be UTF-8 text.",
            ) from error
        except FileNotFoundError as error:
            raise bad_request(
                "corpus_file_not_found",
                f"Corpus file was not found: {error.filename}",
            ) from error
        except ValueError as error:
            raise bad_request("invalid_manifest", str(error)) from error

        try:
            await bootstrap_schema(self._database_engine)
            async with self._session_factory() as session:
                return await persist_seed_batch(
                    session,
                    batch,
                    chunk_batch_size=request.chunk_batch_size,
                )
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def review(self, request: ReviewRequest) -> RunReport:
        """Call M4 over the same M2 seam and persist its structured terminal report."""
        return await self._review(request, on_node=None)

    async def review_stream(
        self,
        request: ReviewRequest,
        on_node: NodeObserver,
    ) -> RunReport:
        """Run one reviewed workflow while reporting each completed node."""
        return await self._review(request, on_node=on_node)

    async def _review(
        self,
        request: ReviewRequest,
        *,
        on_node: NodeObserver | None,
    ) -> RunReport:
        if self._llm_provider is None or self._provider_budget is None:
            raise _unavailable(
                "provider_unavailable",
                "Review requires an explicitly configured LLM provider and budget.",
            )
        workflow_request = WorkflowRequest(
            run_id=self._run_id_factory(),
            query=request.query,
            k=request.k,
            filters=request.filters,
            budget=request.budget,
            provider_budget=self._provider_budget,
            max_context_chars=request.max_context_chars,
        )
        try:
            async with self._session_factory() as session:

                async def retrieve_for_workflow(
                    query: str,
                    k: int,
                    filters: RetrievalFilters,
                ) -> RetrievalResult:
                    return await self._retrieve_with_session(session, query, k, filters)

                report = await self._workflow_service(
                    workflow_request,
                    retriever=retrieve_for_workflow,
                    provider=self._llm_provider,
                    on_node=on_node,
                )
                if session.in_transaction():
                    await session.rollback()
                async with session.begin():
                    await self._run_persister(
                        session,
                        report,
                        secret_values=self._secret_values,
                    )
                return report
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def _trace_rows(self, session: AsyncSession, run_id: str) -> tuple[Trace, ...]:
        rows = await session.scalars(
            select(Trace).where(Trace.run_id == run_id).order_by(Trace.step)
        )
        return tuple(rows)

    async def get_run(self, run_id: str) -> RunReport | None:
        """Load one run and its ordered traces without executing workflow code."""
        try:
            async with self._session_factory() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    return None
                traces = await self._trace_rows(session, run_id)
                return _run_report(run, traces)
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def get_traces(self, run_id: str) -> Sequence[StepTrace] | None:
        """Load trace resources only when their parent run exists."""
        try:
            async with self._session_factory() as session:
                if await session.get(Run, run_id) is None:
                    return None
                traces = await self._trace_rows(session, run_id)
                return tuple(_step_trace(trace) for trace in traces)
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error

    async def list_eval_results(self, limit: int) -> Sequence[EvalResultResource]:
        """Load newest evaluation records through their strict public schema."""
        statement = select(EvalResult).order_by(EvalResult.created_at.desc(), EvalResult.id.desc())
        try:
            async with self._session_factory() as session:
                rows = tuple(await session.scalars(statement.limit(limit)))
        except SQLAlchemyError as error:
            raise _unavailable(
                "database_unavailable",
                f"Database is unavailable ({type(error).__name__}).",
            ) from error
        return tuple(
            EvalResultResource(
                result_id=row.id,
                suite=row.suite,
                config=row.config,
                metrics={name: float(value) for name, value in row.metrics.items()},
                raw_artifact_path=row.raw_artifact_path,
                created_at=row.created_at,
            )
            for row in rows
        )
```

#### 생성 또는 교체 `app/main.py`

<!-- file: app/main.py -->
```python
"""FastAPI runtime entrypoint without import-time database or provider calls."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from app.api import ApiServices, RuntimeApiServices, create_api_app


class HealthResponse(BaseModel):
    """Stable process-liveness response used by container health checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"


def create_app(services: ApiServices | None = None) -> FastAPI:
    """Build one API instance with an injectable database-backed service boundary."""
    active_services = RuntimeApiServices() if services is None else services
    application = create_api_app(active_services)

    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["runtime"],
        operation_id="runtime_health",
    )
    async def health() -> HealthResponse:
        return HealthResponse()

    return application


app = create_app()
```

#### 생성 또는 교체 `app/cli.py`

<!-- file: app/cli.py -->
```python
"""Deterministic command-line entrypoints for retrieval, ingestion, and serving."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
from enum import IntEnum
import json
from pathlib import Path
import sys
from typing import Literal, TextIO

from openai import OpenAIError
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, get_settings
from app.retrieval.types import ChunkHit, RetrievalFilters

ProviderName = Literal["deterministic", "openai"]


class ExitCode(IntEnum):
    """Stable process exit codes for expected CLI outcomes."""

    OK = 0
    INVALID_INPUT = 2
    INVALID_FILE = 3
    UNAVAILABLE = 4


class CliError(Exception):
    """An expected CLI failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, exit_code: ExitCode) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


class CliArgumentParser(argparse.ArgumentParser):
    """Convert argparse failures into the same JSON envelope as runtime failures."""

    def error(self, message: str) -> None:
        """Raise a structured CliError instead of printing usage and exiting."""
        raise CliError("invalid_arguments", message, ExitCode.INVALID_INPUT)


def _add_retrieve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", required=True, help="Nonblank retrieval query.")
    parser.add_argument("-k", type=int, default=5, help="Number of fused hits to return.")
    parser.add_argument(
        "--candidate-k",
        type=int,
        help="Candidates per retrieval component; defaults to max(20, 4 * k).",
    )
    parser.add_argument(
        "--provider",
        choices=("deterministic", "openai"),
        default="deterministic",
        help="Embedding provider; deterministic is the offline default.",
    )
    parser.add_argument(
        "--embed-missing",
        action="store_true",
        help="Fill null chunk embeddings before retrieval.",
    )
    parser.add_argument("--doc-id", action="append", default=[], help="Exact document filter.")
    parser.add_argument("--ticker", action="append", default=[], help="Exact ticker filter.")
    parser.add_argument(
        "--fiscal-year",
        action="append",
        default=[],
        type=int,
        help="Exact fiscal-year filter.",
    )
    parser.add_argument("--form", action="append", default=[], help="Exact filing-form filter.")
    parser.add_argument("--item", action="append", default=[], help="Exact filing-item filter.")
    parser.add_argument(
        "--kind",
        action="append",
        default=[],
        choices=("text", "table"),
        help="Exact chunk-kind filter.",
    )


def _add_ingest_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to the corpus manifest JSON file.",
    )
    parser.add_argument(
        "--expected-documents",
        type=int,
        default=20,
        help="Fail unless the manifest contains this many documents.",
    )
    parser.add_argument(
        "--chunk-batch-size",
        type=int,
        default=500,
        help="Number of chunk rows per PostgreSQL upsert statement.",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create missing tables before ingestion; existing tables are not migrated.",
    )


def _add_serve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="Interface address to bind.")
    parser.add_argument("--port", type=int, default=8000, help="TCP port to bind.")
    parser.add_argument("--workers", type=int, default=1, help="Number of Uvicorn workers.")
    parser.add_argument(
        "--log-level",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        default="info",
        help="Uvicorn log level.",
    )


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse one explicit runtime command without opening files or services."""
    parser = CliArgumentParser(prog="docreview", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    retrieve = subparsers.add_parser("retrieve", help="Retrieve cited filing evidence.")
    ingest = subparsers.add_parser("ingest", help="Upsert one local corpus manifest.")
    serve = subparsers.add_parser("serve", help="Run the FastAPI application with Uvicorn.")
    _add_retrieve_arguments(retrieve)
    _add_ingest_arguments(ingest)
    _add_serve_arguments(serve)
    return parser.parse_args(argv)


def _validate_arguments(args: argparse.Namespace) -> None:
    if args.command == "retrieve":
        if not args.query.strip():
            raise CliError(
                "empty_query",
                "query must not be blank",
                ExitCode.INVALID_INPUT,
            )
        if args.k <= 0:
            raise CliError("invalid_k", "k must be positive", ExitCode.INVALID_INPUT)
        if args.candidate_k is not None and args.candidate_k < args.k:
            raise CliError(
                "invalid_candidate_k",
                "candidate-k must be at least k",
                ExitCode.INVALID_INPUT,
            )
    elif args.command == "ingest":
        if args.expected_documents <= 0:
            raise CliError(
                "invalid_expected_documents",
                "expected-documents must be positive",
                ExitCode.INVALID_INPUT,
            )
        if args.chunk_batch_size <= 0:
            raise CliError(
                "invalid_chunk_batch_size",
                "chunk-batch-size must be positive",
                ExitCode.INVALID_INPUT,
            )
    elif args.command == "serve":
        if not args.host.strip():
            raise CliError("invalid_host", "host must not be blank", ExitCode.INVALID_INPUT)
        if not 1 <= args.port <= 65_535:
            raise CliError(
                "invalid_port",
                "port must be between 1 and 65535",
                ExitCode.INVALID_INPUT,
            )
        if args.workers <= 0:
            raise CliError(
                "invalid_workers",
                "workers must be positive",
                ExitCode.INVALID_INPUT,
            )


def _provider_settings(settings: Settings, provider: ProviderName) -> Settings:
    return settings.model_copy(update={"embedding_provider": provider})


def _filters(args: argparse.Namespace) -> RetrievalFilters:
    return RetrievalFilters(
        doc_ids=tuple(args.doc_id),
        tickers=tuple(args.ticker),
        fiscal_years=tuple(args.fiscal_year),
        forms=tuple(args.form),
        items=tuple(args.item),
        kinds=tuple(args.kind),
    )


def _evidence_payload(hit: ChunkHit) -> dict[str, object]:
    """Project the same public evidence fields exposed by the HTTP boundary."""
    from app.api.schemas import EvidenceHit

    return EvidenceHit.from_chunk_hit(hit).model_dump(mode="json")


async def _retrieve(args: argparse.Namespace) -> dict[str, object]:
    from app.db.session import Session
    from app.retrieval.embeddings import embed_missing_chunks, get_embedding_provider
    from app.retrieval.service import retrieve

    settings = _provider_settings(get_settings(), args.provider)
    provider = get_embedding_provider(settings)
    async with Session() as session:
        backfill = None
        if args.embed_missing:
            backfill = await embed_missing_chunks(session, provider)
        result = await retrieve(
            session,
            args.query,
            provider=provider,
            k=args.k,
            candidate_k=args.candidate_k,
            filters=_filters(args),
        )
    return {
        "status": "ok",
        "command": "retrieve",
        "query": args.query,
        "provider": settings.embedding_provider,
        "backfill": asdict(backfill) if backfill is not None else None,
        "hits": [_evidence_payload(hit) for hit in result.hits],
        "component_rankings": result.component_rankings.model_dump(mode="json"),
    }


def _checked_manifest(path: Path) -> Path:
    if not path.is_file():
        raise CliError(
            "manifest_not_found",
            f"manifest file does not exist: {path}",
            ExitCode.INVALID_FILE,
        )
    return path


async def _ingest(args: argparse.Namespace) -> dict[str, object]:
    from app.db.bootstrap import bootstrap_schema
    from app.db.session import Session, engine
    from app.ingestion.seed import persist_seed_batch, prepare_seed_batch

    manifest = _checked_manifest(args.manifest)
    try:
        batch = prepare_seed_batch(
            manifest,
            expected_documents=args.expected_documents,
        )
    except json.JSONDecodeError as error:
        raise CliError(
            "invalid_manifest_json",
            f"manifest is not valid JSON at line {error.lineno} column {error.colno}",
            ExitCode.INVALID_FILE,
        ) from error
    except UnicodeDecodeError as error:
        raise CliError(
            "invalid_manifest_encoding",
            "manifest must be UTF-8 text",
            ExitCode.INVALID_FILE,
        ) from error
    except FileNotFoundError as error:
        raise CliError(
            "corpus_file_not_found",
            f"corpus file does not exist: {error.filename}",
            ExitCode.INVALID_FILE,
        ) from error
    except ValueError as error:
        raise CliError(
            "invalid_manifest",
            str(error),
            ExitCode.INVALID_FILE,
        ) from error

    if args.create_schema:
        await bootstrap_schema(engine)
    async with Session() as session:
        result = await persist_seed_batch(
            session,
            batch,
            chunk_batch_size=args.chunk_batch_size,
        )
    return {
        "status": "ok",
        "command": "ingest",
        "manifest": str(manifest),
        "documents": result.documents,
        "chunks": result.chunks,
    }


async def _run_data_command(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "retrieve":
        return await _retrieve(args)
    if args.command == "ingest":
        return await _ingest(args)
    raise AssertionError(f"unsupported data command: {args.command}")


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level=args.log_level,
    )


def _failure_payload(error: CliError) -> dict[str, object]:
    return {
        "status": "error",
        "error": {
            "code": error.code,
            "message": error.message,
        },
    }


def _write_json(value: dict[str, object], stream: TextIO) -> None:
    json.dump(value, stream, ensure_ascii=False, sort_keys=True)
    stream.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return a stable process exit code."""
    try:
        args = arguments(argv)
        _validate_arguments(args)
        if args.command == "serve":
            _serve(args)
            return ExitCode.OK
        payload = asyncio.run(_run_data_command(args))
    except CliError as error:
        _write_json(_failure_payload(error), sys.stderr)
        return error.exit_code
    except OpenAIError as error:
        failure = CliError(
            "provider_unavailable",
            f"embedding provider is unavailable ({type(error).__name__})",
            ExitCode.UNAVAILABLE,
        )
        _write_json(_failure_payload(failure), sys.stderr)
        return failure.exit_code
    except SQLAlchemyError as error:
        failure = CliError(
            "database_unavailable",
            f"database is unavailable ({type(error).__name__})",
            ExitCode.UNAVAILABLE,
        )
        _write_json(_failure_payload(failure), sys.stderr)
        return failure.exit_code

    _write_json(payload, sys.stdout)
    return ExitCode.OK


def entrypoint() -> None:
    """Run the installed console script without printing a Python traceback."""
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
```

체크포인트를 실행한다.

```bash
uv run pytest tests/api/test_06_cli.py tests/api/test_07_runtime.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M5.3 — 완성 체크포인트

체크포인트를 실행한다.

```bash
uv run pytest tests/api/test_08_integration.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M5.4 — 완성 체크포인트

#### 생성 또는 교체 `app/api/routes/stream.py`

<!-- file: app/api/routes/stream.py -->
```python
"""Server-sent-events streaming for the evidence-review workflow."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import contextlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import ApiServices, get_api_services
from app.api.schemas import ReviewRequest, RunResponse, StreamNodeEvent
from app.observability import WorkflowNode
from app.workflow import WorkflowState

router = APIRouter(tags=["review"])
Services = Annotated[ApiServices, Depends(get_api_services)]

type _Event = tuple[str, str]


def _sse(event: str, data: str) -> str:
    """Format one server-sent event with a named type and single-line JSON data."""
    return f"event: {event}\ndata: {data}\n\n"


@router.post("/review/stream")
async def review_stream(request: ReviewRequest, services: Services) -> StreamingResponse:
    """Stream node completions while one guarded workflow runs, then its terminal run."""
    queue: asyncio.Queue[_Event | None] = asyncio.Queue()

    async def on_node(node: WorkflowNode, state: WorkflowState) -> None:
        event = StreamNodeEvent(
            node=node,
            evidence_count=len(state.evidence),
            relevant_count=len(state.relevant_chunk_ids),
            step_count=len(state.steps),
        )
        await queue.put(("node", event.model_dump_json()))

    async def run_review() -> None:
        try:
            report = await services.review_stream(request, on_node)
            payload = RunResponse.from_run_report(report).model_dump_json()
            await queue.put(("report", payload))
        except Exception as error:
            # str(error) can carry secrets (a SQLAlchemyError embeds the connection
            # string), so only the exception's class name leaves the process.
            payload = json.dumps({"error_type": type(error).__name__})
            await queue.put(("error", payload))
        finally:
            await queue.put(None)

    review_task = asyncio.create_task(run_review())

    async def events() -> AsyncIterator[str]:
        try:
            while (item := await queue.get()) is not None:
                yield _sse(*item)
            yield _sse("done", "{}")
        finally:
            # A disconnected client cancels the generator; stop the workflow with it.
            review_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await review_task

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store"},
    )
```

체크포인트를 실행한다.

```bash
uv run pytest tests/api/test_09_stream.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

<!-- complete-files:end -->
