# M5.1 튜토리얼 1 — 라우트는 도메인을 몰라야 한다

M5는 라우트가 하는 일을 세 가지로 제한한다.

1. HTTP 요청을 **검증**한다. 2. **주입받은 서비스 메서드 하나**를 부른다. 3. 도메인 결과를 엄격한 리소스로 **투영**한다.

라우트는 검색이 어떤 경로로 실행되는지도, 워크플로 노드가 몇 개인지도 참조하지 않는다.

**선행 조건:** M4가 끝나 `uv run pytest tests/workflow -q`가 통과해야 한다.

### 이 경계가 없으면

전송 계층과 도메인이 섞이면 검색 파라미터의 기본값이 요청 파싱 코드에 들어가고, 라우트 핸들러가 워크플로 제어 흐름을 참조하게 되며, 예외 처리가 HTTP 상태 코드와 도메인 실패를 한 함수에서 다루게 된다.

**이 상태에서는 검색 로직을 검증하려면 HTTP 클라이언트를 띄워야 하고, 실패가 발생해도 전송 오류인지 도메인 오류인지 응답만으로 구분할 수 없다.**

경계를 유지하면 전송 계층을 교체할 수 있다. gRPC를 추가하거나 큐 워커에서 호출해도 `ApiServices` 아래 계층은 수정하지 않는다.

### 응답 스키마를 따로 두는 이유

`EvidenceHit`은 M2의 `ChunkHit`과 필드가 대부분 겹친다. 그래도 `ChunkHit`을 그대로 반환하지 않는다.

**내부 모델을 응답으로 내보내면 그 모델의 필드 구성이 그대로 API 계약이 된다.** `ChunkHit`에 디버깅용 필드를 추가하면 그 값이 API 응답에 함께 나가고, 필드를 제거하면 그 응답에 의존하던 클라이언트가 깨진다.

그래서 투영 계층을 둔다. 응답에 `index_text`를 넣지 않은 것도 같은 판단이다. `body`와 `context_header`로 같은 내용을 표현할 수 있고, 내부 색인 방식은 클라이언트가 알 필요가 없다.

### 무엇을 작성하고 어디를 직접 구현할까

이 문서는 `app/api/schemas.py` 한 파일을 다섯 단계로 작성한다. 라우트와 오류 처리는 다음 문서에서 만든다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 값 어휘와 `StrictApiModel` | **설정 스키마 정의** | API 경계의 엄격도 |
| `ApiError`·`ErrorResponse` | **모델 선언 작성** | 실패에 하나의 봉투를 주는 이유 |
| `EvidenceHit` | **필드 매핑 작성 후 경계 변환 검토** | 내부 모델과 공개 리소스의 차이 |
| 요청·응답 쌍들 | **모델 선언 작성** | 각 오퍼레이션의 입출력 계약 |
| `RunResponse` | 판별 합집합을 **직접 구현** | 성공과 실패를 한 응답에 담는 법 |

### 1. API 경계의 엄격도

#### `app/api/schemas.py` 생성 — 모듈 헤더와 값 어휘

**학습 행동 — 설정 스키마 정의:** 이 파일이 M2와 M4의 타입을 import하지 않는다는 점을 확인하며 작성한다.

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

```

**코드에서 꼭 볼 것**

- 도메인 모듈을 import하지 않는다. **API 스키마가 도메인 타입에 의존하면 도메인 타입을 수정할 때마다 공개 계약이 함께 바뀐다.**
- 값 별칭이 M2, M4와 이름은 같지만 이 파일에서 **다시 정의**된다. 같은 제약을 두 번 적는 대신 두 계층을 독립적으로 바꿀 수 있게 된다.

#### `app/api/schemas.py` 확장 — 오류 봉투

**학습 행동 — 모델 선언 작성:** 모든 오류 응답이 같은 구조를 갖게 하는 이유를 확인한다.

<!-- src: app/api/schemas.py::StrictApiModel,ErrorResponse -->
```python
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
```

**코드에서 꼭 볼 것**

- 모든 실패가 `ErrorResponse` 한 형태로 나간다. 클라이언트가 상태 코드마다 다른 파싱 코드를 두지 않아도 된다.
- `ValidationIssue`는 필드 경로와 메시지를 담는다. FastAPI 기본 오류를 그대로 내보내면 내부 타입 이름이 응답에 포함된다.
- `code`는 문자열 식별자다. 메시지 문구는 바뀔 수 있지만 코드는 계약의 일부로 유지한다.

### 2. 내부 모델과 공개 리소스의 차이

#### `app/api/schemas.py` 확장 — 근거 hit와 검색 오퍼레이션

**학습 행동 — 필드 매핑 작성 후 경계 변환 검토:** `EvidenceHit`과 M2의 `ChunkHit`을 나란히 놓고 어떤 필드가 빠졌는지 찾는다.

<!-- src: app/api/schemas.py::EvidenceHit,RetrieveResponse -->
```python
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
```

**코드에서 꼭 볼 것**

- `index_text`가 없다. `body`와 `context_header`로 같은 내용을 구성할 수 있고, 내부 색인 방식은 응답에 필요하지 않다.
- 반면 `start_char`, `end_char`, `source_sha256`은 포함된다. M1.3의 출처 계약이 API 응답까지 이어지므로 클라이언트가 원문 구간을 직접 확인할 수 있다.
- `score`도 포함된다. **M2.7이 감춘 것은 단위가 서로 다른 구성 요소 점수이고, 융합 점수는 단위가 하나뿐이므로 다른 값과 혼동될 여지 없이 순위 근거로 쓸 수 있다.**

#### `app/api/schemas.py` 확장 — 문서·수집·검토 오퍼레이션

**학습 행동 — 모델 선언 작성:** 각 요청 모델이 어떤 한도를 함께 받는지 확인한다.

<!-- src: app/api/schemas.py::DocumentResource,ReviewRequest -->
```python
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
```

**코드에서 꼭 볼 것**

- `ReviewRequest`가 예산을 함께 받는다. 클라이언트가 워크플로 한도를 지정할 수 있고, 그 값은 스키마 검증을 거친다.
- `IngestRequest`는 `expected_documents`를 받는다. M1.4의 fail-closed 계약이 API 파라미터로 노출된다.

### 3. 성공과 실패를 한 응답에 담는다

#### `app/api/schemas.py` 확장 — 실행 응답

**학습 행동 — 판별 합집합 구현:** `RunFailure`를 무엇으로 판별하는지, `report`와 `failure`가 어떤 관계인지 확인한다.

<!-- src: app/api/schemas.py::BudgetLimitFailure,RunResponse -->
```python
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
```

**코드에서 꼭 볼 것**

- `_RUN_FAILURE_ADAPTER`는 모듈 수준의 `TypeAdapter`다. M3.1 로더와 같은 이유로 스키마 컴파일을 한 번만 수행한다.
- `RunResponse`는 M4의 네 종료 상태를 그대로 노출한다. **`budget_exceeded`는 서버가 처리에 실패한 상태가 아니라 정의된 종료 상태이므로, HTTP 500이 아니라 정상 응답으로 반환한다.**
- `report`와 `failure`는 배타적이다. M4.1의 `ProviderResult`가 세운 규칙을 API 경계에서 다시 강제한다.

#### `app/api/schemas.py` 완성 — 트레이스와 평가 리소스

**학습 행동 — 모델 선언 작성:** 트레이스를 API로 내보낼 때 어떤 필드가 빠지는지 확인한다.

<!-- src: app/api/schemas.py::TraceListResponse,EvalListResponse -->
```python
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

**코드에서 꼭 볼 것**

- 트레이스를 공개한다. 어떤 공급자 호출이 있었는지를 클라이언트가 확인할 수 있고, M4.2가 기록한 값이 여기서 사용된다.
- 평가 결과는 재실행 없이 조회한다. M3가 저장한 `eval_results`를 읽기만 한다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 모델과 연결해 설명해 본다.

- **내부 모델을 그대로 응답으로 쓰면 무엇이 계약이 되는가?**
  - **답:** 클라이언트에 보여 줄 의도가 없던 필드를 포함해 모든 내부 필드와 이후 모델 변경이 공개 API 계약이 된다.
- **`index_text`를 응답에서 빼는 이유는 무엇인가?**
  - **답:** `body`와 `context_header`로 재구성할 수 있어 중복이고, 내부 인덱싱 표현은 클라이언트가 알아야 할 계약이 아니기 때문이다.
- **M2.7이 구성 요소 점수를 감췄는데 융합 점수는 공개하는 이유는 무엇인가?**
  - **답:** 구성 요소 점수는 단위가 달라 오해하기 쉽지만, 하나의 융합 점수는 최종 순위를 직접 설명하기 때문이다.
- **`budget_exceeded`가 HTTP 500이 아닌 이유는 무엇인가?**
  - **답:** 예산 소진은 HTTP 서버의 고장이 아니라 예상하고 타입화한 정상 워크플로 종료 상태이기 때문이다.
- **API 스키마가 도메인 타입을 import하지 않는 이유는 무엇인가?**
  - **답:** 질문의 전제가 맞지 않는다. 요청·응답 모델이 `RetrievalFilters`, `Budget`, `WorkflowNode`, `WorkflowReport`, `StepTrace`를 직접 사용하므로 현재 전송 계약은 이 도메인 정의들과 결합돼 있다.

---

[모듈 개요](../03-build.md) · [다음: 오류와 의존성 →](02-errors-deps.md)
