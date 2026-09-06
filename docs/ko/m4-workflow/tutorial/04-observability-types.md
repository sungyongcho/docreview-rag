# M4.2 튜토리얼 4 — 워크플로를 짜기 전에 실패를 볼 수 있게 만든다

두 번째 방어선은 **관측**이다. 워크플로를 아직 만들지 않은 상태에서 관측 타입부터 작성한다.

**관측을 나중에 붙이면 실패 경로가 기록에서 빠진다.**

워크플로를 먼저 만들면 성공 경로가 먼저 완성되고, 오류 처리는 그 위에 `try/except`로 덧붙는다. 이 순서에서는 예산 초과나 공급자 실패가 로그 한 줄로 남고 구조화된 기록에는 들어가지 않는다. 그러면 특정 요청이 왜 실패했는지를 사후에 확인할 자료가 없다.

이 문서에는 검증 가능한 불변조건이 두 개 있고, 나머지는 전부 이 둘을 위해 존재한다. 첫째, **모든 종료 상태는 `RunReport`를 만든다.** 성공, 예산 소진, 스키마 거부, 오류가 전부 같은 기록 형태로 끝나므로 "기록이 없는 결과"라는 것이 존재하지 않는다. 둘째, **리포트의 모든 합계는 그 아래 트레이스에서 유도된다.** 그래서 리포트가 자신의 근거와 어긋나는 일이 구조적으로 불가능하다.

**선행 조건:** 튜토리얼 3의 `uv run pytest tests/workflow/test_02_provider.py -q`가 통과해야 한다.

### 실패도 출력이다

이 프로젝트에서 예산 소진과 스키마 거부는 버그가 아니라 정의된 종료 상태다.

```
ok                → completed normally
budget_exceeded   → stopped at the budget ceiling
schema_rejected   → model output did not match the schema
error             → any other failure
```

**네 상태 모두 `RunReport`를 만들고 기록 없이 종료되는 경로가 없으므로, 성공한 실행과 실패한 실행을 같은 형식으로 확인할 수 있다.**

예외를 던지고 끝나는 구현과 달리, 예산을 넘겼을 때 어디서 멈췄고 그때까지 무엇을 썼는지가 결과 객체에 남는다.

### 합계가 트레이스와 어긋나면 안 된다

`RunReport`의 총 토큰 수는 별도 카운터가 아니라 **`StepTrace` 목록에서 계산한다.**

**카운터를 따로 두면 트레이스를 남기지 않은 노드나 집계에서 빠진 재시도가 생겼을 때 리포트의 합계와 트레이스 기록이 달라지고, 둘 중 어느 쪽이 실제 사용량인지 판단할 근거가 없다.**

집계는 기반 데이터에서 유도한다. M1.4에서 `content_tsv`를 생성 열로 만든 것과 같은 원칙이다.

> **개념 — 검증기가 뒷받침하는 유도 집계**
>
> 헬퍼 함수에서 합계를 유도하는 것은 관례이고, 관례는 누군가 헬퍼를 우회하는 순간까지만 유효하다. 이 모듈은 두 번째 층을 더한다. 리포트 모델이 생성 시점에 모든 합계를 자기 트레이스와 다시 대조하므로, 카운터가 스텝과 어긋나는 리포트는 객체로 존재할 수 없다.
>
> 두 층의 역할은 다르다. 헬퍼는 정직한 경로를 편하게 만든다 — 트레이스를 넘기면 올바른 합계가 나온다. 검증기는 부정직한 경로를 불가능하게 만든다 — 잘못된 합계로 리포트를 직접 만들면 저장된 거짓 대신 검증 오류를 받는다. 커밋된 테스트가 정확히 이 우회를 검사한다. 100토큰짜리 트레이스 위에 입력 999토큰을 주장하는 수제 리포트는 생성 단계에서 거부된다.

### 예산은 노드가 돌기 *전에* 검사한다

예산 가드는 노드를 실행한 **뒤가 아니라 앞에서** 실행된다. 지금까지 쓴 토큰과 시간으로 다음 노드를 실행할 여유가 있는지 판정한다. 가드가 보는 자원은 정확히 넷이다 — 진입한 노드 수, 입력 토큰, 출력 토큰, 벽시계 시간.

**노드를 실행한 뒤에 검사하면 비용은 이미 발생한 뒤이므로, 그 한도는 사용량을 제한하지 못하고 초과 사실을 사후에 알리는 값이 된다.**

```
provider metadata + node id → StepTrace
ordered traces → cumulative token/request totals + cost → [pre-node budget guard] → RunReport
                                                              ↓
                                                    caller-owned persistence seam
```

다이어그램에서 한 지점을 주의해서 읽어야 한다. 비용은 누적 합계 옆에 나란히 있지만, 가드로 들어가는 화살표에 실리는 것은 합계뿐이다. 가드는 비용을 소비하지 않는다 — `Budget`에는 비용 필드가 없고, 지금 이 시스템의 비용 상한은 튜토리얼 1의 `ProviderBudget`이 가진 호출 단위 상한 하나뿐이다. 비용 추정이 실제로 무엇을 위한 것인지는 4절에서 다룬다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `StepTrace` | **모델 선언 작성** | 한 스텝에서 보존해야 하는 것 |
| `RunReport`·`Budget` | **모델 선언 작성** | 실패도 리포트를 만든다는 계약 |
| `build_run_report` | 집계를 **직접 구현** | 합계를 트레이스에서 유도하는 법 |
| `ModelPrice` | **설정 스키마 정의** | 모르는 모델을 추정하지 않는 이유 |
| `estimate_trace_cost_usd` | 비용 계산을 **직접 구현** | `Decimal` 산술의 경계 |

### 1. 한 스텝에서 보존해야 하는 것

#### `app/observability/types.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** 이 파일이 `app.llm`을 import하지 않는다는 점을 확인한다. 이 부재는 설계 결정이고, 그 보상은 튜토리얼 5에서 받는다. 거기서 구조적 `Protocol`이 어느 쪽도 상대를 import하지 않은 채 공급자 결과를 이 패키지로 건너오게 한다.

```python
"""Strict value objects for workflow traces, reports, and budgets."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictFloat, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator

WorkflowNode = Literal["retrieve", "grade", "check", "report"]
RunStatus = Literal["ok", "budget_exceeded", "schema_rejected", "error"]
JsonObject = dict[str, JsonValue]

NonnegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonnegativeFloat = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]

```

이 헤더의 별칭 두 개는 한 줄 이상의 무게를 가진다. `JsonValue`는 Pydantic의 재귀적 any-JSON 타입이다 — 문자열, 수, 불리언, `None`, 그리고 그것들로 이루어진 리스트와 딕셔너리까지. 따라서 `JsonObject = dict[str, JsonValue]`는 "값이 끝까지 전부 유효한 JSON인 JSON 객체"로 읽는다. 뒤에서 `report`가 서로 다른 세 가지 형태의 페이로드를 담으면서도 엄격한 JSONB 컬럼에 저장될 수 있는 것이 이 타입 덕분이다 — 다만 이 별칭 혼자만으로는 아니다. 별칭 자체는 유한하지 않은 부동소수점도 받아들이며, 그런 값이 JSONB 컬럼에 들어가지 않게 실제로 막는 것은 아래 고정 코드에 보이는 `report` 필드의 `reject_nonfinite_json` 검증기다.

#### `app/observability/types.py` 확장 — `StepTrace`

**학습 행동 — 모델 선언 작성:** 각 필드에 대해 그 필드가 없으면 사후에 무엇을 확인할 수 없는지 정리하며 작성한다.

<!-- src: app/observability/types.py::StepTrace -->
```python
class StepTrace(BaseModel):
    """One raw, traceable workflow step before persistence redaction."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    step: PositiveInt
    node: WorkflowNode
    model_name: Annotated[StrictStr, Field(min_length=1)]
    api_url: Annotated[StrictStr, Field(min_length=1)]
    input_tokens: NonnegativeInt
    output_tokens: NonnegativeInt
    request_time_ms: NonnegativeFloat
    llm_output: StrictStr
    retries: NonnegativeInt
    error: StrictStr | None = None

    @field_validator("model_name", "api_url", mode="after")
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        """Reject provider identity fields that contain only whitespace."""
        if not value.strip():
            raise ValueError("provider identity fields must not be blank")
        return value

    @field_validator("error", mode="after")
    @classmethod
    def reject_blank_error(cls, value: str | None) -> str | None:
        """Keep absence distinct from an unusable blank error message."""
        if value is not None and not value.strip():
            raise ValueError("error must be null or nonblank")
        return value
```

**코드에서 꼭 볼 것**

- `llm_output`을 그대로 저장한다. 실패한 스텝의 원시 출력이 없으면 실패 원인을 확인할 수 없다. M4.1의 `RawProviderResponse`가 여기까지 이어지고, 궤적은 한 걸음 더 간다. 튜토리얼 5가 바로 이 문자열에서 자격증명을 지운 뒤 데이터베이스에 쓰고, 실패 조사는 실제로 그 지점에서 시작된다.
- `retries`와 `error`가 별도 필드다. 재시도 후 성공한 스텝과 끝내 실패한 스텝이 구분된다.
- `api_url`을 기록한다. 어느 엔드포인트로 호출했는지가 남으므로, 설정 오류로 다른 환경에 요청한 실행을 사후에 찾을 수 있다.

코드가 보여주지 못하는 것이 하나 더 있다. 이 문서 안에는 `StepTrace`를 만드는 곳이 없다. 이 값은 튜토리얼 5의 `step_trace_from_provider_result`가 공급자 결과 하나를 트레이스 하나로 변환하는 자리에서 태어나고, `RunReport.steps` 안에서 살다가, 튜토리얼 5의 영속화 이음새를 지나며 비밀이 지워진 `Trace` 행으로 남는다. 이 파일의 일은 그 여정을 그대로 살아남아야 하는 것이 무엇인지 정의하는 것이다.

### 2. 실패도 리포트를 만든다

#### `app/observability/types.py` 확장 — `RunReport`와 `Budget`

**학습 행동 — 모델 선언 작성:** `status`의 네 값과 `report`에 `| None`이 붙는 관계를 확인하며 작성한다.

<!-- src: app/observability/types.py::RunReport,Budget -->
```python
class RunReport(BaseModel):
    """One complete or structured-failure workflow run."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    run_id: Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]
    status: RunStatus
    iterations: NonnegativeInt
    total_requests: NonnegativeInt
    total_input_tokens: NonnegativeInt
    total_output_tokens: NonnegativeInt
    total_time_seconds: NonnegativeFloat
    system_prompt: Annotated[StrictStr, Field(min_length=1)]
    node_path: tuple[WorkflowNode, ...]
    report: JsonObject | None
    steps: tuple[StepTrace, ...]

    @field_validator("system_prompt", mode="after")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        """Require the prompt provenance promised by the trace contract."""
        if not value.strip():
            raise ValueError("system_prompt must not be blank")
        return value

    @field_validator("report", mode="after")
    @classmethod
    def reject_nonfinite_json(cls, value: JsonObject | None) -> JsonObject | None:
        """Keep the report compatible with strict PostgreSQL JSONB serialization."""

        def validate(child: object) -> None:
            if isinstance(child, float) and not math.isfinite(child):
                raise ValueError("report must contain only finite JSON numbers")
            if isinstance(child, dict):
                for nested in child.values():
                    validate(nested)
            elif isinstance(child, list):
                for nested in child:
                    validate(nested)

        validate(value)
        return value

    @model_validator(mode="after")
    def validate_accumulated_totals(self) -> Self:
        """Reject reports whose cumulative counters disagree with their raw traces."""
        expected_steps = tuple(range(1, len(self.steps) + 1))
        actual_steps = tuple(trace.step for trace in self.steps)
        if actual_steps != expected_steps:
            raise ValueError("trace step numbers must be contiguous and start at 1")
        if self.iterations != len(self.node_path):
            raise ValueError("iterations must equal the number of entered nodes")
        expected_requests = sum(1 + trace.retries for trace in self.steps)
        if self.total_requests != expected_requests:
            raise ValueError("total_requests must include every trace request and retry")
        if self.total_input_tokens != sum(trace.input_tokens for trace in self.steps):
            raise ValueError("total_input_tokens must equal the trace sum")
        if self.total_output_tokens != sum(trace.output_tokens for trace in self.steps):
            raise ValueError("total_output_tokens must equal the trace sum")
        return self


class Budget(BaseModel):
    """Hard cumulative limits checked immediately before entering a node."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_iterations: NonnegativeInt = 6
    max_input_tokens: NonnegativeInt = 60_000
    max_output_tokens: NonnegativeInt = 4_000
    max_wall_clock_s: NonnegativeFloat = 120.0
```

**코드에서 꼭 볼 것**

- `status`는 네 값이고 네 경우 모두 `RunReport`를 만든다. 실행 결과가 예외로 끝나는 경로는 없다 — 다만 정확히 하자면, 러너는 타입이 잘못된 요청이나 공급자에 `TypeError`를, float 초를 돌려주지 않는 시계에 `ValueError`를 던진다. 이 둘은 실행 결과가 아니라 문 앞에서 잡히는 프로그래밍 오류다. 두 가드는 튜토리얼 8에서 본다. 잘못 짠 프로그램은 시끄럽게 실패하고, 실패한 실행은 리포트를 남긴다.
- `run_id`는 자유 텍스트가 아니라 패턴이다. 영문자나 숫자로 시작해 영문자, 숫자, `.`, `_`, `:`, `-`로 이어지고 최대 128자다. 제외된 문자들은 정확히 URL 경로 조각이나 파일 이름을 깨뜨리는 문자들이다 — 이 식별자는 로그, 파일 이름, 엔드포인트로 따옴표 없이 옮겨 다니도록 설계됐다.
- `report`에는 `| None`이 붙는다. 예산 초과로 멈춘 실행은 보고서가 없지만 **트레이스와 합계는 남는다.**
- `report`를 채우는 생산자는 셋이고 형태가 전부 다르다. 노드 진입 전 가드는 구조화된 거부 사유를 쓰고, 러너의 실패 경로는 타입 있는 실패를 JSON으로 덤프해 쓰고, 완주한 실행은 답변 리포트 전체를 쓴다. 생산자 셋에 형태가 셋이라는 사실이 이 필드가 타입 있는 모델이 아니라 느슨한 JSON인 이유다 — 성공 사례를 차지하는 타입 있는 `WorkflowReport`는 튜토리얼 6에서 만들고, 이 필드는 셋이 만나는 합류점이다.
- `Budget`은 `max_wall_clock_s`도 포함한다. 토큰이 남아 있어도 지정한 시간을 넘기면 실행을 멈춘다.
- 기본값을 숫자로 읽어 둘 가치가 있다. 반복 6회, 입력 60,000토큰, 출력 4,000토큰, 120.0초. 노드가 넷인 그래프에 반복 한도가 6이라는 것은 이 값이 튜닝된 값이 아니라 여유분이라는 뜻이다 — 저장소 어디에도 이 기본값을 유도한 근거가 없으니, 측정된 값처럼 취급하면 안 된다.
- `Budget`에는 비용 필드가 없다. 가드는 트레이스와 시계로 정확히 재계산할 수 있는 것만 집행한다. 비용은 가격표에서 유도한 추정치이고, 오늘 그 집행 지점은 이 모델이 아니라 튜토리얼 1의 호출 단위 공급자 예산이다. 4절에서 이것을 정직하게 밝힌다.
- `system_prompt`를 리포트에 저장한다. 프롬프트를 수정하면 결과가 달라지므로, 어떤 프롬프트로 얻은 결과인지가 함께 남아야 두 실행을 비교할 수 있다.

### 3. 합계를 트레이스에서 유도한다

#### `app/observability/types.py` 완성 — 리포트 조립

**학습 행동 — 집계 구현:** `build_run_report`를 직접 구현한다. 합계를 어디에서 계산하는지가 핵심이다.

<!-- src: app/observability/types.py::build_run_report,validate_elapsed_seconds -->
```python
def build_run_report(
    *,
    run_id: str,
    status: RunStatus,
    total_time_seconds: float,
    system_prompt: str,
    node_path: tuple[WorkflowNode, ...] | list[WorkflowNode],
    steps: tuple[StepTrace, ...] | list[StepTrace],
    report: JsonObject | None = None,
) -> RunReport:
    """Derive cumulative counters from raw traces instead of trusting callers."""
    trace_values = tuple(steps)
    return RunReport(
        run_id=run_id,
        status=status,
        iterations=len(node_path),
        total_requests=sum(1 + trace.retries for trace in trace_values),
        total_input_tokens=sum(trace.input_tokens for trace in trace_values),
        total_output_tokens=sum(trace.output_tokens for trace in trace_values),
        total_time_seconds=total_time_seconds,
        system_prompt=system_prompt,
        node_path=tuple(node_path),
        report=report,
        steps=trace_values,
    )


def validate_elapsed_seconds(value: object) -> float:
    """Validate an externally measured monotonic duration without coercion."""
    if isinstance(value, bool) or not isinstance(value, float):
        raise ValueError("elapsed_seconds must be a finite nonnegative float")
    if not math.isfinite(value) or value < 0:
        raise ValueError("elapsed_seconds must be a finite nonnegative float")
    return value
```

**코드에서 꼭 볼 것**

- 토큰 합계를 `steps`를 순회해 계산한다. 별도 카운터가 없으므로 합계와 트레이스가 어긋날 수 없다.
- `validate_elapsed_seconds`가 음수와 유한하지 않은 값을 거부한다. 경과 시간이 잘못되면 시간 예산 판정도 함께 무효가 된다. 필드 검증기가 아니라 자유 함수인 데에는 이유가 있다. 이 값은 검증기를 걸 모델이 존재하기 전에 예산 가드의 인자로 맨몸으로 도착한다 — 가드가 시계 값을 먼저 검증하고, 그 다음에야 `RunReport`를 만들지 말지 결정한다.
- 스텝 번호의 연속성을 확인한다. 트레이스가 하나 빠지면 합계가 그만큼 줄어든 채로 정상 값처럼 보고된다.

> **개념 — 스텝이 아니라 요청을 센다**
>
> 트레이스 하나는 워크플로 스텝 하나지만, 스텝 하나가 HTTP 요청 하나는 아니다. 튜토리얼 3의 복구 루프가 거부된 응답을 재시도하면 그 재시도는 실제로 비용을 치른 요청이고, 트레이스는 그 횟수를 보관한다. 스텝당 요청 하나로 세면 실패 경로에서 정확히 비싼 부분이 지워진다.
>
> 요청 합계가 트레이스 개수가 아니라 트레이스마다 1 더하기 재시도 횟수를 합한 값인 이유가 이것이다. 스텝 하나가 한 번 재시도한 실행은 요청 두 개를 보고한다 — 스텝 수와 요청 수는 원래 어긋나라고 만든 숫자다.

커밋된 스위트가 그 사례를 고정한다. `tests/workflow/test_03_observability.py`가 `retries=1`인 스텝 하나짜리 리포트를 만들고 `total_requests == 2`를 단언한다.

> **개념 — 연속성은 변조 검사다**
>
> 스텝 번호는 1부터 시작하고 빈틈이 없다. 트레이스 셋을 담은 리포트는 반드시 1, 2, 3번 스텝을 실어야 한다. 검증기는 트레이스 개수만으로 기대 수열을 다시 만들어 트레이스가 주장하는 번호와 대조한다. 트레이스 하나가 사라지면 합계가 줄어드는 데서 끝나지 않는다 — 번호에 구멍이 생기고, 그 구멍이 리포트 생성 자체를 불가능하게 만든다.
>
> 이 규칙이 없으면 잃어버린 트레이스는 설계상 탐지 불가능하다. 합계는 살아남은 트레이스에서 유도되므로 서로는 여전히 일치한다 — 완벽하게, 그리고 틀리게. 내부적으로 일관된 산술이 잡지 못하는 것을 잡는 유일한 검사가 연속성이다.

질문이 하나 남는다. 항상 유도할 수 있다면 합계를 왜 리포트에 저장하는가? 리포트가 메모리에 머물지 않기 때문이다. 튜토리얼 5의 `report_to_records`가 `iterations`, `total_requests`와 두 토큰 합계를 영속화된 실행 행의 컬럼으로 복사하고, 그 컬럼을 조회하는 모니터링 쿼리는 트레이스를 전부 되살리지 않고 "어제 얼마를 썼는가"에 답해야 한다. 저장된 중복은 의도된 것이고, 그 중복을 안전하게 만드는 것이 위의 검증기다.

### 4. 모르는 모델은 추정하지 않는다

#### `app/observability/cost.py` 생성 — 모듈 헤더와 가격표

**학습 행동 — 설정 스키마 정의:** 모르는 모델 이름을 기본값이 아니라 `UnknownModelPriceError`로 처리하는 이유를 확인한다.

```python
"""Deterministic token-cost estimates using versioned, explicit prices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from app.observability.types import StepTrace

TOKENS_PER_MILLION: Final[Decimal] = Decimal(1_000_000)

```

<!-- src: app/observability/cost.py::ModelPrice,UnknownModelPriceError -->
```python
@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD prices per one million uncached input and output tokens."""

    input_per_million: Decimal
    output_per_million: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.input_per_million, Decimal) or not isinstance(
            self.output_per_million, Decimal
        ):
            raise ValueError("model prices must be Decimal values")
        if not self.input_per_million.is_finite() or not self.output_per_million.is_finite():
            raise ValueError("model prices must be finite")
        if self.input_per_million < 0 or self.output_per_million < 0:
            raise ValueError("model prices must be nonnegative")


# Published launch prices are pinned so historical trace estimates never drift.
MODEL_PRICES: Final[dict[str, ModelPrice]] = {
    "gpt-4.1-mini": ModelPrice(Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1-mini-2025-04-14": ModelPrice(Decimal("0.40"), Decimal("1.60")),
}


class UnknownModelPriceError(ValueError):
    """Raised when cost would otherwise be silently reported as zero."""
```

`ModelPrice`는 온통 Pydantic인 패키지에서 유일한 순수 dataclass이고, 이 불일치는 의도된 것이다. 이 가격들은 외부 입력에서 파싱되는 것이 아니라 바로 이 파일에 모듈 상수로 작성되므로 파싱 시점 검증 장치가 이득이 없다. `frozen=True`와 `slots=True`가 더 적은 장치로 불변성과 닫힌 속성 집합을 준다. `__post_init__`은 모델 검증기의 dataclass 대응물이다 — 필드 할당 뒤에 실행되고, Decimal·유한성·부호 검사가 거기에 산다. 눈에 보이는 재사용 후보인 튜토리얼 1의 `NonNegativeDecimal` 별칭은 구조적 이유로 기각된다. 그 별칭은 `app.llm`에 살고, 그것을 import하는 순간 이 패키지가 갖지 않기로 설계한 바로 그 의존성이 생긴다.

`Final`은 모듈 상수를 지키는데, 무엇을 막는지 정확히 알아둘 가치가 있다. 이것은 런타임 잠금이 아니라 타입 검사기 약속이다. `TOKENS_PER_MILLION`이나 `MODEL_PRICES`를 다시 바인딩하면 리뷰에서 타입 오류가 되지만, 실행 중인 코드는 여전히 딕셔너리 내용을 제자리에서 바꿀 수 있다. 보증의 런타임 절반은 `ModelPrice` 자체가 frozen이라는 데서 온다 — 표는 바꿀 수 있는 자리에서도 표 안의 값은 편집할 수 없다.

> **개념 — 열린 실패가 아니라 닫힌 실패**
>
> 답을 모르는 조회에는 선택지가 둘 있다. 추측하거나 거부하거나. 비용 수치에서 0은 최악의 추측이다. 0은 "아무것도 쓰지 않았다"와 구별되지 않아서 오류가 그럴듯한 값 안에 숨고, 하류의 모든 소비자가 그것을 물려받는다. 거부는 모르는 모델 이름을 들여온 바로 그 호출 지점에서 공백을 시끄럽게 만든다.
>
> 거부 타입은 평범한 값 오류 계열을 상속한다. 잘못된 입력을 이미 오류로 다루는 호출자는 새 코드 없이 이 경우도 다루고, 특정해서 잡는 것은 여전히 가능하며, 실수로 무시하는 것은 불가능하다.

표의 키가 둘인 것은 우연한 중복이 아니다. `gpt-4.1-mini`는 떠다니는 별칭이고 `gpt-4.1-mini-2025-04-14`는 날짜가 박힌 스냅샷이며 가격은 동일하다 — 날짜 모델에 고정한 배포와 별칭을 따라가는 배포가 둘 다 조회에 성공한다. 미래의 스냅샷이 다른 가격으로 나오면 자기 행을 새로 얻는다. 표 위의 주석이 과거 추정치는 표류하지 않는다고 약속하는데, 스냅샷별 행이 그 약속을 지키는 장치다.

**코드에서 꼭 볼 것**

- 모르는 모델 이름은 **예외로 처리한다.** 0으로 계산하거나 비슷한 모델의 가격을 대신 쓰지 않는다. 오늘 이것이 무엇을 지키는지는 정확히 말해 둔다. `app/` 안에서 이 추정 함수들을 부르는 코드는 아직 없다 — `Budget`에는 비용 축이 없고 노드 진입 전 가드는 비용을 읽지 않으므로, 비용 추정은 집행 경로가 아니라 보고 표면이다. 닫힌 실패는 보고되는 수치를 지금도, 언젠가 무언가가 이것을 집행하게 되는 날에도 믿을 수 있게 유지한다. 0 추정이었다면 실제 지출이 공짜로 기록되고 모든 소비자가 그럴듯한 거짓을 건네받는다.
- 가격 단위는 백만 토큰이다. 공급자 가격표가 같은 단위로 고시되므로 옮겨 적을 때 단위 변환이 필요 없다.

가격표는 한 줄로 검증할 수 있다. 양방향 각각 백만 토큰이면 정확히 0.40 + 1.60달러가 나와야 한다.

```bash
uv run python -c "from app.observability import estimate_cost_usd; print(estimate_cost_usd('gpt-4.1-mini', 1_000_000, 1_000_000))"
```

이 명령은 `2.00`을 출력한다 — 커밋된 스위트가 같은 값을 `Decimal`로 단언하고, 다른 출력이 나온다면 가격표가 바뀐 것이다.

### 5. `Decimal` 산술의 경계

#### `app/observability/cost.py` 완성 — 비용 추정

**학습 행동 — 비용 계산 구현:** `Decimal` 값이 어디에서 만들어지고 어디까지 유지되는지 따라가며 작성한다.

<!-- src: app/observability/cost.py::_token_count,estimate_trace_cost_usd -->
```python
def _token_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def estimate_cost_usd(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    *,
    prices: dict[str, ModelPrice] | None = None,
) -> Decimal:
    """Estimate uncached token cost exactly with decimal arithmetic.

    Unknown models fail closed because a zero estimate would weaken the budget signal.
    Callers can pass an explicit versioned table for other providers or pricing dates.
    """
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name must be a nonblank string")
    input_count = _token_count(input_tokens, "input_tokens")
    output_count = _token_count(output_tokens, "output_tokens")
    table = MODEL_PRICES if prices is None else prices
    try:
        price = table[model_name]
    except KeyError as exc:
        raise UnknownModelPriceError(f"no pinned price for model {model_name!r}") from exc
    return (
        Decimal(input_count) * price.input_per_million
        + Decimal(output_count) * price.output_per_million
    ) / TOKENS_PER_MILLION


def estimate_trace_cost_usd(
    steps: tuple[StepTrace, ...] | list[StepTrace],
    *,
    prices: dict[str, ModelPrice] | None = None,
) -> Decimal:
    """Sum deterministic per-trace estimates without floating-point rounding."""
    total = Decimal(0)
    for trace in steps:
        if not isinstance(trace, StepTrace):
            raise ValueError("steps must contain StepTrace values")
        total += estimate_cost_usd(
            trace.model_name,
            trace.input_tokens,
            trace.output_tokens,
            prices=prices,
        )
    return total
```

**코드에서 꼭 볼 것**

- 토큰 수를 `_token_count`가 검증해 불리언과 음수를 거부한다. `True`가 1토큰으로 통과하면 계산된 금액이 오류 없이 실제와 달라진다.
- 나눗셈을 `Decimal`끼리 수행한다. 중간에 `float`가 한 번이라도 섞이면 그 오차가 최종 금액까지 전파된다.
- `estimate_trace_cost_usd`는 트레이스 목록을 받아 합산한다. 스텝마다 사용한 모델이 다를 수 있으므로 가격도 스텝별로 조회한다.

커밋된 스위트는 가장 작은 현실적 규모에서도 산술을 고정한다. 공용 테스트 픽스처는 `gpt-4.1-mini`로 입력 100토큰, 출력 20토큰을 쓰고, 그 트레이스 하나에 대한 `estimate_trace_cost_usd`는 정확히 `Decimal("0.000072")`를 돌려준다 — 100 × 0.40 / 1,000,000 더하기 20 × 1.60 / 1,000,000이고, 부동소수점 잔여물이 없다. 하니스 없이 재현해 본다.

```bash
uv run python -c "from app.observability import estimate_cost_usd; print(estimate_cost_usd('gpt-4.1-mini', 100, 20))"
```

여기서 `0.000072` 외의 값이 나오면 가격이나 산술이 움직인 것이다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 타입과 연결해 설명해 본다.

- **관측을 워크플로보다 먼저 만드는 이유는 무엇인가?**
  - **답:** 실패 경로를 처음부터 설계에 포함해 나중에 로그 한 줄이나 예외 처리 뒤로 사라지지 않게 하기 위해서다.
- **네 가지 종료 상태가 전부 `RunReport`를 만드는 것이 무엇을 가능하게 하는가?**
  - **답:** 성공, 예산 소진, 스키마 거부, 오류를 모두 같은 리포트 형태로 조사할 수 있게 한다.
- **합계를 별도 카운터로 세면 언제 어긋나는가?**
  - **답:** 트레이스를 추가·삭제·수정하면서 별도 카운터에 똑같은 변경을 반영하지 않는 순간 어긋난다.
- **예산을 노드 실행 뒤에 검사하면 무엇이 무력해지는가?**
  - **답:** 천장 그 자체다. 사후 검사는 이미 발생한 지출을 관찰한다 — 실행은 여전히 다음 노드 전에 멈추지만, 방금 실행된 노드는 한 번도 상한에 묶인 적이 없으므로 그 노드에 대해서는 한도가 아무것도 막지 못하고 초과를 보고했을 뿐이다. 진입 전에 검사하면 자원을 아직 쓰기 전에 노드를 거부하고, 그것이 한도를 한도로 만든다.
- **모르는 모델 이름을 0으로 치면 어떤 조용한 실패가 생기는가?**
  - **답:** 실제 지출이 0으로 기록되고, 0은 유효한 추정처럼 보이므로 하류의 어떤 것도 그 수치가 틀렸다는 것을 알 수 없다. 닫힌 실패는 그 조용한 오염을, 그 모델 이름을 들여온 호출에서 나는 시끄러운 오류로 바꾼다.

---

[← 이전: 공급자 구현](03-provider-impl.md) · [모듈 개요](../03-build.md) · [다음: 예산과 영속화 →](05-observability-trace.md)
