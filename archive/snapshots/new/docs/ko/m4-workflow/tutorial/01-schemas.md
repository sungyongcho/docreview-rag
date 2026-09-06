# M4.1 튜토리얼 1 — 워크플로를 짜기 전에 경계부터 세운다

M4는 LLM 호출을 하나의 **공급자 경계**로 모은다. 프롬프트 전송, 출력 검증, 토큰 집계, 실패 처리가 모두 이 경계에서 일어난다.

**선행 조건:** M3이 끝나 `uv run pytest tests/evals -q`가 통과해야 한다.

### 경계를 한 곳에 모으는 이유

경계가 없으면 워크플로 노드 네 개가 각각 자기 방식으로 JSON을 파싱하고, 각자의 규칙으로 재시도하고, 토큰을 따로 집계한다. 그 결과는 다음과 같다.

- 재시도 정책이 노드마다 다르다 (하나는 세 번, 하나는 아예 안 함)
- 파싱 실패 처리가 다르다 (하나는 예외, 하나는 빈 값 반환)
- **원시 공급자 응답이 어딘가에서 버려진다** — 나중에 왜 실패했는지 볼 수 없다
- 결정론적 테스트 공급자와 실제 OpenAI가 서로 다른 계약을 따른다

**규칙을 한 곳에 모으면 노드는 프롬프트와 기대하는 출력 스키마만 지정하고, 검증·재시도·계측은 경계가 처리한다.** 노드마다 재시도 횟수와 실패 처리가 달라지는 상태 자체가 생기지 않는다.

파일 전체를 관통하는 불변조건은 한 문장이고, 테스트로 확인할 수 있다. `ProviderResult`는 파싱된 값과 거부를 동시에 갖지 않으며, 둘 다 없는 상태도 되지 않는다. 4절 이전에 작성하는 모든 모델은 이 문장을 타입으로 표현 가능하게 만드는 어휘이고, 마지막의 `validate_result_state`가 그것을 강제하는 코드다.

### 복구는 정확히 한 번

구조화 출력이 스키마와 맞지 않으면 복구 프롬프트를 한 번 보내고, 그 시도도 실패하면 타입이 있는 거부를 반환한다.

**재시도 횟수를 늘리면 성공률과 함께 비용과 지연도 함께 늘어나고, 모델이 같은 스키마를 두 번 연속 맞히지 못했다면 원인은 대개 프롬프트나 스키마 자체에 있다.** 세 번째 호출은 같은 원인을 한 번 더 지불하는 것에 가깝다.

횟수 제한이 없으면 예산 초과가 감지되기 전에 호출이 계속 쌓인다.

이 정책은 주석이 아니라 이 문서에서 작성하는 타입에 새겨진다. `ProviderMetadata.retries`는 `Field(ge=0, le=1)`로 제약되어 재시도 두 번을 주장하는 메타데이터 자체를 만들 수 없고, `SchemaRejected.attempts`는 기본값 2를 가진 `Literal[2]`라서 스키마 거부는 타입 수준에서 복구 시도까지 실패한 뒤에만 존재할 수 있는 값이다.

거부를 반환할 때도 **원시 응답과 메타데이터를 함께 반환한다.** 실패를 예외 하나로 삼키면 무엇이 왜 실패했는지 확인할 근거가 남지 않는다.

```
Prompt + schema + ProviderBudget → provider call → RawProviderResponse → strict parse
                                                        ↓ failure
                                            one repair prompt → final typed result
```

### 무엇을 작성하고 어디를 직접 구현할까

이 문서는 `app/llm/schemas.py` 한 파일을 다섯 단계로 작성한다. 공급자 구현은 다음 두 문서에서 만든다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 값 어휘와 `StrictSchema` | **설정 스키마 정의** | `strict=True`가 추가로 막는 것 |
| `Prompt`·`TokenPricing`·`ProviderBudget` | **모델 선언 작성** | 호출 전에 정해지는 한도 |
| `AnswerDecision`의 모델 검증기 | 배타 규칙을 **직접 구현** | 라벨과 근거가 모순될 수 없게 하는 법 |
| 실패 타입 셋 | **레코드 선언 작성** | 실패를 문자열이 아니라 값으로 남기는 이유 |
| `ProviderResult` | 불변조건을 **직접 구현** | 성공과 실패가 동시에 참일 수 없게 하는 법 |

### 1. 값 어휘와 fail-closed 기반

#### `app/llm/schemas.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록에서 `Decimal`을 확인한다. 비용 계산에 부동소수 타입을 쓰지 않는다는 뜻이다.

```python
"""Strict structured-output, budget, and provider-result schemas for M4."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from pydantic.functional_validators import field_validator, model_validator
```

#### `app/llm/schemas.py` 확장 — 값 어휘

**학습 행동 — 설정 스키마 정의:** 앞의 별칭 네 개는 제약이다 — 각각 어떤 잘못된 값을 막는지 확인하며 작성한다. 뒤의 두 개는 닫힌 어휘로, 값을 제약하는 것이 아니라 존재하는 값 전체를 열거한다.

<!-- src: app/llm/schemas.py::NonBlank,ProviderStatus -->
```python
NonBlank = Annotated[StrictStr, Field(min_length=1)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
AnswerLabel = Literal["SUPPORTED", "NOT_IN_DOCS"]
ProviderStatus = Literal[
    "ok",
    "schema_rejected",
    "provider_refused",
    "provider_error",
    "budget_exceeded",
]
```

**코드에서 꼭 볼 것**

- `Annotated[StrictStr, Field(min_length=1)]`은 타입과 제약을 하나의 이름으로 묶는다. `NonBlank`로 선언한 모든 필드가 코드를 반복하지 않고 같은 규칙을 얻고, 규칙을 바꾸면 전부 한 번에 바뀐다.
- `NonNegativeDecimal`은 `Decimal` 기반이고 `allow_inf_nan=False`다. **비용을 `float`로 다루면 이진 부동소수가 표현하지 못하는 십진 소수의 오차가 누적되어 청구 금액과 계산 금액이 어긋난다.**
- `ProviderStatus`는 값 다섯 개의 `Literal`이다. `"provider_refused"`는 모델이 응답을 거부한 경우이고 `"provider_error"`는 호출 자체가 실패한 경우다. **두 상태를 하나로 합치면 프롬프트를 고쳐야 하는 실패와 네트워크·인증을 고쳐야 하는 실패를 구분할 수 없다.** 비대칭도 확인한다. 다섯 값 중 거부에 실릴 수 있는 것은 네 개뿐이고, `"ok"`는 실패 값과 함께 다니지 않는 유일한 상태다.

> **개념 — Decimal은 정확하게 만들어야 정확하다**
>
> 이진 부동소수는 대부분의 십진 소수를 표현하지 못한다. 0.1 + 0.2가 0.3이 아니라는 것이 대표적인 예이고, 이 오차는 연산을 거치며 누적된다. Decimal은 십진 자릿수를 그대로 저장하므로 0.1 + 0.2가 정확히 0.3이다. 이 파일의 모든 금액 필드가 Decimal 기반인 이유다.
>
> 함정은 생성자에 있다. float에서 Decimal을 만들면 이진 오차가 먼저 확정된 뒤 그 값이 충실히 보존된다. Decimal(0.4)는 float의 긴 이진 꼬리를 그대로 담지만, Decimal("0.4")는 정확히 10분의 4다. 가격표를 손으로 쓸 때는 값을 문자열이나 정수로 넣어야 하고, float 리터럴로 넣으면 안 된다.

왜 `Literal`을 쓰고 `Enum`을 쓰지 않는가? 대부분의 파이썬 코드베이스가 먼저 꺼내는 것은 `StrEnum`이고, 그것도 동작은 한다. 그러나 M4의 경계 값은 전부 동결되어 JSON 트레이스로 변형 없이 왕복해야 한다. 평범한 문자열 `Literal`은 문자열 그 자체로 직렬화되고, 저장된 원시 JSON과 `==`로 바로 비교되며, 소비하는 쪽에 import를 요구하지 않는다. 열거형은 저장된 트레이스를 읽는 모든 코드가 복원해야 하는 클래스를 하나 얹는데, 이 어휘는 메서드나 순회에서 얻는 것이 없다. 튜토리얼 6의 워크플로 사유 타입들도 같은 이유로 같은 선택을 한다.

#### `app/llm/schemas.py` 확장 — `StrictSchema`와 예산

**학습 행동 — 모델 선언 작성:** `StrictSchema`의 `model_config` 항목 세 개를 확인하며 작성한다.

<!-- src: app/llm/schemas.py::StrictSchema,ProviderBudget -->
```python
class StrictSchema(BaseModel):
    """Frozen fail-closed base for all M4 boundary values."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Prompt(StrictSchema):
    """System and user text sent through one provider boundary."""

    system: NonBlank
    user: NonBlank

    @field_validator("system", "user", mode="after")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """Reject whitespace-only prompts without silently normalizing them."""
        if not value.strip():
            raise ValueError("prompt text must not be blank")
        return value


class TokenPricing(StrictSchema):
    """Caller-supplied provider prices in USD per million tokens."""

    input_per_million_usd: NonNegativeDecimal
    output_per_million_usd: NonNegativeDecimal

    def estimate(self, input_tokens: int, output_tokens: int) -> Decimal:
        """Return the exact Decimal estimate for explicit token counts."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be nonnegative")
        million = Decimal(1_000_000)
        return (
            Decimal(input_tokens) * self.input_per_million_usd
            + Decimal(output_tokens) * self.output_per_million_usd
        ) / million


class ProviderBudget(StrictSchema):
    """Remaining cumulative token and estimated-cost allowance for one completion."""

    max_input_tokens: PositiveInt
    max_output_tokens: PositiveInt
    max_cost_usd: NonNegativeDecimal
    pricing: TokenPricing
```

**코드에서 꼭 볼 것**

- `strict=True`는 M2.1의 `Strict*` 타입에서 한 단계 더 나아간다. M2.1의 `ChunkHit` 설정은 `extra="forbid", frozen=True`였다 — 엄격함은 필드 단위의 `Strict*` 별칭에 있었고, 평범하게 선언한 필드는 조용히 강제 변환을 받았다. 여기서는 스위치가 **모델 전체**로 옮겨져, 나중에 필드를 추가할 때 제약을 빠뜨릴 자리가 없다.
- `ProviderBudget`은 호출 **전에** 만들어진다 — 만드는 쪽은 호출자이고, 공급자는 절대 만들지 않는다. 토큰 한도와 비용 한도가 요청 값에 실려 나가므로, 이번 호출이 쓸 수 있는 양이 코드가 아니라 값으로 기록된다. 공급자는 이 값을 변경하지도 못한다. 기반 클래스가 동결되어 있으므로 튜토리얼 3의 복구 경로는 `model_copy`로 시도별 사본을 줄여 쓰고, 호출자의 원본은 그대로 남는다.
- `TokenPricing`은 별도 인자가 아니라 예산 안에 산다. 비용 한도는 그것을 판정할 가격표 없이는 의미가 없다 — 따로 전달하면 둘이 어긋날 수 있고, 어떤 가격 기준으로 정한 한도가 다른 가격으로 집행된다. 안에 품으면 가격이 바뀔 때 예산 객체 자체가 달라지므로, 이전 가격으로 계산한 비용과 새 비용이 섞이지 않는다.

> **개념 — 강제 변환, 그리고 strict 스위치가 있는 곳**
>
> Pydantic의 기본은 관대(lax) 모드다. 정수로 선언한 자리에 문자열 "5"가 오면 5로, 정수 5는 실수 5.0으로, "true"는 True로 조용히 바뀐다. 웹 폼에서는 편의지만, 돈과 실패 상태를 다루는 경계에서는 소리 없는 데이터 개조다.
>
> 끄는 자리는 두 곳이다. 필드 수준: Strict* 별칭이 개별 필드를 제외한다. M2.1이 쓴 방식이고, 기억해 낸 자리에만 보호가 생긴다. 모델 수준: 설정의 strict=True가 지금 있는 필드와 나중에 누가 추가할 필드 전부에서 강제 변환을 끈다.
>
> 이 파일은 둘 다 쓴다. 모델 설정이 기본 방어선이고, 별칭 속 Strict* 타입은 별칭이 더 관대한 설정의 모델에서 재사용되더라도 스스로 엄격함을 유지하게 하는 이중 장치다.

이 블록에서 하나 더 볼 것이 있다. `Prompt`는 `reject_blank_text`를 갖는다. `system`과 `user`가 이미 `NonBlank`인데도 그렇다. 두 관문이 막는 문자열이 다르다.

> **개념 — min_length는 글자 수를 세고, strip은 공백을 가려낸다**
>
> min_length=1 제약이 거부하는 것은 빈 문자열 하나뿐이다. 공백 한 칸은 길이가 1이라 통과하고, 탭도, 줄바꿈도, 공백 마흔 칸도 통과한다. "아무 말도 하지 않는 문자열"을 잡는 데 길이는 맞는 도구가 아니다.
>
> 검증기가 더하는 것이 그것이다. value.strip()은 공백뿐인 텍스트를 빈 문자열로 접으므로, 길이 규칙이 통과시키는 겉보기에 빈 문자열을 전부 잡는다. 이 짝은 의도된 설계다 — 별칭은 퇴화 사례를 어디서나 공짜로 막고, 검증기는 자유 텍스트를 담는 모델 다섯 개에서 의미론적 검사를 맡는다.
>
> 이 파일은 같은 모양의 검증기를 다섯 번 반복한다. 중복 제거 대상이 아니라 한 관문의 사본 다섯 개로 읽어야 한다 — 하나를 지우면 그 모델에만 공백 문자열이 들어온다.

커밋된 테스트가 이 절의 산술을 숫자로 못 박는다. 백만 토큰당 2달러와 10달러의 가격에서 `estimate(100, 20)`은 정확히 `Decimal("0.0004")`를 반환한다 — 100 × 2 / 1,000,000 + 20 × 10 / 1,000,000이고, 중간값이 전부 Decimal이라 테스트의 등호는 근사가 아니라 정확한 일치다.

```bash
uv run pytest tests/workflow/test_01_schemas.py -k token_pricing -q
```

### 2. 라벨과 근거가 모순될 수 없게 한다

#### `app/llm/schemas.py` 확장 — 판정과 답변 결정

**학습 행동 — 배타 규칙 구현:** `AnswerDecision`의 모델 검증기를 직접 구현한다. M3.1의 positive와 absent 배타 규칙과 같은 구조다.

<!-- src: app/llm/schemas.py::ChunkRelevance,AnswerDecision -->
```python
class ChunkRelevance(StrictSchema):
    """One source chunk graded for relevance by a structured LLM call."""

    chunk_id: PositiveInt
    relevant: StrictBool
    reason: NonBlank

    @field_validator("reason", mode="after")
    @classmethod
    def reject_blank_reason(cls, value: str) -> str:
        """Require an inspectable grading reason."""
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value


class RelevanceJudgment(StrictSchema):
    """Complete relevance grades for one retrieved candidate set."""

    grades: tuple[ChunkRelevance, ...]

    @model_validator(mode="after")
    def reject_duplicate_chunk_ids(self) -> Self:
        """Prevent one chunk from receiving contradictory duplicate grades."""
        chunk_ids = [grade.chunk_id for grade in self.grades]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("graded chunk ids must be unique")
        return self


class AnswerDecision(StrictSchema):
    """One structured evidence decision produced before workflow code guards it."""

    label: AnswerLabel
    answer: NonBlank
    citation_chunk_ids: tuple[PositiveInt, ...]
    reason: NonBlank

    @field_validator("answer", "reason", mode="after")
    @classmethod
    def reject_blank_decision_text(cls, value: str) -> str:
        """Require visible answer and decision rationale text."""
        if not value.strip():
            raise ValueError("decision text must not be blank")
        return value

    @model_validator(mode="after")
    def validate_label_contract(self) -> Self:
        """Keep supported and absent structured states mutually exclusive."""
        if len(self.citation_chunk_ids) != len(set(self.citation_chunk_ids)):
            raise ValueError("citation chunk ids must be unique")
        if self.label == "SUPPORTED":
            if not self.citation_chunk_ids:
                raise ValueError("SUPPORTED decisions require at least one citation")
            if self.answer == "NOT_IN_DOCS":
                raise ValueError("SUPPORTED decisions require a supported answer")
        else:
            if self.answer != "NOT_IN_DOCS":
                raise ValueError("NOT_IN_DOCS decisions must use the NOT_IN_DOCS answer")
            if self.citation_chunk_ids:
                raise ValueError("NOT_IN_DOCS decisions must not contain citations")
        return self
```

**코드에서 꼭 볼 것**

- 라벨이 `SUPPORTED`인데 `citation_chunk_ids`가 비어 있으면 거부한다. 근거를 제시하지 않은 지지 답변은 M4가 막아야 할 첫 번째 실패다. 같은 분기가 별개의 두 번째 모순도 거부한다. `SUPPORTED`이면서 답변이 문자 그대로 `NOT_IN_DOCS`인 경우다.
- 라벨이 `NOT_IN_DOCS`인데 인용이 있으면 거부한다. 문서에 없다고 판정하면서 문서를 인용하는 출력이다.
- M3.1의 `GoldenCase`가 정답 데이터 쪽에서 세운 배타 규칙을 여기서는 **모델 출력 쪽**에 같은 형태로 세운다. 평가와 실행이 같은 계약을 공유한다.
- 이 블록의 모델 검증기 두 개는 같은 시그니처를 공유한다. `@model_validator(mode="after")`로 선언하고 `Self`를 반환한다. after 모드는 완전히 만들어져 타입이 확정된 인스턴스 위에서 돌므로, 검사가 여러 필드를 한 번에 읽고 객체 자신을 그대로 돌려줄 수 있다. 이 파일은 이 시그니처를 여섯 번 쓰는데, 전부 필드 하나로는 볼 수 없는 필드 간 사실을 위해서다.

### 3. 실패를 문자열이 아니라 값으로 남긴다

#### `app/llm/schemas.py` 확장 — 원시 응답과 실패 타입

**학습 행동 — 레코드 선언 작성:** 실패 타입 세 개가 각각 어떤 근거를 함께 저장하는지 확인한다.

<!-- src: app/llm/schemas.py::RawProviderResponse,CompletionFailure -->
```python
class RawProviderResponse(StrictSchema):
    """Provider-neutral raw response used by adapters and deterministic tests."""

    output_text: StrictStr
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    request_id: StrictStr | None = None
    refusal: StrictStr | None = None

    @field_validator("request_id", "refusal", mode="after")
    @classmethod
    def reject_blank_optional_text(cls, value: str | None) -> str | None:
        """Reject present-but-empty identifiers and refusals."""
        if value is not None and not value.strip():
            raise ValueError("optional provider text must not be blank")
        return value


class SchemaRejected(StrictSchema):
    """Typed fail-closed result after one repair attempt also fails."""

    status: Literal["schema_rejected"] = "schema_rejected"
    errors: tuple[NonBlank, ...]
    attempts: Literal[2] = 2

    @model_validator(mode="after")
    def require_errors(self) -> Self:
        """Require the final validation failure to remain inspectable."""
        if not self.errors:
            raise ValueError("schema rejection requires validation errors")
        return self


class BudgetExceeded(StrictSchema):
    """Typed refusal when a call or repair cannot continue within its budget."""

    status: Literal["budget_exceeded"] = "budget_exceeded"
    which: Literal["input_tokens", "output_tokens", "estimated_cost_usd"]
    used: StrictInt | Decimal
    limit: StrictInt | Decimal
    attempts: Annotated[StrictInt, Field(ge=1, le=2)]

    @model_validator(mode="after")
    def validate_nonnegative_values(self) -> Self:
        """Reject nonsensical negative budget evidence."""
        if self.used < 0 or self.limit < 0:
            raise ValueError("budget evidence must be nonnegative")
        if isinstance(self.used, Decimal) and not self.used.is_finite():
            raise ValueError("used budget evidence must be finite")
        if isinstance(self.limit, Decimal) and not self.limit.is_finite():
            raise ValueError("budget limit evidence must be finite")
        return self


class ProviderRefusal(StrictSchema):
    """Typed model refusal or provider-boundary error."""

    status: Literal["provider_refused", "provider_error"]
    message: NonBlank
    attempts: Annotated[StrictInt, Field(ge=1, le=2)]

    @field_validator("message", mode="after")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        """Keep provider failures explicit and visible."""
        if not value.strip():
            raise ValueError("provider refusal message must not be blank")
        return value


type CompletionFailure = SchemaRejected | BudgetExceeded | ProviderRefusal
```

**코드에서 꼭 볼 것**

- `RawProviderResponse`는 스키마 파싱 **전에** 만들어진다 — 다음 두 문서에서 작성할 어댑터인 `_request` 안에서 태어나며, SDK 응답과 우리 파싱 사이의 마지막 공급자 중립 정거장이다. 파싱이 실패해도 모델이 실제로 말한 것은 남는다. `output_text`가 모든 경로에서 메타데이터의 원시 출력 이력에 덧붙기 때문이다.
- 실패 타입 세 개는 각자 자기 경로가 만들 수 있는 근거만 담는다. `SchemaRejected`는 최종 검증 오류와 시도 횟수를 담는다 — 원시 출력은 담지 않으며, 그것은 `ProviderMetadata.raw_outputs`에 있고 결과의 `metadata`를 통해 닿는다. `BudgetExceeded`는 어느 한도를 넘었는지와 사용량, 한도 값을 담는다. `ProviderRefusal`은 거부 사유를 담는다.
- `CompletionFailure`는 세 타입의 합 타입이다. 호출자가 `match`로 분기하면 처리하지 않은 실패 종류를 타입 검사기가 찾아낸다.

왜 선택적 필드를 잔뜩 가진 실패 타입 하나가 아니라 형제 클래스 셋인가? 잡동사니 클래스 하나 — `errors`, `which`, `message`가 전부 선택적인 — 는 이 파일이 고치려는 병을 실패 값 안에 다시 들여온다. 잘못된 필드 조합을 담거나 아무것도 담지 않은 상태가 멀쩡히 생성되기 때문이다. 형제 셋으로 나누면 각 실패는 자기 경로가 실제로 만드는 근거만 담을 수 있다. `raw_outputs`가 `SchemaRejected`에 없는 것도 같은 논리다. 원시 출력은 성공을 포함한 모든 결과에 존재하므로, 그 자리는 실패 분기 하나가 아니라 모든 결과가 갖는 메타데이터다.

> **개념 — Literal 기본값은 편의가 아니라 주장이다**
>
> SchemaRejected는 attempts를 기본값 2를 가진 Literal[2]로 선언한다. 이것은 "보통 이 값"이 아니다 — 이 실패는 정확히 두 번의 시도 뒤에만 존재할 수 있다는 타입 수준의 단언이다. 스키마 거부는 정의상 복구 한 번까지 실패한 뒤의 상태이기 때문이다. 어떤 코드 경로도 다른 횟수로 이 값을 만들 수 없고, 그것을 확인하는 테스트도 필요 없다.
>
> BudgetExceeded는 반대 진술을 반대 장치로 한다. attempts가 1 또는 2로 제약된 엄격한 정수인 이유는, 예산은 첫 호출에서도 복구에서도 죽을 수 있어서다. 거기서 횟수는 변하는 증거이므로 상수가 아니라 범위를 가진 데이터다.
>
> 둘을 나란히 읽으면 서두의 정책 — 복구는 정확히 한 번 — 이 산문이 아니게 된다. 한 번은 상수로, 한 번은 범위로 코드에 새겨져 있다.

> **개념 — 이 합 타입은 일부러 맨몸이다**
>
> 세 구성원 모두 값이 하나 또는 둘인 Literal 타입의 status 필드를 갖는다. 판별 합 타입(discriminated union)이 원하는 바로 그 모양이다. 그런데 이 합 타입은 판별자를 선언하지 않는다. 정적 관점에서는 필요가 없다. 세 클래스에 대한 match는 클래스 자체로 분기하고, 빠진 가지는 어느 쪽이든 타입 검사기가 잡는다.
>
> 판별자가 값을 하는 곳은 런타임, 즉 합 타입을 JSON에서 되파싱할 때다. 판별자가 없으면 Pydantic은 스마트 유니언 채점 — 구성원을 차례로 시도해 가장 잘 맞는 것을 고르는 방식 — 으로 물러난다. 동작은 하지만 오류 메시지가 모든 구성원의 불평을 나열하게 된다. 이 모듈에서 그 경로는 돌지 않는다. 실패 값은 구체 클래스가 이미 정해진 채 파이썬 코드에서 생성되고, JSON에서 CompletionFailure를 되파싱하는 코드는 여기에 없다.
>
> 튜토리얼 6은 같은 모양을 반대 제약 아래에서 만난다 — 그쪽의 사유 합 타입은 저장된 JSON을 실제로 왕복한다 — 그리고 거기서는 판별자를 선언한다. 같은 패턴, 다른 수명주기, 다른 선택.

### 4. 성공과 실패가 동시에 참일 수 없게 한다

#### `app/llm/schemas.py` 완성 — 메타데이터와 결과

**학습 행동 — 불변조건 구현:** `ProviderResult`의 검증기를 직접 구현한다. `status`와 `parsed`, `refusal` 사이의 관계가 핵심이다.

<!-- src: app/llm/schemas.py::ProviderMetadata,ProviderResult -->
```python
class ProviderMetadata(StrictSchema):
    """Trace-ready provider identity, usage, latency, raw output, and retry data."""

    provider: NonBlank
    model_name: NonBlank
    api_url: NonBlank
    input_tokens: NonNegativeInt
    output_tokens: NonNegativeInt
    estimated_cost_usd: NonNegativeDecimal
    request_time_ms: Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
    retries: Annotated[StrictInt, Field(ge=0, le=1)]
    request_ids: tuple[StrictStr, ...]
    llm_output: StrictStr
    raw_outputs: tuple[StrictStr, ...]

    @model_validator(mode="after")
    def validate_attempt_metadata(self) -> Self:
        """Keep final output and retry count consistent with captured attempts."""
        if any(not value.strip() for value in (self.provider, self.model_name, self.api_url)):
            raise ValueError("provider identity fields must not be blank")
        if any(not request_id.strip() for request_id in self.request_ids):
            raise ValueError("request ids must not be blank")
        if not self.raw_outputs:
            raise ValueError("provider metadata requires at least one raw output")
        if len(self.raw_outputs) != self.retries + 1:
            raise ValueError("raw output count must equal retries plus one")
        if self.llm_output != self.raw_outputs[-1]:
            raise ValueError("llm_output must equal the final raw output")
        if len(self.request_ids) > len(self.raw_outputs):
            raise ValueError("request ids cannot outnumber provider attempts")
        return self


class ProviderResult[OutputT: BaseModel](StrictSchema):
    """Typed successful output or typed refusal with trace-ready metadata."""

    status: ProviderStatus
    parsed: OutputT | None
    refusal: CompletionFailure | None
    metadata: ProviderMetadata

    @model_validator(mode="after")
    def validate_result_state(self) -> Self:
        """Require exactly one success output or matching typed refusal."""
        if self.status == "ok":
            if self.parsed is None or self.refusal is not None:
                raise ValueError("successful provider results require only parsed output")
        else:
            if self.parsed is not None or self.refusal is None:
                raise ValueError("failed provider results require only a typed refusal")
            if self.refusal.status != self.status:
                raise ValueError("provider result status must match refusal status")
        return self
```

**코드에서 꼭 볼 것**

- `ProviderResult[OutputT: BaseModel]`은 제네릭이다. 노드마다 다른 출력 스키마를 쓰면서도 경계 타입은 하나로 유지된다.
- `status == "ok"`이면 `parsed`가 있고 `refusal`이 없으며, 실패 상태에서는 반대다. 두 값이 동시에 있거나 동시에 없는 결과는 만들 수 없다.
- `refusal`이 이미 상태를 알고 있는데도 `status`를 최상위에 저장한다 — 의도된 중복이다. 상태를 유도하면 `"ok"` 결과에는 상태가 없어지고 트레이스를 소비하는 쪽마다 그것을 계산해야 한다. 저장하면 모든 결과가 조회 가능한 필드 하나를 갖고, 검증기의 마지막 검사가 이 중복을 어긋남 위험이 아니라 강제된 일치로 바꾼다.
- **`metadata`는 성공과 실패 양쪽에 붙는다. 실패한 호출도 토큰을 소비하고 비용이 발생하므로, 실패 결과의 메타데이터를 버리면 그만큼의 사용량이 예산 집계에서 빠진다.**
- `ProviderMetadata`는 재시도별 요청 ID와 원시 출력을 검증기가 못 박은 수명주기 불변조건 아래 저장한다. 원시 출력 튜플의 길이는 `retries + 1` — 시도당 한 항목, 순서대로 — 이어야 하고, 마지막 원소는 `llm_output`과 같아야 하며, 요청 ID는 시도 수를 넘을 수 없다. 특정 공급자 SDK의 로그에 의존하지 않고 모든 시도를 추적할 수 있다.

### 집중 테스트와 테스트가 지키는 계약

```bash
WORKFLOW_MODULE=app.llm.schemas uv run pytest tests/workflow/test_01_schemas.py -q
```

`WORKFLOW_MODULE` 오버라이드는 하니스를 방금 작성한 모듈로 직접 향하게 한다. 패키지 수준 명령은 튜토리얼 3의 `__init__.py`가 생긴 뒤부터 동작한다.

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 인용 없는 `SUPPORTED` | 근거 없는 지지 답변이 만들어지지 않는다. |
| 인용이 있는 `NOT_IN_DOCS` | 라벨과 근거가 모순되지 않는다. |
| `parsed`와 `refusal`이 동시에 있는 결과 | 성공과 실패가 동시에 참일 수 없다. |
| `float`로 들어온 비용 | 청구 금액에 부동소수 오차가 들어가지 않는다. |
| 모르는 추가 필드 | 경계 값에 오타가 통과하지 않는다. |

저 명령이 실행하는 스위트는 테스트 함수 11개를 담고 있고, 위 표의 다섯 행은 이름이 있는 테스트에 대응한다. 앞의 두 행은 `test_supported_decision_requires_unique_citations_and_non_absent_answer`와 `test_not_in_docs_decision_requires_literal_answer_and_no_citations`다. 셋째 행은 `test_provider_result_requires_exactly_one_output_or_matching_refusal`인데, 이 테스트는 상태가 어긋난 결과와 둘 다 없는 결과를 직접 만들어 본다 — 둘 다 있는 결과는 같은 검증기 분기에서 죽는다. 비용 행은 두 번 못 박힌다. `test_token_pricing_uses_exact_decimal_arithmetic`이 정확한 산술을 증명하고, `test_provider_budget_requires_explicit_strict_limits_and_pricing`이 토큰 수 자리에 불리언을, 그리고 음수 비용을 넣는다. 추가 필드 행은 `extra=True` 사례로, `test_prompt_is_strict_frozen_and_forbids_unknown_fields`가 그것을 넣어 본다. 나머지 테스트들은 공백 관문, 중복 판정, 오류 필수 규칙, 음수 예산 증거, 메타데이터 시도 불변조건을 고정한다 — 이 파일의 모든 계약이 커밋된 테스트 하나 이상으로 검증된다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 타입과 연결해 설명해 본다.

- **경계를 한 곳에 모으지 않으면 노드마다 무엇이 달라지는가?**
  - **답:** 재시도 정책, JSON 파싱, 실패 처리, 토큰 집계가 노드마다 서로 다른 계약을 따르게 된다.
- **복구 프롬프트를 한 번만 보내는 이유는 무엇인가?**
  - **답:** 시도를 늘릴수록 비용과 지연이 선형으로 증가하고, 스키마를 두 번 지키지 못했다면 보통 프롬프트나 스키마를 수정해야 하기 때문이다.
- **`provider_refused`와 `provider_error`를 나누는 이유는 무엇인가?**
  - **답:** 전자는 모델이 의도적으로 거부한 경우이고 후자는 호출이나 인프라가 실패한 경우이므로, 호출자가 원인을 진단하고 대응하려면 둘을 구분해야 한다.
- **실패한 호출의 `metadata`를 버리면 무엇이 새어 나가는가?**
  - **답:** 이미 쓴 토큰, 비용, 지연, 재시도 ID, 원시 출력이 트레이스에서 사라져 소비한 예산이 합계에서 조용히 누락된다.
- **비용에 `Decimal`을 쓰는 이유는 무엇인가?**
  - **답:** 과금 계산에는 이진 부동소수점의 반올림 오차가 없는 정확한 십진 값이 필요하기 때문이다.

---

[모듈 개요](../03-build.md) · [다음: 공급자 경계 →](02-provider.md)
