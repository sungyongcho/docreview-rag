# M4.2 튜토리얼 5 — 예산 가드, 트레이스 변환, 안전한 영속화

관측 타입을 정의했으므로, 이제 그 타입을 채우고 저장하는 파일 세 개를 작성한다. 튜토리얼 4는 모델을 정의하면서 이음새 세 개를 열어 둔 상태다. `StepTrace`를 만들어 주는 코드가 없고, 실행을 언제 멈춰야 하는지 결정하는 것이 없으며, `RunReport`가 데이터베이스로 들어가는 경로도 없다.

열린 이음새 하나하나가 튜토리얼 8의 러너에서 구체적인 실패가 된다. 가드가 없으면 계속 지출하는 실행을 막을 천장이 없다 — 예산 필드는 존재하지만 아무도 읽지 않는다. 트레이스 어댑터가 없으면 공급자 결과를 트레이스로 바꾸는 매핑이 양쪽 타입을 모두 아는 코드에 놓여야 한다 — `app/observability`가 `app.llm`을 import하기 시작하거나, 모든 호출자가 필드 매핑을 손으로 다시 만들어야 한다. 편집이 없으면 프롬프트에 섞여 들어간 API 키가 보고서를 저장하는 순간 평문으로 기록된다.

이 문서가 세우는 불변조건은 이것이다. 모든 실행은 `RunReport`로 끝나고, 편집되지 않은 비밀 값은 `Run`이나 `Trace` 인스턴스 안에 단 한 순간도 존재하지 않는다.

**선행 조건:** 튜토리얼 4에서 `observability/types.py`와 `cost.py`를 작성한 상태여야 한다. 테스트는 이 문서 끝에서 함께 돈다.

### 한도에 도달하면 이미 초과다

예산 가드는 `>=`를 사용한다. `>`가 아니므로 사용량이 한도에 **정확히 도달**한 경우에도 다음 노드를 막는다.

판정 대상이 M4.1의 `_repair_budget_failure`와 같기 때문이다. 이 가드는 이미 사용한 양이 아니라 다음 노드를 실행할 여유가 있는지를 판정하고, 한도를 정확히 채웠다면 남은 여유는 0이다.

`>`가 허용하는 실패는 구체적이다. 남은 토큰이 정확히 0인 채로 노드에 진입하면 요청은 그대로 나가고, 그 요청은 한도를 넘길 수밖에 없다 — 초과가 보장되어 있고, 나중에 어떤 검사가 돌아볼 시점에는 이미 비용을 치른 뒤다. `>=`는 진입 자체를 거부한다. 이 가드는 예방이고, 사후 검사는 회계일 뿐이다.

**이 선택으로 예산 0이 유효한 설정이 된다.** 예산이 0인 실행은 첫 노드에서 결정론적으로 거부되므로, 동작이 정의되지 않은 설정이 아니라 정의된 종료 상태가 된다.

### 트레이스는 프로토콜로 받는다

`step_trace_from_provider_result`는 `ProviderResult`를 import하지 않고, `Protocol` 두 개로 필요한 필드 모양만 기술한다.

**이 방식이 `app/observability`가 `app/llm`에 의존하지 않게 유지한다.** 관측 계층이 특정 공급자 구현을 참조하지 않으므로, 다른 LLM 계층을 추가해도 이 파일은 수정하지 않는다.

이 주장은 함수 하나의 import 목록보다 강한 주장이고, 저장소 루트에서 명령 한 줄로 확인된다.

```bash
grep -rn "app.llm" app/observability/
```

아무것도 출력되지 않는다. 이 함수 하나가 아니라 `app/observability` 패키지 전체가 `app.llm`을 단 한 번도 참조하지 않는다. 의존은 한 방향으로만 흐르고, 이 문서의 테스트도 공급자 계층을 import하지 않는다.

### 트레이스에 키가 들어가면 데이터베이스에 남는다

`llm_output`은 모델이 반환한 원시 문자열이다. 프롬프트에 API 키가 포함됐거나 모델이 요청 헤더를 그대로 출력하면, **그 값이 트레이스에 담겨 데이터베이스에 저장된다.**

그래서 저장 직전에 편집한다. **로그 출력 시점이 아니라 저장 경계에서 편집해야, 자격증명이 데이터베이스에 기록된 적이 없는 상태가 된다.**

흔한 대답인 로깅 필터는 왜 아닌가. 필터는 필터를 거쳐 로그를 남기는 경로만 지킨다. 데이터베이스 쓰기는 별개의 경로이고, 앞으로 트레이스를 만들 모든 코드가 필터 설치를 기억해야 한다. 저장 경계는 길목이다 — 저장되는 모든 바이트가 `report_to_records`를 지나므로, 이음새 하나가 현재와 미래의 모든 생산자를 지킨다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `pre_node_budget_guard` | 판정 규칙을 **직접 구현** | `>=`가 예산 0을 유효하게 만드는 법 |
| `Protocol` 둘 | **설계 결정 확인** | 의존 방향을 뒤집지 않고 타입을 받는 법 |
| `step_trace_from_provider_result` | **필드 매핑 작성** | 공급자 결과가 트레이스가 되는 지점 |
| `redact_sensitive_text` | 편집 규칙을 **직접 구현** | 평범한 텍스트를 지우지 않고 자격증명만 지우는 법 |
| `persist_run_report` | **호출 순서 검토** | 편집이 저장보다 앞이어야 하는 이유 |

### 1. `>=`가 예산 0을 유효하게 만든다

#### `app/observability/budget.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** 이 파일에 함수가 하나뿐이라는 점을 확인한다. 예산 판정이 한 곳에만 존재한다는 뜻이다.

```python
"""The single cumulative budget guard used before workflow node entry."""

from __future__ import annotations

from typing import Literal

from app.observability.types import (
    Budget,
    RunReport,
    StepTrace,
    WorkflowNode,
    build_run_report,
    validate_elapsed_seconds,
)

BudgetResource = Literal["iterations", "input_tokens", "output_tokens", "wall_clock_s"]

```

#### `app/observability/budget.py` 완성 — 예산 가드

**학습 행동 — 판정 규칙 구현:** `observed`와 `limits` 두 딕셔너리를 만들고 비교하는 구조를 직접 구현한다. 두 딕셔너리의 키가 같아야 한다는 점을 확인한다.

<!-- src: app/observability/budget.py::pre_node_budget_guard -->
```python
def pre_node_budget_guard(
    *,
    run_id: str,
    node: WorkflowNode,
    budget: Budget,
    elapsed_seconds: float,
    system_prompt: str,
    node_path: tuple[WorkflowNode, ...] | list[WorkflowNode],
    steps: tuple[StepTrace, ...] | list[StepTrace],
) -> RunReport | None:
    """Return a structured refusal when any cumulative hard limit is exhausted.

    This is the only budget-enforcement point: call it immediately before a node.
    Equality blocks entry because no capacity remains, which also makes a zero budget
    a valid configuration that deterministically refuses the first node.
    """
    elapsed = validate_elapsed_seconds(elapsed_seconds)
    trace_values = tuple(steps)
    observed: dict[BudgetResource, int | float] = {
        "iterations": len(node_path),
        "input_tokens": sum(trace.input_tokens for trace in trace_values),
        "output_tokens": sum(trace.output_tokens for trace in trace_values),
        "wall_clock_s": elapsed,
    }
    limits: dict[BudgetResource, int | float] = {
        "iterations": budget.max_iterations,
        "input_tokens": budget.max_input_tokens,
        "output_tokens": budget.max_output_tokens,
        "wall_clock_s": budget.max_wall_clock_s,
    }

    exhausted: BudgetResource | None = next(
        (resource for resource in limits if observed[resource] >= limits[resource]),
        None,
    )
    if exhausted is None:
        return None

    return build_run_report(
        run_id=run_id,
        status="budget_exceeded",
        total_time_seconds=elapsed,
        system_prompt=system_prompt,
        node_path=node_path,
        steps=trace_values,
        report={
            "reason": {
                "code": "budget_exceeded",
                "resource": exhausted,
                "limit": limits[exhausted],
                "observed": observed[exhausted],
                "blocked_node": node,
            }
        },
    )
```

**코드에서 꼭 볼 것**

- `observed`와 `limits`는 키가 같은 두 딕셔너리지만, 런타임 보호는 **한 방향뿐**이다. 컴프리헨션이 `limits`를 순회하며 `observed`를 인덱싱하므로, `limits`에만 자원을 추가하면 `KeyError`가 요란하게 나지만, `observed`에만 추가하면 비교 자체가 조용히 생략된다. 실제로 두 딕셔너리를 맞춰 주는 것은 `BudgetResource` Literal이다 — 오타가 나거나 목록에 없는 키는 코드가 실행되기 전에 타입 검사에서 걸린다.
- `next((... for resource in limits if ...), None)`은 **처음 소진된** 자원 하나를 찾는다. 보고서에 기록하는 소진 자원이 하나이므로 전체를 수집하지 않는다.
- `>=` 비교가 예산 0을 유효한 설정으로 만든다. 예산이 0이면 첫 노드가 결정론적으로 거부된다.
- 반환값은 `RunReport | None`이다. 예외가 아니라 값이므로 호출자가 `if report:` 분기로 종료 경로를 처리한다.

> **개념 — 딕셔너리 순서가 곧 우선순위 규칙이다**
>
> 파이썬 딕셔너리는 삽입 순서대로 순회하므로, 제너레이터 식은 limits 리터럴에 적힌 순서 그대로 자원을 검사한다. 반복 횟수, 입력 토큰, 출력 토큰, 벽시계 시간 순이다. 여러 자원이 동시에 소진되면 보고서에는 이 순서에서 앞서는 자원이 기록된다 — 예산 0 테스트는 네 자원을 동시에 소진시키는데 언제나 반복 횟수 사유를 돌려받는다. 리터럴의 순서를 바꾸면 저장된 보고서의 내용이 바뀐다. 이 순서는 서식이 아니라 딕셔너리 리터럴에 부호화된 관측 가능한 동작이다.

왜 타입 있는 예외를 던지지 않고 보고서를 반환하는가. 차단된 실행은 복구해야 할 오류가 아니라 실행의 정상적인 종료 상태 중 하나이고, 다른 모든 종료와 똑같이 완전한 형태를 갖춰야 하기 때문이다. 예외로 만들면 모든 호출자가 그것을 잡아서 보고서를 다시 조립해야 한다. `RunReport | None`을 반환하면 "모든 종료 상태는 `RunReport`다"가 관례가 아니라 구조가 된다.

가드가 반환하는 보고서는 경고가 아니라 종착점이다. 호출자는 이것을 실행의 최종 보고서로 그대로 반환하고 차단된 노드는 실행되지 않는다 — 튜토리얼 8이 모든 노드 앞에 정확히 이 가드-반환 패턴을 배선한다. 거부는 "진입한 노드"와 "시도된 노드"도 구분한다. `tests/workflow/test_03_observability.py`에서 노드 두 개를 마친 뒤 `check` 진입이 차단되면 `node_path`는 `("retrieve", "grade")`에 머물고, 차단된 노드는 `report["reason"]` 안의 `"blocked_node": "check"`로만 나타난다 — 경로는 실행된 것을, 사유는 거부된 것을 기록하므로 반복 횟수 집계가 정직하게 유지된다.

### 2. 의존 방향을 뒤집지 않는다

#### `app/observability/trace.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import 목록에 `app.llm`이 없다는 점을 확인한다.

```python
"""Adapters from provider results into strict observability traces."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any, Protocol

from pydantic import BaseModel

from app.observability.types import StepTrace, WorkflowNode

```

#### `app/observability/trace.py` 확장 — 구조적 타입

**학습 행동 — 설계 결정 확인:** `Protocol`이 명시적 상속과 어떻게 다른지 확인한다.

<!-- src: app/observability/trace.py::ProviderMetadataLike,ProviderResultLike -->
```python
class ProviderMetadataLike(Protocol):
    """Minimum trace-ready metadata required from an LLM provider boundary."""

    model_name: str
    api_url: str
    input_tokens: int
    output_tokens: int
    request_time_ms: float
    llm_output: str
    retries: int


class ProviderResultLike(Protocol):
    """Minimum typed provider result needed to retain a refusal reason."""

    status: str
    metadata: ProviderMetadataLike
    refusal: object | None
```

**코드에서 꼭 볼 것**

- `Protocol`은 **구조적** 타입이다. `ProviderResult`가 이 프로토콜을 상속한다고 선언하지 않아도 필드 모양이 맞으면 타입 검사를 통과한다.
- 그래서 `app/observability`가 `app/llm`을 참조하지 않는다. 의존이 한 방향으로만 흐른다.

> **개념 — 구조적 타이핑은 타입 검사기에서 끝난다**
>
> 구조 일치는 코드가 실행되는 시점이 아니라 타입 검사 시점에 확인된다. 이 두 프로토콜은 런타임 검사가 가능하도록 선언되어 있지 않고, 변환 함수도 인자에 어떤 런타임 타입 검사도 하지 않는다 — 선언한 속성을 그대로 읽어서 흘려보낼 뿐이다. 런타임 관문은 의도적으로 한 층 아래에 있다. 그 값들은 결국 트레이스 모델 자신의 엄격한 검증기를 통과해야 한다. 프로토콜은 의존 화살표의 방향을 지키고, 모델은 데이터의 정직함을 지킨다. 층이 둘이고, 실패하는 시점도 둘이다.

테스트 파일이 구조적 주장 그 자체를 보여준다. `test_provider_refusal_mapping_keeps_trace_metadata_and_typed_reason`도 공급자를 import하지 않는다 — 평범한 `SimpleNamespace` 객체를 넣는데, 읽히는 것이 모양뿐이므로 그것으로 `ProviderResultLike`를 만족한다.

#### `app/observability/trace.py` 완성 — 트레이스 변환

**학습 행동 — 필드 매핑 작성:** 공급자 메타데이터의 각 필드가 어느 트레이스 필드로 옮겨지는지 대조하며 작성한다.

<!-- src: app/observability/trace.py::_jsonable_refusal,step_trace_from_provider_result -->
```python
def _jsonable_refusal(refusal: object) -> dict[str, Any]:
    if isinstance(refusal, BaseModel):
        return refusal.model_dump(mode="json")
    if isinstance(refusal, Mapping):
        return dict(refusal)
    return {"message": str(refusal)}


def step_trace_from_provider_result(
    result: ProviderResultLike,
    *,
    step: int,
    node: WorkflowNode,
) -> StepTrace:
    """Map trace-ready provider metadata and typed refusal state without importing it."""
    metadata = result.metadata
    error = None
    if result.status != "ok":
        failure = (
            _jsonable_refusal(result.refusal)
            if result.refusal is not None
            else {"message": "provider returned a non-ok result without refusal details"}
        )
        error = json.dumps(
            {"status": result.status, "refusal": failure},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return StepTrace(
        step=step,
        node=node,
        model_name=metadata.model_name,
        api_url=metadata.api_url,
        input_tokens=metadata.input_tokens,
        output_tokens=metadata.output_tokens,
        request_time_ms=metadata.request_time_ms,
        llm_output=metadata.llm_output,
        retries=metadata.retries,
        error=error,
    )
```

**코드에서 꼭 볼 것**

- `_jsonable_refusal`은 거부 값을 JSON 텍스트가 아니라 **JSON으로 만들 수 있는 파이썬 객체** — 평범한 딕셔너리 — 로 바꾼다. 실패 타입이 Pydantic 모델이라 그대로는 저장할 수 없고, 문자열로의 직렬화는 호출자의 `json.dumps` 호출에서 일어난다.
- 그 `json.dumps` 호출은 `sort_keys=True`와 `separators=(",", ":")`를 넘기므로 평탄화가 정준적이다. 같은 실패 두 건은 바이트까지 같은 문자열이 된다. 테스트가 그 바이트를 그대로 고정한다 — `{"refusal":{"errors":["label is required"],"status":"schema_rejected"},"status":"schema_rejected"}` — 모든 깊이에서 키가 정렬되고 공백이 없으므로, 나중에 저장된 오류를 단순 문자열 비교만으로 묶거나 중복 제거할 수 있다.
- 성공과 실패 모두 트레이스를 만들고, 두 경우는 `error` 필드의 유무로 구분된다. `error`는 성공 경로에서 `None`으로 태어나고, 실패 경로에서는 구조가 아니라 평탄화된 JSON **문자열**이다 — 거부 전체가 텍스트 열 하나에 들어가도록 의도적으로 눌러 담은 것이다. 4절에서 `Trace.error`에 안착하며, 가는 길에 편집을 거친다.

### 3. 자격증명만 지우고 평범한 텍스트는 남긴다

#### `app/observability/persistence.py` 생성 — 모듈 헤더와 패턴

**학습 행동 — 구조 작성:** 정규식 세 개가 각각 어떤 형태의 문자열을 잡는지 확인한다.

```python
"""Secret-safe mapping and transaction-neutral workflow persistence seams."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, Trace
from app.observability.types import JsonValue, RunReport
```

<!-- src: app/observability/persistence.py::REDACTED,_SECRET_ASSIGNMENT -->
```python
REDACTED = "[REDACTED]"
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_BEARER_TOKEN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|password|secret|access[_-]?token)\b\s*[:=]\s*)"
    r"([^\s,;]+)"
)
```

**코드에서 꼭 볼 것**

- 패턴은 세 개다. OpenAI 키 형태, `Bearer` 토큰, 그리고 `api_key: ...` 같은 **대입 형태**이며, 마지막 패턴이 가장 넓은 범위를 잡는다.
- `_SECRET_ASSIGNMENT`에는 캡처 그룹이 둘 있다. 그룹 1은 키 이름과 구분자, 그룹 2는 값이다. 치환식 `rf"\1{REDACTED}"`는 그룹 1만 되돌려 쓰고 그룹 2는 참조하지 않는다 — 값은 언급되지 않음으로써 사라지고, 키 이름은 남는다. 무엇이 편집됐는지가 로그에 보여야 하기 때문이다.

> **개념 — 캡처 그룹과 역참조**
>
> 정규식의 괄호는 자신이 매치한 텍스트를 붙잡아 두며, 여는 괄호 순서대로 1부터 번호가 붙는다. 치환 문자열에서 `\1` 같은 역참조는 그룹 1이 잡은 내용을 그대로 되돌려 붙이므로, 치환이 매치의 일부는 원문 그대로 남기고 나머지는 버릴 수 있다. `(?i)` 접두사는 패턴 전체를 대소문자 무시로 만들어서, 헤더가 키 이름을 대문자로 쓰든 소문자로 쓰든 대입 어휘가 매치된다.

> **개념 — 삭제가 아니라 치환이다**
>
> 여기서의 편집은 비밀 값을 지우는 것이 아니라 눈에 보이는 표식으로 바꾸는 것이다. 이 차이는 나중에 저장된 트레이스를 읽는 사람에게 중요하다. 치환이면 무언가 제거되었다는 사실과 그것이 어떤 종류였는지를 알 수 있다. 삭제면 편집된 값과 애초에 없던 값이 똑같아 보여서, "모델이 키를 흘렸고 우리가 지웠다"와 "키는 처음부터 없었다"를 조사 단계에서 구분할 수 없다. 표식 자체가 감사 기록의 일부다.

왜 일반적인 고엔트로피 탐지기가 아니라 명시적인 형태 세 개인가. 이 시스템은 긴 16진수 문자열을 일부러 저장하기 때문이다. 모든 인용에는 64자리 16진수 `source_sha256`이 붙어 있고, 편집은 바로 그것들이 들어 있는 JSON을 순회한다. 편집 쪽으로 치우친 엔트로피 휴리스틱은 우리 자신의 출처 기록을 지워 버리고, 반대로 치우치면 키를 놓치는데, 어느 쪽 실패도 일어나는 순간에는 보이지 않는다. 닫힌 형태 세 개에 호출자가 넘기는 `secret_values`를 더한 방식이 규칙을 감사 가능하게 유지한다 — 제거되는 것은 패턴이 말하는 것 그대로이고, 그 이상은 없다.

#### `app/observability/persistence.py` 확장 — 편집

**학습 행동 — 편집 규칙 구현:** `secret_values`를 길이 역순으로 정렬하는 이유를 확인하며 작성한다.

<!-- src: app/observability/persistence.py::redact_sensitive_text,_sanitize_json -->
```python
def redact_sensitive_text(text: str, *, secret_values: Iterable[str] = ()) -> str:
    """Preserve ordinary text while removing explicit and recognizable credentials."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    secrets: list[str] = []
    for secret in secret_values:
        if not isinstance(secret, str) or not secret:
            raise ValueError("secret_values must contain nonempty strings")
        secrets.append(secret)
    redacted = text
    for secret in sorted(set(secrets), key=len, reverse=True):
        redacted = redacted.replace(secret, REDACTED)
    redacted = _OPENAI_KEY.sub(REDACTED, redacted)
    redacted = _BEARER_TOKEN.sub(rf"\1{REDACTED}", redacted)
    return _SECRET_ASSIGNMENT.sub(rf"\1{REDACTED}", redacted)


def _sanitize_json(value: JsonValue, *, secret_values: tuple[str, ...]) -> JsonValue:
    if isinstance(value, str):
        return redact_sensitive_text(value, secret_values=secret_values)
    if isinstance(value, Mapping):
        return {
            redact_sensitive_text(str(key), secret_values=secret_values): _sanitize_json(
                child,
                secret_values=secret_values,
            )
            for key, child in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_json(child, secret_values=secret_values) for child in value]
    return value
```

**코드에서 꼭 볼 것**

- `sorted(set(secrets), key=len, reverse=True)`가 **긴 비밀 문자열부터** 치환한다. 짧은 문자열이 먼저 치환되면 그것을 포함한 긴 비밀은 일부만 지워지고 나머지 문자열이 그대로 남는다.
- `secret_values`의 타입은 `Iterable[str]`이고, 검증 루프에서 리스트로 실체화된다. 이터러블은 한 번만 소비되는 제너레이터일 수 있는데, 값들은 정렬 치환 단계에서 다시 필요하다 — 같은 제너레이터로 검증과 치환을 모두 하려 들면 치환 시점에는 이미 소진되어 있다.
- `_sanitize_json`은 딕셔너리 **키도** 편집한다. 키 이름 자체에 토큰이 들어가는 경우가 있다.
- 재귀는 중첩 구조 전체를 순회한다 — 다만 어느 구조인지 보라. `StepTrace`에는 느슨한 JSON 필드가 없다. 깊이가 정해지지 않은 값은 `RunReport.report`이고, `_sanitize_json`은 정확히 그 하나의 느슨한 필드를 위해 존재한다.

패턴 세 개와 긴 것 우선 규칙은 믿는 대신 눈으로 볼 수 있다. 저장소 루트에서 실행한다.

```bash
uv run python -c "
from app.observability.persistence import redact_sensitive_text as r
print(r('send Bearer abc.def-123 now'))
print(r('api_key=sk-test, user=alice'))
print(r('pair abcdef123 abcdef', secret_values=['abcdef', 'abcdef123']))
"
```

```text
send Bearer [REDACTED] now
api_key=[REDACTED], user=alice
pair [REDACTED] [REDACTED]
```

한 줄씩 읽는다. `Bearer` 키워드는 남고 뒤의 토큰만 사라졌다. 대입 어휘가 닫혀 있으므로 키 이름과 `user=alice`는 남고 값만 사라졌다. 겹치는 비밀 두 개를 함께 넘기면 긴 것 우선 치환이 잔여물을 남기지 않는다 — 짧은 쪽을 먼저 치환했다면 긴 비밀의 꼬리 `123`이 그대로 서 있었을 것이다.

### 4. 편집이 저장보다 앞이다

#### `app/observability/persistence.py` 완성 — 레코드 변환과 저장

**학습 행동 — 호출 순서 검토:** `report_to_records`가 편집 함수를 어느 시점에 호출하는지 확인한다.

<!-- src: app/observability/persistence.py::report_to_records,persist_run_report -->
```python
def report_to_records(
    report: RunReport,
    *,
    secret_values: Iterable[str] = (),
) -> tuple[Run, tuple[Trace, ...]]:
    """Map a strict report to secret-safe ORM records without database I/O."""
    if not isinstance(report, RunReport):
        raise ValueError("report must be a RunReport")
    secrets = tuple(secret_values)
    run = Run(
        run_id=report.run_id,
        status=report.status,
        iterations=report.iterations,
        total_requests=report.total_requests,
        total_input_tokens=report.total_input_tokens,
        total_output_tokens=report.total_output_tokens,
        total_time_seconds=report.total_time_seconds,
        system_prompt=redact_sensitive_text(
            report.system_prompt,
            secret_values=secrets,
        ),
        node_path=list(report.node_path),
        report=_sanitize_json(report.report, secret_values=secrets),
    )
    traces = tuple(
        Trace(
            run_id=report.run_id,
            step=trace.step,
            node=trace.node,
            model_name=trace.model_name,
            api_url=redact_sensitive_text(trace.api_url, secret_values=secrets),
            input_tokens=trace.input_tokens,
            output_tokens=trace.output_tokens,
            request_time_ms=trace.request_time_ms,
            llm_output=redact_sensitive_text(trace.llm_output, secret_values=secrets),
            retries=trace.retries,
            error=(
                redact_sensitive_text(trace.error, secret_values=secrets)
                if trace.error is not None
                else None
            ),
        )
        for trace in report.steps
    )
    return run, traces


async def persist_run_report(
    session: AsyncSession,
    report: RunReport,
    *,
    secret_values: Iterable[str] = (),
) -> Run:
    """Flush one run and its traces without committing the caller's transaction."""
    run, traces = report_to_records(report, secret_values=secret_values)
    session.add(run)
    session.add_all(traces)
    await session.flush()
    return run
```

**코드에서 꼭 볼 것**

- 편집은 `report_to_records` 안에서 ORM 객체를 만들기 **전에** 실행된다. 편집되지 않은 값이 `Run`이나 `Trace` 인스턴스에 담기는 시점 자체가 없다 — 편집이 레코드의 메서드가 아니라 생성자 인자에 적용되는 변환인 이유도 이것이다. 정리 메서드는 잊을 수 있지만, 여기서는 비밀을 품은 문자열이 객체 안에 단 한 순간도 존재하지 않는다.
- 매핑은 자유 텍스트 필드만 정확히 골라 편집한다. `system_prompt`, `report`, `api_url`, `llm_output`, `error`다. `model_name`은 우리 설정의 닫힌 어휘에서 오고 바깥 텍스트가 흘러들지 않으므로 그대로 통과한다. 반면 URL은 쿼리 문자열에 자격증명을 실을 수 있다 — 편집 테스트는 `api_url`이 `?api_key=...`로 끝나게 넣고 저장값이 깨끗한지 단언한다.
- `node_path=list(report.node_path)`가 보고서의 튜플을 JSON 열에 맞게 변환한다. 매핑 테스트는 `run.node_path == ["retrieve", "grade"]`를 다시 읽어 확인한다 — 순서도 내용도 같고 컨테이너만 다르다.
- `persist_run_report`는 flush만 수행한다. M3.3의 `persist_eval_result`와 같이 커밋은 호출자가 한다.
- `secret_values`를 인자로 받는다. 설정에서 직접 읽지 않으므로 이 파일이 `app.config`에 의존하지 않는다.

> **개념 — flush와 commit의 차이**
>
> flush는 대기 중인 INSERT 문을 호출자의 아직 열려 있는 트랜잭션 안에서 데이터베이스로 보낸다. 그 트랜잭션 안에서는 행이 존재하고 데이터베이스가 생성한 기본 키도 돌아오지만, 아직 아무것도 영속적이지 않다 — 나중에 롤백하면 flush가 쓴 것이 전부 되돌아간다. commit이 영속성을 결정하며, 그 결정은 트랜잭션을 소유한 쪽의 몫이다. flush만 하는 이음새는 조합이 된다. 호출자는 실행 보고서를 자신의 행들과 하나의 원자적 트랜잭션으로 저장할 수도, 함께 버릴 수도 있고, 테스트는 데이터베이스 없이 가짜 세션만으로 이음새 전체를 구동할 수 있다.

`secret_values`는 왜 `Settings`에서 읽지 않고 매개변수인가. 여기서 설정을 읽는 편이 편리하겠지만, 그러면 이 패키지가 파일 세 개에 걸쳐 피해 온 import가 생긴다. 설정 객체는 진짜 API 키가 사는 곳이므로, 그것을 건드리는 순간 관측 계층이 `app.config`에 묶이고 편집 목록이 호출 지점에서 보이지 않게 된다. 매개변수로 받으면 호출자가 어떤 값이 비밀인지 정확히 선언하고, 테스트는 설정 없이 지어낸 비밀 값만으로 편집을 검증한다.

`secret_values`의 여정을 따라가 보면 이렇다. 호출자에게서 들어와 `report_to_records` 첫머리에서 튜플로 한 번 고정되고, 그 뒤 다섯 군데 편집 지점 전부에 명시적으로 꿰어진다. 이 반복은 의도적으로 기계적이다 — 각 지점이 자유 텍스트 열이고, 여기서 한 곳을 빠뜨리면 타입 검사기가 볼 수 없는 유출이 되므로, 매개변수 전달이 그토록 반복적으로 보이는 것이다.

#### `app/observability/__init__.py` 생성 — 공개 API

**학습 행동 — 구조 작성:** M4.2가 공개하는 표면을 확인하며 작성한다.

```python
"""Public contracts for M4 workflow observability and budget enforcement."""

from app.observability.budget import BudgetResource, pre_node_budget_guard
from app.observability.cost import (
    MODEL_PRICES,
    ModelPrice,
    UnknownModelPriceError,
    estimate_cost_usd,
    estimate_trace_cost_usd,
)
from app.observability.persistence import (
    REDACTED,
    persist_run_report,
    redact_sensitive_text,
    report_to_records,
)
from app.observability.trace import step_trace_from_provider_result
from app.observability.types import (
    Budget,
    JsonObject,
    RunReport,
    RunStatus,
    StepTrace,
    WorkflowNode,
    build_run_report,
)

__all__ = [
    "MODEL_PRICES",
    "REDACTED",
    "Budget",
    "BudgetResource",
    "JsonObject",
    "ModelPrice",
    "RunReport",
    "RunStatus",
    "StepTrace",
    "UnknownModelPriceError",
    "WorkflowNode",
    "build_run_report",
    "estimate_cost_usd",
    "estimate_trace_cost_usd",
    "persist_run_report",
    "pre_node_budget_guard",
    "redact_sensitive_text",
    "report_to_records",
    "step_trace_from_provider_result",
]
```

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/workflow/test_03_observability.py -q
```

이 파일에는 389줄에 테스트 함수 13개가 있고, 튜토리얼 4의 모델과 이 문서의 파일 세 개를 함께 덮는다. 상단의 `_trace`와 `_report` 픽스처가 정준 트레이스 하나와 정준 보고서 하나를 만들고, 아래 계약 전부가 그것을 상대로 검증된다. 셋은 전문을 읽을 가치가 있다. 가드의 경계는 `test_zero_budget_refuses_the_first_node_and_negative_budgets_are_invalid`, 보고서 하나로 편집 경로 전체를 재는 것은 `test_persistence_mapping_preserves_provenance_and_redacts_secrets`, 그리고 `test_persistence_flushes_without_committing_or_live_services`는 손으로 쓴 기록용 세션으로 `persist_run_report`를 구동한다 — 데이터베이스도 I/O도 없이, flush만 하는 이음새라서 가능한 방식 그대로다.

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 한도에 정확히 도달한 사용량 | 여유가 0이면 다음 노드가 막힌다. |
| 예산 0 설정 | 첫 노드부터 결정론적으로 거부한다. |
| 트레이스와 어긋난 합계 | 집계가 항상 트레이스에서 유도된다. |
| `llm_output`에 섞인 API 키 | 자격증명이 데이터베이스에 저장되지 않는다. |
| 서로 겹치는 비밀 문자열 | 긴 비밀이 부분만 지워지지 않는다. |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 함수와 연결해 설명해 본다.

- **예산 가드가 `>=`를 쓰고 `>`를 쓰지 않으면 무엇이 유효한 설정이 되는가?**
  - **답:** 예산 0이 유효해지며 첫 노드를 실행하기 전에 결정론적으로 차단할 수 있다. 네 자원이 동시에 소진된 상태이므로 거부 사유에는 limits 리터럴의 첫 키인 `iterations`가 기록된다.
- **`Protocol`을 쓰면 어떤 의존 방향이 유지되는가?**
  - **답:** `app.observability`는 필요한 구조에만 의존하고 `app.llm`을 모른 채 유지되며, 공급자 결과는 상속 없이 그 구조만 만족한다.
- **비밀 문자열을 길이 역순으로 치환하는 이유는 무엇인가?**
  - **답:** 겹치는 짧은 비밀을 먼저 바꾸면 긴 비밀의 일부만 지워지고 나머지가 노출될 수 있기 때문이다.
- **편집을 ORM 객체 생성 뒤로 옮기면 무엇이 깨지는가?**
  - **답:** 편집되지 않은 비밀이 이미 `Run`이나 `Trace` 객체 안에 존재하게 되어 민감한 값이 저장 경계를 넘지 않는다는 보장이 깨진다.
- **`persist_run_report`가 커밋하지 않는 이유는 무엇인가?**
  - **답:** 호출자가 트랜잭션을 소유하고 주변 작업과 함께 언제 원자적으로 커밋할지 결정해야 하므로 이 함수는 플러시만 한다.

---

[← 이전: 관측 타입](04-observability-types.md) · [모듈 개요](../03-build.md) · [다음: 워크플로 타입 →](06-workflow-types.md)
