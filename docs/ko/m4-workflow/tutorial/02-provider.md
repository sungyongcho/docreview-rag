# M4.1 튜토리얼 2 — 파싱·복구·예산 판정을 함수로 떼어낸다

튜토리얼 1은 실패를 값으로 만들었다. `ProviderResult`는 파싱된 객체나 타입 있는 거부 중 정확히 하나만 담는다 — 둘 다 담거나 둘 다 비우는 조합은 `validate_result_state`가 거부한다. 열려 있는 질문은 그 값들이 어디서 오느냐다. 모델이 실제로 반환한 문자열을 그 값 중 하나로 바꾸는 코드는 아직 없다.

이 계층을 건너뛰면 호출자마다 그 변환을 즉흥으로 만든다. 한 노드는 맨 `json.loads`로 파싱해 `NaN`이 비용 합계로 흘러들게 두고, 다른 노드는 제멋대로 재시도하고, 또 다른 노드는 실패를 설명해 줄 원시 출력을 버린다. 튜토리얼 1이 서두에서 나열한 노드별 혼란이 호출 지점 하나씩 그대로 재조립되는 것이다.

이 문서는 공급자 경계의 **판단 로직**을 작성한다. 클래스가 아니라 모듈 수준 순수 함수 일곱 개이며, 어느 것을 직접 구현하는지는 아래 표가 표시한다. 이 함수들이 지키는 불변조건은 한 문장으로 검증 가능하다. **어떤 코드 경로도 파싱된 값과 검증 오류를 동시에 반환하지 않는다.** `_parse_output`은 모델 인스턴스와 빈 오류 튜플, 또는 `None`과 한 개 이상의 오류 문자열 중 하나만 돌려주며, 이 배타성이 다음 문서의 `complete()`가 모든 종료 지점에서 `validate_result_state`를 통과하는 근거다.

작성 순서에 이유가 있다. `LLMProvider` 추상 클래스는 212줄(`provider.py:152-363`)이고, 그 안에서 내리는 판단은 모두 이 문서의 함수들에 들어 있다. 함수를 먼저 작성하면 클래스에는 **호출 순서만** 남는다. 순수 함수가 여기서 사 주는 것도 그것이다. 판단 하나하나를 이벤트 루프도, 네트워크도, 클래스 인스턴스도 없이 평범한 함수 호출로 검증할 수 있다.

**선행 조건:** 튜토리얼 1의 `uv run pytest tests/workflow/test_01_schemas.py -q`가 통과해야 한다.

### 모델이 돌려준 JSON을 어떻게 믿을 것인가

구조화 출력이라도 공급자가 반환하는 것은 문자열이다. 파싱 단계에서 어긋날 수 있는 경우가 세 가지다.

- JSON 자체가 깨졌다
- JSON은 맞는데 스키마와 다르다
- 둘 다 맞는데 **JSON 표준에 없는 값**이 들어 있다 (`NaN`, `Infinity`)

세 번째가 가장 조용하다. 파이썬 `json`은 `NaN`을 기본으로 허용하므로 파싱은 성공하고, 그 값이 비용 계산이나 점수에 들어가면 이후의 모든 비교가 거짓이 된다. **항상 통과하는 예산 검사는 존재하지 않는 예산과 같다.** 앞의 두 경우는 최소한 소리라도 내지만, 이 경우는 파싱 단계에 아무 신호도 남기지 않는다.

세 경우 모두 아래 `_parse_output`에서 각자의 타입 있는 종료 경로를 얻고, 어느 경로든 복구 프롬프트가 활용할 수 있는 오류 문자열을 만든다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| 모듈 헤더와 시계 별칭 | **구조 작성** | 시계가 주입 가능한 이유 |
| `_parse_output` | 파싱 가드를 **직접 구현** | JSON 표준 밖 값을 막는 지점 |
| `_repair_prompt` | **필드 매핑 작성** | 복구 프롬프트가 모델에게 주는 정보 |
| 예산 판정 두 함수 | 경계 규칙을 **직접 구현** | `>`와 `>=`가 갈리는 이유 |

### 1. 모듈 헤더와 주입 가능한 시계

#### `app/llm/provider.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록에서 `Decimal`과 `ValidationError`를 확인한다. 비용 계산과 스키마 검증이 이 파일에서 함께 처리된다는 뜻이다. 여기서 타이핑하는 헤더는 M4.1의 완성형이다. 튜토리얼 9가 strict 디코딩 경로를 들여올 때 SDK의 strict 포맷 타입 import 하나가 더해진다.

```python
"""Async structured-output providers with one repair and fail-closed refusal."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from decimal import Decimal
import json
import time
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.llm.schemas import (
    BudgetExceeded,
    CompletionFailure,
    Prompt,
    ProviderBudget,
    ProviderMetadata,
    ProviderRefusal,
    ProviderResult,
    RawProviderResponse,
    SchemaRejected,
)
```

#### `app/llm/provider.py` 확장 — 시계 별칭

**학습 행동 — 구조 작성:** M3의 평가 CLI(`app/evals/retrieval_eval.py`)가 `Clock`에 사용한 것과 같은 별칭 형태다.

<!-- src: app/llm/provider.py::Clock -->
```python
type Clock = Callable[[], int]
```

**코드에서 꼭 볼 것**

- `Clock`은 나노초 정수를 반환한다. **부동소수 초 단위를 쓰면 짧은 호출의 지연 시간이 유효 자릿수 아래로 내려가 0에 가깝게 기록된다.**
- 별칭이 존재하는 이유는 시계를 주입하기 위해서다. `complete()`는 시도마다 시계를 두 번 읽어 경과 시간을 재는데, 운영 기본값 `time.perf_counter_ns`로는 테스트가 "0 이상인 어떤 수"만 단언할 수 있다. 테스트 스위트는 읽을 때마다 정확히 1,000,000ns씩 전진하는 `TickClock`을 주입하고, 정상 경로 테스트는 `request_time_ms == 1.0`을 못 박는다. 지연 시간이 결정론적으로 단언 가능한 값이 된다.

### 2. JSON 표준 밖 값을 막는다

#### `app/llm/provider.py` 확장 — 출력 파싱

**학습 행동 — 파싱 가드 구현:** `_json_object`와 `_invalid_json_constant`를 직접 구현한다. `parse_constant`가 어떤 입력에서 호출되는지 확인한다.

<!-- src: app/llm/provider.py::_json_object,_parse_output -->
```python
def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _invalid_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _validation_errors(error: ValidationError) -> tuple[str, ...]:
    messages = []
    for issue in error.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in issue["loc"]) or "$"
        messages.append(f"{location}: {issue['msg']} [{issue['type']}]")
    return tuple(messages)


def _parse_output[OutputT: BaseModel](
    output_text: str,
    schema: type[OutputT],
) -> tuple[OutputT | None, tuple[str, ...]]:
    try:
        value = json.loads(
            output_text,
            object_pairs_hook=_json_object,
            parse_constant=_invalid_json_constant,
        )
        canonical = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        return schema.model_validate_json(canonical, strict=True), ()
    except ValidationError as error:
        return None, _validation_errors(error)
    except json.JSONDecodeError as error:
        message = f"$: {error.msg} at line {error.lineno} column {error.colno} [json_invalid]"
        return None, (message,)
    except ValueError as error:
        return None, (f"$: {error} [json_invalid]",)
```

> **개념 — 왜 파싱한 것을 다시 직렬화해 다시 파싱하는가**
>
> 두 요구가 서로 반대 방향을 가리킨다. 중복 키는 파싱 도중에만 보인다. 파이썬 `json.loads`는 키-값 쌍이 dict로 접히기 전에 `object_pairs_hook`으로 전부 노출하지만, Pydantic의 자체 JSON 파서는 마지막 중복만 남기고 아무것도 보고하지 않는다. 반면 엄격 디코딩은 JSON 텍스트를 기준으로 정의된다. `"5"`가 정수로 바뀌지 않게 막는 규칙은 `model_validate_json`이 `strict=True`에서 적용하는 규칙표이고, 이미 파싱된 dict를 넘기면 Pydantic은 파이썬 객체용의 다른 규칙표를 적용한다.
>
> 둘을 다 만족하려면 우회로가 강제된다. 훅을 걸어 파싱하고, 정규 형태로 다시 직렬화하고, 그 텍스트를 검증한다. 꼬리를 `schema.model_validate(value)`로 "단순화"해도 정상 출력을 넣는 테스트는 전부 통과한다 — 허용되는 강제 변환이 조용히 달라질 뿐이다. `json.dumps` 단계의 `allow_nan=False`는 `parse_constant` 뒤에 선 두 번째 관문이다. 다른 경로로 들어온 유한하지 않은 float가 있어도 스키마가 보는 텍스트로는 직렬화될 수 없다.

> **개념 — `NaN`은 JSON이 아니다**
>
> JSON 표준인 RFC 8259에는 유한하지 않은 수를 표현하는 방법 자체가 없다. `NaN`, `Infinity`, `-Infinity`는 아예 JSON이 아니며, CPython의 `json` 모듈이 문서화된 확장으로 받아 줄 뿐이다. 그래서 "모델이 잘못된 JSON을 반환하면 파싱이 실패한다"는 방어가 여기서는 작동하지 않는다 — 파싱이 성공해 버린다. `parse_constant`는 파서가 정확히 이 세 토큰에서만, 그 외에는 절대 부르지 않는 훅이므로, 그 안에서 예외를 던지면 확장이 표준이 말하는 그대로의 오류로 되돌아간다.

**코드에서 꼭 볼 것**

- `parse_constant=_invalid_json_constant`는 파서가 `NaN`, `Infinity`, `-Infinity`를 만났을 때 호출된다. 파이썬 `json`은 이 세 값을 기본으로 **허용**하므로, 이 훅으로 막지 않으면 그대로 통과한다.
- `object_pairs_hook=_json_object`가 중복 키를 거부한다. M3.1의 골든 로더와 같은 방어이며, 모델이 같은 키를 두 번 출력하면 기본 파서는 뒤의 값만 남긴다.
- `_validation_errors`는 Pydantic 오류를 문자열 튜플로 정리한다. 각 오류의 `loc` 경로를 점으로 이어 붙이고(`answer.label`), 최상위 값 자체가 문제일 때는 JSONPath에서 문서 루트를 가리키는 이름인 `$`로 대신한다. 이 튜플의 수명은 여기서 끝나지 않는다. 복구 프롬프트 본문에 `_repair_prompt`가 접어 넣는 것은 첫 시도의 튜플이고, 두 번째 시도마저 실패하면 그 마지막 파싱이 만든 튜플이 `SchemaRejected.errors`에 실려 호출자에게 반환된다 — 시도마다 파싱이 변수를 다시 묶으므로 두 튜플은 같은 객체가 아니다.
- 세 `except` 절의 순서는 의도된 것이다. `json.JSONDecodeError`는 `ValueError`의 하위 클래스이므로 구체적인 절이 먼저 와야 한다. 마지막 두 절을 뒤집으면 깨진 JSON이 전부 맨 `ValueError` 절로 빨려 들어가 전용 절은 죽은 코드가 되고, 깨진 JSON 메시지의 형식을 이 모듈이 더 이상 통제하지 못하게 된다. 행과 열 정보 자체는 살아남는다 — 디코드 오류의 자체 메시지가 이미 담고 있기 때문이다 — 다만 그것은 표준 라이브러리가 우연히 그렇게 표현해 줄 뿐, 이 모듈이 선택한 형식이 아니게 된다.
- 최상위 값이 객체가 아닌 경우는 훅이 잡지 **못한다**. `object_pairs_hook`은 객체에서만 발화하므로, 모델이 배열이나 맨 문자열을 반환하면 `json.loads`를 통과하고 `json.dumps`도 살아남아 `model_validate_json`이 거부한다. `json_invalid` 경로가 아니라 스키마 검증 오류로 나타난다.

조용한 실패 두 가지는 주장으로 남기지 않고 테스트가 고정한다. `tests/workflow/test_02_provider.py`의 `test_non_strict_json_is_repaired_instead_of_silently_interpreted`는 정확히 두 입력 — 기본 파서라면 말없이 `NOT_IN_DOCS`로 접어 버릴 중복 키, 즉 `{"label":"SUPPORTED","label":"NOT_IN_DOCS"}`와, `reason`이 `NaN`인 그 외에는 멀쩡한 객체 — 을 넣고, 각각이 `json_invalid`를 담은 프롬프트로 복구를 한 번 유발하는지(`retries == 1`) 단언한다.

### 3. 복구 프롬프트가 모델에게 주는 정보

#### `app/llm/provider.py` 확장 — 복구 프롬프트

**학습 행동 — 필드 매핑 작성:** 복구 프롬프트에 어떤 정보가 들어가는지 확인하며 작성한다.

<!-- src: app/llm/provider.py::_repair_prompt -->
```python
def _repair_prompt(prompt: Prompt, raw_output: str, errors: Sequence[str]) -> Prompt:
    details = "\n".join(f"- {error}" for error in errors)
    return Prompt(
        system=prompt.system,
        user=(
            f"{prompt.user}\n\n"
            "Your previous structured output failed validation. Repair it once and return "
            "only an object that matches the required schema.\n"
            f"Validation errors:\n{details}\n"
            f"Previous output:\n{raw_output}"
        ),
    )
```

**코드에서 꼭 볼 것**

- 원래 프롬프트, **모델이 반환한 잘못된 출력**, **검증 오류 목록**이 함께 들어간다. 하나라도 빠지면 모델은 무엇을 고쳐야 하는지 알 수 없다. **오류 목록이 빠지면 거부됐다는 사실만 남아 두 번째 시도가 첫 번째를 반복할 가능성이 높아진다.**
- 오류 목록은 설명 문장이 아니라 Pydantic이 만든 필드 경로다(`answer.label: ...`). 모델에게는 이쪽이 더 정밀한 형식이다. 고칠 필드가 서술이 아니라 이름으로 지정된다.
- 바뀌는 것은 `user`뿐이고 `system`은 글자 그대로 재사용된다. 시스템 프롬프트는 과제의 계약이고, 두 번째 시도는 같은 규칙 아래 같은 과제를 풀어야 한다. 시도에 따라 달라지는 지시를 `system`에 덧붙이면 복구 호출은 조용히 다른 과제가 된다. 이번 시도에 속하는 것 — 거부된 출력, 오류 보고 — 은 데이터이고, 데이터는 사용자 턴에 들어간다.
- 오류는 구조화 객체가 아니라 미리 형식을 갖춘 문자열로 이동한다. 프롬프트는 어차피 텍스트이고, 직렬화는 `_validation_errors`가 이미 결정했다. `include_url=False`와 `include_input=False`는 위생 조치다. Pydantic이 만드는 오류 항목에서 문서 링크와 입력 값 반향을 걷어내 각 항목을 가볍게 유지한다. 실패한 출력이 오류마다 반복되지 않고 `Previous output` 블록에 정확히 한 번 나타나는 것은 그보다 한 단계 앞에서 보장된다. 형식화 함수 자체가 각 오류의 위치 경로, 메시지, 유형만 읽기 때문이다.

세 재료가 실제로 도착한다는 것은 테스트가 증명한다. `test_schema_failure_repairs_once_with_errors_and_remaining_budget`는 두 번째 프롬프트에 `failed validation`, Pydantic 메시지 `Field required`, 그리고 거부된 출력 `{"label":"SUPPORTED"}` 자체가 들어 있음을 단언한다.

### 4. `>`와 `>=`가 갈리는 지점

#### `app/llm/provider.py` 확장 — 예산 판정

**학습 행동 — 경계 규칙 구현:** 두 함수를 나란히 놓고 부등호를 비교한다. 두 함수가 판정하는 대상이 다르다는 점이 차이의 이유다.

<!-- src: app/llm/provider.py::_budget_failure,_repair_budget_failure -->
```python
def _budget_failure(
    budget: ProviderBudget,
    *,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: Decimal,
    attempts: int,
) -> BudgetExceeded | None:
    if input_tokens > budget.max_input_tokens:
        return BudgetExceeded(
            which="input_tokens",
            used=input_tokens,
            limit=budget.max_input_tokens,
            attempts=attempts,
        )
    if output_tokens > budget.max_output_tokens:
        return BudgetExceeded(
            which="output_tokens",
            used=output_tokens,
            limit=budget.max_output_tokens,
            attempts=attempts,
        )
    if estimated_cost_usd > budget.max_cost_usd:
        return BudgetExceeded(
            which="estimated_cost_usd",
            used=estimated_cost_usd,
            limit=budget.max_cost_usd,
            attempts=attempts,
        )
    return None


def _repair_budget_failure(
    budget: ProviderBudget,
    *,
    input_tokens: int,
    output_tokens: int,
    estimated_cost_usd: Decimal,
) -> BudgetExceeded | None:
    """Return why a validation repair cannot make another provider request."""
    if input_tokens >= budget.max_input_tokens:
        return BudgetExceeded(
            which="input_tokens",
            used=input_tokens,
            limit=budget.max_input_tokens,
            attempts=1,
        )
    if output_tokens >= budget.max_output_tokens:
        return BudgetExceeded(
            which="output_tokens",
            used=output_tokens,
            limit=budget.max_output_tokens,
            attempts=1,
        )
    priced = budget.pricing.input_per_million_usd > 0 or budget.pricing.output_per_million_usd > 0
    if priced and estimated_cost_usd >= budget.max_cost_usd:
        return BudgetExceeded(
            which="estimated_cost_usd",
            used=estimated_cost_usd,
            limit=budget.max_cost_usd,
            attempts=1,
        )
    return None
```

> **개념 — 사후 판정과 사전 판정**
>
> 두 함수는 서로 다른 시점에 대해 서로 다른 질문에 답한다. `_budget_failure`는 "이미 일어난 일이 너무 비쌌는가"를 묻는다. 과거에 대한 판결이고, 한도에 정확히 닿았다는 것은 한도가 지켜졌다는 뜻이다. `_repair_budget_failure`는 "한 번 더 요청할 여유가 있는가"를 묻는다. 미래에 대한 판결이고, 이미 한도 위에 서 있다면 다음 요청은 반드시 한도를 넘는다. 문자 하나의 차이가 전부를 나른다. 사후 판정이 `>=`를 쓰면 예산 안에 머문 호출을 처벌하고, 사전 판정이 `>`를 쓰면 초과가 보장된 요청을 승인한다.

**코드에서 꼭 볼 것**

- `_budget_failure`는 `>`를, `_repair_budget_failure`는 `>=`를 사용한다. **두 함수가 서로 다른 시점을 판정하기 때문에 부등호도 다르다.**
- `_budget_failure`는 **이미 발생한** 사용량을 판정한다. 한도와 정확히 같은 양을 썼다면 한도를 넘지 않았으므로 초과가 아니다.
- `_repair_budget_failure`는 **호출을 한 번 더 할 수 있는지**를 판정한다. 사용량이 한도에 정확히 도달했다면 다음 호출은 반드시 한도를 넘으므로 그 호출을 미리 막는다.
- 두 판정 함수 모두 예외를 던지지 않고 `BudgetExceeded | None`을 반환한다. 튜토리얼 1이 실패를 값으로 만들었으므로 이 함수들은 그 값을 만들거나 아무것도 만들지 않으며, 다음 문서는 이들을 가드 절로 연결한다. 여기서 예외를 던지면 예산 실패가 다시 예외 채널로 올라가는데, 바로 그 채널을 비워 두는 것이 `complete()`의 존재 이유다.
- `priced` 검사는 비용 판정에만 붙고, 그 소속은 어떤 공급자 클래스도 아닌 **예산**이다. 가격은 호출자가 채우는 `ProviderBudget.pricing`에 있다. 가격표가 전부 0이면 추정치는 0에 머무는데, 0은 "비용 한도에 닿았다"가 아니라 비용이 측정되지 않는다는 뜻이다. `max_cost_usd`까지 0이면 `0 >= 0`이 참이 되어 모든 복구가 영원히 막힌다. 토큰 판정에 같은 가드가 필요 없는 이유는 타입이 말해 준다. `max_input_tokens`와 `max_output_tokens`는 `PositiveInt`라 0이 될 수 없고, `max_cost_usd`는 `NonNegativeDecimal`이라 가격 없는 예산이 자연스럽게 0을 갖는다.

어느 판정 함수도 자신이 몇 번째 시도를 판정하는지 모른다. 숫자는 호출자가 공급한다. 다음 문서에서 `complete()`는 **원래** 한도와 지금까지의 **누적** 사용량을 이 함수들에 넘기고, `model_copy`로 만드는 시도별 축소 사본은 판정 함수가 아니라 전송 계층으로만 보낸다. 테스트 스위트가 이 분리를 측정 가능하게 만든다. 1,000/100 예산에서 첫 시도가 입력 10, 출력 5 토큰을 쓰면, 복구 판정은 10을 1,000과 비교해 재시도를 허용하고, 두 번째 요청은 990과 95로 줄어든 한도를 받는다. 픽스처가 공급하는 가격 — 백만 토큰당 입력 `Decimal("2")`, 출력 `Decimal("10")` — 은 비용 단언을 정확하게 만드는 조건이기도 하다. 정상 경로 테스트는 입력 100, 출력 20 토큰에 대해 `estimated_cost_usd == Decimal("0.0004")`를 못 박는데, float였다면 근사로만 말할 수 있는 산술이다.

두 부등호는 각자의 경계값에서 실제로 실행된다. `test_repair_does_not_start_after_the_first_attempt_exhausts_budget`가 `>=`의 경계다. 입력 한도 10토큰, 정확히 10을 쓴 첫 시도, 복구를 원하는 스키마 실패가 겹치면 `_budget_failure`는 초과를 찾지 못하지만 — `10 > 10`은 거짓이다 — `_repair_budget_failure`가 두 번째 호출을 막고, 결과에는 `used == limit == 10`과 전송된 프롬프트 정확히 하나가 남는다. `test_explicit_usage_and_cost_budgets_fail_closed`는 `>`의 경계다. 입력 9토큰, 출력 4토큰, 비용 `Decimal("0.00001")`의 한도에 입력 10, 출력 5, 비용 `Decimal("0.00007")`인 호출을 대면, 각 사례가 자기 한도를 넘어 `budget_exceeded`로 돌아오고 `parsed is None`이다.

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 함수와 연결해 설명해 본다.

- **파이썬 `json`이 기본으로 허용하는, JSON 표준에 없는 값 셋은 무엇인가?**
  - **답:** `NaN`, `Infinity`, `-Infinity`다. RFC 8259 기준으로는 셋 다 JSON이 아니며, `parse_constant`로 명시적으로 거부하지 않으면 허용된다.
- **`_parse_output`은 왜 파싱된 dict를 Pydantic에 바로 주지 않고 다시 직렬화하는가?**
  - **답:** 중복 키는 `object_pairs_hook`을 건 `json.loads`만 볼 수 있고, 엄격 디코딩은 `model_validate_json`이 받는 JSON 텍스트에 대해서만 정의되므로, 훅으로 파싱하고 정규 형태로 다시 직렬화해 텍스트로 검증한다.
- **복구 프롬프트에 검증 오류 목록이 들어가야 하는 이유는 무엇인가?**
  - **답:** 모델이 원래 프롬프트와 거부된 출력뿐 아니라 정확히 어떤 스키마 규칙을 어겼는지 알아야 고칠 수 있기 때문이다.
- **`_budget_failure`와 `_repair_budget_failure`의 부등호가 다른 이유는 무엇인가?**
  - **답:** `_budget_failure`는 끝난 호출에 대한 사후 판정이라 한도와 정확히 같은 값은 허용해 `>`를 쓴다. `_repair_budget_failure`는 다음 호출에 대한 사전 판정이라 이미 한도에 닿았다면 `>=`로 막는다.
- **가격 없는 예산에서 `priced` 검사가 없으면 무슨 일이 생기는가?**
  - **답:** 가격표가 전부 0이면 비용 추정치가 0에 머물고, `max_cost_usd`까지 0이면 `0 >= 0`이 참이 되어 모든 복구 시도가 막힌다. 토큰 한도는 `PositiveInt`라 0이 될 수 없으므로 같은 문제가 없다.
- **시계가 나노초 정수인 이유는 무엇인가?**
  - **답:** 부동소수점 초 단위에서는 반올림에 묻힐 수 있는 짧은 호출 시간도 보존하기 위해서다.

---

[← 이전: 스키마](01-schemas.md) · [모듈 개요](../03-build.md) · [다음: 공급자 구현 →](03-provider-impl.md)
