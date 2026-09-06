# M4.3 튜토리얼 8 — 러너는 얇아야 한다

튜토리얼 7은 구멍 하나를 의도적으로 남겼다. 순수 노드 네 개가 완성됐지만 그중 어느 것도 스스로 무언가를 호출하지 못한다. `retrieve_node`는 직접 가져올 수 없는 히트를 필요로 하고, `grade_node`와 `check_node`는 직접 요청할 수 없는 공급자 결과를 해석한다. 순수성의 값은 어딘가에서 치러야 하고, 이 파일이 그 계산서다. 노드가 순수 함수이므로 I/O는 모두 러너에 모인다. 러너가 하는 일은 세 가지다. 예산을 검사하고, 공급자를 호출하고, 그 결과를 노드에 전달한다.

이 계층이 없거나 틀리면 실패는 구체적으로 나타난다. 공급자 예외가 이미 태운 토큰의 기록도 없이 호출자까지 새어 나가거나, 예산이 바닥난 뒤에도 호출이 나간다. 그래서 파일 전체가 검증 가능한 불변조건 하나를 향한다. **`run_workflow`의 모든 종료는 `RunReport`이고, 실제로 일어난 모든 공급자 호출은 그 안에 `StepTrace`를 남긴다.** `return` 문이 `run_workflow` 안에 열두 개 있고, 열두 개 모두 `RunReport`를 반환한다.

**선행 조건:** 튜토리얼 7까지 `workflow/prompts.py`와 `nodes.py`를 작성한 상태여야 한다.

### 예산이 두 겹이다

`WorkflowRequest`에는 예산이 두 개 있다. `budget`은 워크플로 전체의 한도이고, `provider_budget`은 호출 하나의 한도다.

노드를 실행하기 전에 워크플로 예산을 검사하고, 통과하면 **토큰** 축에 대해서는 남은 워크플로 예산과 공급자 예산 중 작은 값을 그 호출에 전달한다. 두 예산을 합성하지 않고 공급자 예산만 넘기면 호출 한 번이 워크플로의 토큰 한도 전체를 소진할 수 있다. 비용은 예외다 — 아래 상자에서 다루며, 이 예외를 놓치면 첫 호출 이후의 모든 호출에 대해 잘못된 가정을 하게 된다.

> **개념 — 서로 다른 축 위의 두 예산**
>
> 토큰에서는 두 예산이 실제로 교차한다. 호출당 상한은 실행 내내 고정이고, 워크플로 잔여량은 스텝이 토큰을 쓸수록 줄어들며, 매 호출은 둘 중 최솟값을 받는다. 축이 둘이고 `min`이 하나다.
>
> 비용에는 두 번째 축이 없다. `Budget`의 필드는 반복 횟수, 입력 토큰, 출력 토큰, 벽시계 초 네 개뿐이고 비용 필드는 아예 없다. 그래서 뺄셈은 실행이 지금까지 쓴 비용 전부를 `provider_budget.max_cost_usd`에서 덜어내고, "호출당" 비용 상한은 조용히 실행 전체의 누적 상한이 된다. 첫 호출은 상한 전액까지 쓸 수 있고, 이후의 호출은 앞선 호출들이 남긴 만큼만 받는다.
>
> 같은 객체인데 필드마다 의미가 다르다. `ProviderBudget`을 어디서나 "호출당"으로 읽는 것이 자연스러운 실수이고, 정확히 한 필드에서 그 독해가 틀린다.

### 실패해도 리포트까지 간다

노드가 실패하면 러너는 **이후의 공급자 호출을 전부 건너뛰고** 실행을 그 자리에서 끝낸다. 어디서 끝나는지를 정확히 해야 한다. 세 실패 경로 모두 `_failure_report(...)`를 직접 반환하고, `_failure_report`는 `build_run_report`를 호출한다. `report_node`가 아니다. 리포트 *노드*는 정상 실행의 경로이고, 실패한 실행도 완전한 `RunReport`를 받지만 그 경로로 받지는 않는다.

그러므로 이 절의 제목이 약속하는 보장은 "항상 리포트 노드"가 아니라 "항상 `RunReport`"다. 테스트가 그 차이를 측정한다. 스키마 거부 경로에서 기록되는 `node_path`는 `("retrieve", "grade")`이고, 검색 예외 경로에서는 `("retrieve",)`다. 어느 쪽에도 `"report"` 항목이 없지만, 두 실행 모두 타입화된 실패 리포트로 끝나고 예외로 빠져나가는 경로는 없다.

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `make_session_retriever` | **구조 작성** | 검색을 주입 가능하게 만드는 법 |
| `_remaining_provider_budget` | 예산 합성을 **직접 구현** | 두 예산이 맞물리는 방식 |
| `_failure_report`·`_node_error` | **필드 매핑 작성** | 실패를 리포트로 옮기는 경로 |
| `run_workflow` | 실행 순서를 **직접 구현** | 가드·호출·노드의 반복 구조 |
| `app/workflow/__init__.py` | **구조 작성** | M4가 공개하는 표면 |

### 1. 검색을 주입 가능하게 만든다

#### `app/workflow/runner.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** M2와 M4.1, M4.2, M4.3의 타입이 모두 이 파일로 모인다는 점을 확인한다.

```python
"""Thin deterministic orchestration over four pure workflow nodes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import AnswerDecision, LLMProvider, ProviderBudget, RelevanceJudgment
from app.observability import (
    RunReport,
    WorkflowNode,
    build_run_report,
    pre_node_budget_guard,
    step_trace_from_provider_result,
)
from app.retrieval import (
    DEFAULT_RRF_K,
    ChunkHit,
    EmbeddingProvider as RetrievalEmbeddingProvider,
    RetrievalFilters,
    RetrievalResult,
    retrieve,
)
from app.workflow.nodes import check_node, grade_node, report_node, retrieve_node
from app.workflow.prompts import build_check_prompt, build_grade_prompt
from app.workflow.types import (
    NodeError,
    WorkflowRequest,
    WorkflowState,
    evidence_fetch_k,
    initial_state,
    run_status_for_failure,
)
```

#### `app/workflow/runner.py` 확장 — 시계와 검색기 별칭

**학습 행동 — 설정 스키마 정의:** 이 파일의 `Clock`은 `float`을 반환한다. M3과 M4.1의 시계와 단위가 다른 이유를 확인한다.

<!-- src: app/workflow/runner.py::Clock,Retriever -->
```python
type Clock = Callable[[], float]
type NodeObserver = Callable[[WorkflowNode, WorkflowState], Awaitable[None]]
type Retriever = Callable[
    [str, int, RetrievalFilters],
    Awaitable[RetrievalResult | Sequence[ChunkHit]],
]
```

**코드에서 꼭 볼 것**

- 이 파일의 `Clock`은 초 단위 `float`이고 기본값은 `time.perf_counter`다. M3과 M4.1의 시계는 이름만 같은 **다른** 별칭이다. `app/llm`은 `Clock`을 `int` 반환으로 정의하고 기본값이 `time.perf_counter_ns`, 즉 정수 나노초다. 두 별칭은 서로 다른 모듈에 사는 무관한 타입이고 어느 쪽도 상대를 임포트하지 않는다. 여기서는 워크플로 예산이 `max_wall_clock_s`로 초를 재므로, 이 시계의 단위는 비교 대상인 한도와 곧바로 맞고 둘 사이에 잘못될 변환 단계가 없다.

- `NodeObserver`는 여기서 처음 나오는데 러너 본문 어디에도 설명이 없으니 지금 읽어 둔다. 각 노드가 끝난 뒤 노드 이름과 확정된 상태를 받는 비동기 호출 가능 객체다. `run_workflow`가 `on_node` 인자로 하나를 받아 전이가 완료될 때마다 await한다. 이벤트 시스템 대신 이 함수 타입 하나가 스트리밍 인터페이스의 전부다.

- `Retriever`는 M2의 반환 타입보다 일부러 넓다. `RetrievalResult`도 받고 `ChunkHit`의 일반 시퀀스도 받으므로, 테스트는 완전한 결과 래퍼를 만들지 않고 맨 리스트를 러너에 넘길 수 있다.

#### `app/workflow/runner.py` 확장 — 검색기와 가드

**학습 행동 — 구조 작성:** `make_session_retriever`가 세션을 어디에 보관하는지 확인한다.

<!-- src: app/workflow/runner.py::make_session_retriever,_guard -->
```python
def make_session_retriever(
    session: AsyncSession,
    *,
    provider: RetrievalEmbeddingProvider | None = None,
    candidate_k: int | None = None,
    rrf_k: int = DEFAULT_RRF_K,
) -> Retriever:
    """Close the M2 retrieval service over one caller-owned database session."""

    async def retrieve_for_workflow(
        query: str,
        k: int,
        filters: RetrievalFilters,
    ) -> RetrievalResult:
        return await retrieve(
            session,
            query,
            provider=provider,
            k=k,
            candidate_k=candidate_k,
            filters=filters,
            rrf_k=rrf_k,
        )

    return retrieve_for_workflow


def _elapsed(clock: Clock, started: float) -> float:
    current = clock()
    if isinstance(current, bool) or not isinstance(current, float):
        raise ValueError("workflow clock must return float seconds")
    elapsed = current - started
    if elapsed < 0:
        raise ValueError("workflow clock must be monotonic")
    return elapsed


def _guard(
    state: WorkflowState,
    request: WorkflowRequest,
    node: WorkflowNode,
    *,
    elapsed_seconds: float,
) -> RunReport | None:
    return pre_node_budget_guard(
        run_id=state.run_id,
        node=node,
        budget=request.budget,
        elapsed_seconds=elapsed_seconds,
        system_prompt=state.system_prompt,
        node_path=state.node_path,
        steps=state.steps,
    )
```

**코드에서 꼭 볼 것**

- `make_session_retriever`는 세션을 클로저에 담는다. **그래서 `run_workflow`는 세션 타입을 참조하지 않고 검색을 호출할 수 있고, 워크플로 실행 경로가 데이터베이스 계층에 의존하지 않는다.** M2.7의 어댑터와 같은 구조다.
- `_guard`는 M4.2의 `pre_node_budget_guard`를 감싼 함수이고, 상태에서 인자를 꺼내 전달하는 그 일이 바로 존재 이유다. 가드는 키워드 인자를 일곱 개 받는데 그중 다섯 개는 매번 같은 두 객체에서 읽어 오고, `run_workflow` 안에서 여섯 곳에서 호출된다. 래퍼가 없으면 그 여섯 자리마다 전체 인자 목록이 반복되고, 한 벌만 어긋나도 타입 검사기가 잡지 못하는 예산 버그가 된다.

> **개념 — 의존성 주입으로서의 클로저**
>
> `make_session_retriever`는 데이터를 반환하지 않는다. 안쪽 비동기 함수를 반환한다. 그 함수는 바깥 호출의 변수들 — 세션, 임베딩 공급자, 후보 폭, RRF 상수 — 을 바깥 함수가 반환한 뒤에도 붙들고 있다. 나중에 그 함수를 부르면, 그 값들이 인자로 돌아다니지 않고도 완전히 설정된 검색이 재생된다.
>
> 보상은 시그니처에 있다. 반환된 호출 가능 객체는 인자 세 개짜리 `Retriever` 별칭에 맞으므로, `run_workflow`는 "질의를 히트로 바꾸는 무언가"만 받고 그 이상은 받지 않는다. 세션과 공급자와 튜닝 상수는 호출자의 소관으로 남고, 테스트는 M2 스택 전체 대신 네 줄짜리 비동기 함수를 끼워 넣을 수 있다. 러너는 그 차이를 구분하지 못한다.
>
> M3의 평가 루프가 전략을 바인딩할 때 같은 수를 썼고, 이 모듈의 공급자 문서가 HTTP 클라이언트를 숨기는 방식도 같다. 이제 이것이 "코어가 모르는 채로 I/O를 들여오는 법"에 대한 이 프로젝트의 표준 답이다.

### 2. 두 예산이 맞물리는 방식

#### `app/workflow/runner.py` 확장 — 남은 예산 계산

**학습 행동 — 예산 합성 구현:** `min`을 두 번, `max`를 한 번 사용한다. 각각이 어떤 값을 막는지 확인하며 작성한다.

<!-- src: app/workflow/runner.py::_remaining_provider_budget -->
```python
def _remaining_provider_budget(
    request: WorkflowRequest,
    state: WorkflowState,
) -> ProviderBudget:
    used_input = sum(step.input_tokens for step in state.steps)
    used_output = sum(step.output_tokens for step in state.steps)
    input_remaining = min(
        request.provider_budget.max_input_tokens,
        request.budget.max_input_tokens - used_input,
    )
    output_remaining = min(
        request.provider_budget.max_output_tokens,
        request.budget.max_output_tokens - used_output,
    )
    if input_remaining <= 0 or output_remaining <= 0:
        raise ValueError("pre-node budget guard must run before computing provider allowance")
    spent = request.provider_budget.pricing.estimate(used_input, used_output)
    cost_remaining = max(Decimal(0), request.provider_budget.max_cost_usd - spent)
    return ProviderBudget(
        max_input_tokens=input_remaining,
        max_output_tokens=output_remaining,
        max_cost_usd=cost_remaining,
        pricing=request.provider_budget.pricing,
    )
```

**코드에서 꼭 볼 것**

- 계산식은 `min(provider limit, remaining workflow allowance)`이다 — 그런데 두 피연산자는 의미가 대칭이 아니다. 공급자 한도는 실행 내내 변하지 않는 호출당 고정 상한이고, 워크플로 잔여량은 스텝마다 줄어드는 값이다. 실행 초반에는 대개 고정 상한이 `min`에서 이기고, 후반에는 잔여량이 이긴다. "서로를 넘지 못한다"는 말은 맞지만 아무것도 가르치지 않는다. 중요한 것은 *어느* 피연산자가 언제 구속하는가다.
- 값이 `<= 0`이면 잘라내는 대신 예외를 던진다. **이 지점에 도달했다는 것은 예산 가드가 먼저 실행되지 않았다는 뜻이므로, 0을 그대로 넘기는 대신 구현 오류로 처리해 즉시 드러나게 한다.** 왜 그것이 이 지점에 도달하는 유일한 길인지는 아래 상자가 보여 준다.
- 비용은 예외를 던지는 대신 `max(Decimal(0), ...)`로 하한을 둔다. 토큰과 같은 취급이 불가능한 이유는 가드가 비용을 아예 검사하지 않기 때문이다 — `Budget`에 비용 필드가 없다 — 그래서 비용 상한 초과는 이 줄에서 정당하게 있을 수 있는 상태이지, 가드를 건너뛴 증거가 아니다. 하한 자체도 하중을 받는다. `ProviderBudget`은 `max_cost_usd`를 음수 불가로 검증하므로, `max`가 없으면 초과 지출된 실행은 공급자가 다음 호출을 깔끔하게 거부하는 대신 바로 이 자리에서 모델 생성 중에 죽는다.

> **개념 — 가드가 이 raise를 도달 불가능하게 만드는 이유**
>
> 두 함수는 산술에 합의되어 있다. 노드 전 가드는 관측된 합이 한도보다 크거나 같으면 진입을 막고, 이 함수는 정확히 그 합을 정확히 그 한도에서 뺀다. 그러니 가드가 실행되어 통과했다면 사용량 합계는 전부 워크플로 한도보다 엄격히 작고, 뺄셈의 결과는 최소 토큰 하나다. 호출당 상한은 자기 모델이 양수로 검증하므로 바깥의 `min`도 양수다.
>
> 그래서 이 검사는 잘라내기가 아니라 `raise`다. 런타임 조건을 처리하는 것이 아니라 호출 순서 계약을 단언하는 것이다. 이것을 터뜨리는 유일한 방법은 가드를 먼저 실행하지 않고 이 함수를 부르는 것 — 러너 자체의 버그 — 이고, 예외는 정확히 그럴 때 쓰라고 있다. 가드의 크거나-같음과 이 함수의 양수-잔여 검사가 맞물린 합의는 하중을 받는 구조다. 어느 한쪽을 느슨하게 풀면 토큰 0짜리 예산이 공급자까지 흘러갈 수 있다.

이 함수가 반환하는 값의 수명은 짧고 분명하다. 공급자 호출 직전에 새로 태어나고, 상태에 저장되지 않으며, `provider.complete`가 즉시 소비한다. `complete` 안에서 한 번 더 줄어든다 — 튜토리얼 3의 수리 루프가 다음 요청 전에 각 시도의 지출을 빼기 때문이다 — 그래서 같은 허용량이 두 층위에서 좁아진다. 여기서는 노드마다 한 번, 거기서는 시도마다 한 번.

### 3. 실패를 리포트로 옮긴다

#### `app/workflow/runner.py` 확장 — 실패 리포트

**학습 행동 — 필드 매핑 작성:** `_failure_report`가 M4.2의 어떤 함수를 호출하는지 확인한다.

<!-- src: app/workflow/runner.py::_failure_report,_result_hits -->
```python
def _failure_report(
    state: WorkflowState,
    *,
    elapsed_seconds: float,
) -> RunReport:
    if state.failure is None:
        raise ValueError("failure report requires a typed workflow failure")
    return build_run_report(
        run_id=state.run_id,
        status=run_status_for_failure(state.failure),
        total_time_seconds=elapsed_seconds,
        system_prompt=state.system_prompt,
        node_path=state.node_path,
        steps=state.steps,
        report={"failure": state.failure.model_dump(mode="json")},
    )


def _node_error(node: WorkflowNode, error: Exception) -> NodeError:
    message = str(error)
    if not message.strip():
        message = f"{node} failed without an error message"
    return NodeError(
        node=node,
        error_type=type(error).__name__,
        message=message,
    )


def _result_hits(result: RetrievalResult | Sequence[ChunkHit]) -> tuple[ChunkHit, ...]:
    if isinstance(result, RetrievalResult):
        return result.hits
    if isinstance(result, str | bytes | bytearray) or not isinstance(result, Sequence):
        raise TypeError("retriever must return RetrievalResult or a sequence of ChunkHit")
    return tuple(result)
```

**코드에서 꼭 볼 것**

- `run_status_for_failure`가 워크플로 실패를 M4.2의 `RunStatus`로 변환한다. "한 곳"이라는 주장은 정확히 읽어야 한다. 이 *방향* — 워크플로 실패에서 실행 상태로 — 만 여기 한 곳에 산다. 반대 방향, 즉 공급자 상태를 타입화된 워크플로 실패로 바꾸는 일은 튜토리얼 7의 `nodes.py`에서 일어났다. 방향마다 변환 하나, 각각 한 곳 — 이것이 실제 불변조건이다.
- `_node_error`는 빈 메시지를 대체 문자열로 채운다. `str(error)`가 빈 문자열인 예외는 실제로 있다 — 맨몸의 `raise RuntimeError()` 하나면 충분하다 — 그리고 그대로 기록하면 메시지 필드가 아무것도 말하지 않는 실패 기록이 남는다.
- `_result_hits`는 두 가지 반환 형태를 모두 받는다. M2.7의 `RetrievalResult`는 리스트가 아니라 `.hits`와 전략 메타데이터를 함께 담은 래퍼이고, 첫 분기가 그것을 풀어내는 이유다. 일반 시퀀스도 받되 문자열은 거부한다. 문자열*도* `Sequence`라서, 명시적으로 거부하지 않으면 문자 하나하나가 검색 히트로 받아들여진 뒤 한참 뒤에 훨씬 나쁜 오류로 실패한다.
- `_failure_report`는 건강한 상태를 거부한다. `state.failure`가 `None`일 때 예외를 던지므로, 이 함수로 성공한 실행에서 실패 리포트를 지어내는 일은 불가능하다.

### 4. 가드·호출·노드의 반복 구조

#### `app/workflow/runner.py` 완성 — 워크플로 실행

**학습 행동 — 실행 순서 구현:** 노드 네 개를 순서대로 실행하는 구조를 직접 구현한다. 각 노드 앞에 무엇이 오는지가 핵심이다.

<!-- src: app/workflow/runner.py::run_workflow -->
```python
async def run_workflow(
    request: WorkflowRequest,
    *,
    retriever: Retriever,
    provider: LLMProvider,
    clock: Clock = time.perf_counter,
    on_node: NodeObserver | None = None,
) -> RunReport:
    """Execute retrieve, grade, check, and report with one guard before each node.

    ``on_node`` is awaited after every completed node transition with the node
    name and the committed state, so callers can stream progress; observer
    exceptions propagate to the caller instead of becoming node failures.
    """
    if not isinstance(request, WorkflowRequest):
        raise TypeError("request must be a WorkflowRequest")
    if not isinstance(provider, LLMProvider):
        raise TypeError("provider must implement LLMProvider")

    async def notify(node: WorkflowNode, committed: WorkflowState) -> None:
        if on_node is not None:
            await on_node(node, committed)

    state = initial_state(request)
    started = clock()
    if isinstance(started, bool) or not isinstance(started, float):
        raise ValueError("workflow clock must return float seconds")

    if blocked := _guard(state, request, "retrieve", elapsed_seconds=_elapsed(clock, started)):
        return blocked
    try:
        retrieval = await retriever(state.query, evidence_fetch_k(state), state.filters)
        state = retrieve_node(state, _result_hits(retrieval))
    except Exception as error:
        failure = _node_error("retrieve", error)
        state = state.model_copy(
            update={
                "failure": failure,
                "reasons": (*state.reasons, failure),
                "node_path": (*state.node_path, "retrieve"),
            }
        )
        return _failure_report(state, elapsed_seconds=_elapsed(clock, started))
    await notify("retrieve", state)

    if not state.evidence:
        if blocked := _guard(state, request, "report", elapsed_seconds=_elapsed(clock, started)):
            return blocked
        state = report_node(state)
        await notify("report", state)
        return build_run_report(
            run_id=state.run_id,
            status="ok",
            total_time_seconds=_elapsed(clock, started),
            system_prompt=state.system_prompt,
            node_path=state.node_path,
            steps=state.steps,
            report=state.report.model_dump(mode="json") if state.report else None,
        )

    if blocked := _guard(state, request, "grade", elapsed_seconds=_elapsed(clock, started)):
        return blocked
    try:
        grade_result = await provider.complete(
            build_grade_prompt(state),
            RelevanceJudgment,
            _remaining_provider_budget(request, state),
        )
        grade_trace = step_trace_from_provider_result(
            grade_result,
            step=len(state.steps) + 1,
            node="grade",
        )
        state = state.model_copy(update={"steps": (*state.steps, grade_trace)})
        state = grade_node(state, grade_result)
    except Exception as error:
        failure = _node_error("grade", error)
        state = state.model_copy(
            update={
                "failure": failure,
                "reasons": (*state.reasons, failure),
                "node_path": (*state.node_path, "grade"),
            }
        )
    if state.failure is not None:
        return _failure_report(state, elapsed_seconds=_elapsed(clock, started))
    await notify("grade", state)

    if not state.relevant_chunk_ids:
        if blocked := _guard(state, request, "report", elapsed_seconds=_elapsed(clock, started)):
            return blocked
        state = report_node(state)
        await notify("report", state)
        return build_run_report(
            run_id=state.run_id,
            status="ok",
            total_time_seconds=_elapsed(clock, started),
            system_prompt=state.system_prompt,
            node_path=state.node_path,
            steps=state.steps,
            report=state.report.model_dump(mode="json") if state.report else None,
        )

    if blocked := _guard(state, request, "check", elapsed_seconds=_elapsed(clock, started)):
        return blocked
    try:
        check_result = await provider.complete(
            build_check_prompt(state),
            AnswerDecision,
            _remaining_provider_budget(request, state),
        )
        check_trace = step_trace_from_provider_result(
            check_result,
            step=len(state.steps) + 1,
            node="check",
        )
        state = state.model_copy(update={"steps": (*state.steps, check_trace)})
        state = check_node(state, check_result)
    except Exception as error:
        failure = _node_error("check", error)
        state = state.model_copy(
            update={
                "failure": failure,
                "reasons": (*state.reasons, failure),
                "node_path": (*state.node_path, "check"),
            }
        )
    if state.failure is not None:
        return _failure_report(state, elapsed_seconds=_elapsed(clock, started))
    await notify("check", state)

    if blocked := _guard(state, request, "report", elapsed_seconds=_elapsed(clock, started)):
        return blocked
    state = report_node(state)
    await notify("report", state)
    return build_run_report(
        run_id=state.run_id,
        status="ok",
        total_time_seconds=_elapsed(clock, started),
        system_prompt=state.system_prompt,
        node_path=state.node_path,
        steps=state.steps,
        report=state.report.model_dump(mode="json") if state.report else None,
    )
```

**코드에서 꼭 볼 것**

- 노드마다 **가드, 공급자 호출, 노드** 순서로 진행한다. 가드가 먼저 실행되므로 남은 예산이 없으면 공급자 호출 자체가 일어나지 않는다. 측정된 사실: 예산이 0이면 실행은 아무것도 하기 전에 거부한다 — `node_path == ()`이고, 리포트는 `blocked_node == "retrieve"`를 기록하며, 검색기의 호출 횟수는 0이다.
- 가드가 리포트를 반환하면 러너는 즉시 종료한다. 이때도 `RunReport`가 반환되고 상태는 `budget_exceeded`이며, 이 역시 정의된 종료 경로다. 실행 중간에도 같은 장치가 누적으로 동작한다. 실행에 입력 토큰 다섯 개를 주고 grade가 정확히 다섯을 쓰게 하면, check의 가드가 `resource == "input_tokens"`와 `blocked_node == "check"`로 막는다 — 프롬프트가 정확히 한 번 나간 뒤에.
- `state.failure`가 설정되면 이후의 공급자 호출을 건너뛴다 — 그리고 실행은 그 자리에서 `_failure_report`로 끝나지, `report_node`로 가지 않는다. retrieve 경로는 자기 `except` 안에서 반환하고, grade와 check 경로는 바로 아래의 `if state.failure is not None`으로 떨어져 반환한다. 그래프를 계속 걷는 실패 경로는 없다.
- `try/except`가 공급자 호출과 노드를 함께 감싼다. 노드가 예외를 던지면 `NodeError`로 변환되어 상태에 들어가고 — 워크플로는 거기서 멈추지, 계속 진행하지 않는다. 측정된 사실: `RuntimeError("database unavailable")`를 던지는 검색기는 실행을 상태 `"error"`, `node_path == ("retrieve",)`로 끝내고, 오류 메시지 전문이 리포트에 보존된다.
- 공급자 호출마다 트레이스를 남기는데, 순서가 중요하다. 트레이스는 `grade_node` / `check_node`가 결과를 해석하기 *전에* 상태에 확정된다. 그다음 노드가 거부하거나 예외를 던져도 호출의 트레이스는 이미 남아 있다 — **실패한 호출도 실제 토큰을 소비했고, 이 순서가 실패 경로에서 M4.2의 합계를 정확하게 유지한다.** 측정된 사실: 스키마 거부 실행에서 `total_requests == 2`인데 `len(result.steps) == 1`이고 `retries == 1`이다. 수리 시도는 트레이스 하나 안에 들어 있지, 옆에서 사라지지 않았다.

> **개념 — 가드 줄의 왈러스 연산자**
>
> `:=`는 할당 표현식이다. 한 표현식 안에서 값을 할당하고 그 값을 내놓으므로, `if blocked := ...`는 가드의 판정을 저장하는 동시에 검사한다. 가드는 한도가 소진되면 리포트를, 아니면 `None`을 반환하고 `None`은 거짓으로 평가된다 — 그 줄은 "가드가 막았으면 가드가 만든 것을 반환한다"로 읽힌다.
>
> 이것 없이 쓰면 가드 자리마다 두 줄이 된다 — 할당하고, 검사하고 — 그리고 `run_workflow`에는 가드 자리가 여섯 곳이다. 가드 규율의 비용이 노드당 눈에 보이는 한 줄로 끝나는 것은 바다코끼리 덕분이고, 그래서 반복이 한눈에 읽힐 만큼 작게 유지된다.

docstring은 이것을 "deterministic graph orchestration"이라 부르는데 그래프 자료구조는 어디에도 없다 — 뻔한 대안은 노드 목록을 루프로 도는 것, 아니면 워크플로 그래프 라이브러리다. 기각한 이유는 이 그래프가 작고, 흥미로운 부분이 간선이기 때문이다. 노드 넷, 데이터가 결정하는 단락 둘, 예외 간선 셋, 노드마다 가드 하나. 데이터로 인코딩하면 간선 하나하나가 엔진이 실행하는 설정 항목이 되고 그 엔진까지 읽어야 한다. 직선 코드로 쓰면 열두 개의 종료 각각이 손가락으로 짚을 수 있는 문자 그대로의 `return`이고, 제어 흐름 전체를 `node_path` 단언으로 테스트할 수 있다. 대가는 반복이다 — 가드 블록 여섯 번, 실패 출구 세 번 — 그리고 파일은 그 대가를 의도적으로 치른다. 두 줄짜리 패턴의 반복이 간접화보다 감사하기 싸다. 그래프 엔진이 밥값을 하는 것은 노드가 런타임에 추가되거나 동시에 실행될 때인데, 여기는 둘 다 아니다.

docstring에는 의도적 결정이 하나 더 숨어 있다. `on_node` 관찰자의 예외는 `NodeError`가 되지 않고 **전파된다**. 관찰자는 호출자 자신의 코드다 — UI 갱신, 로그 한 줄 — 그 안의 버그는 호출자의 버그이고, 워크플로 실패로 기록하면 사고가 엉뚱한 주인 밑에 접수된다. 관찰자 테스트는 계약의 나머지 절반을 못 박는다. 성공한 실행에서 관찰자는 네 노드를 스텝 수 `[0, 1, 2, 2]`로 본다 — 검색은 트레이스를 더하지 않고, 공급자 호출마다 하나씩 더해지고, `report`는 더하지 않는다.

두 단락 경로 — `not state.evidence`와 `not state.relevant_chunk_ids` — 는 제3의 상태가 아니라 상태 `"ok"`로 끝난다. 아무것도 못 찾는 것은 어떤 질문에 대한 올바른 답이고, 리포트가 그것을 정직하게 말한다. 빈 검색 실행에서 라벨은 `NOT_IN_DOCS`, 첫 사유 코드는 `retrieval_empty`이며, `node_path == ("retrieve", "report")`에 `steps == ()`이고 `provider.prompts == ()`다 — LLM 호출 둘 다 건너뛴 것이 증명되고, 토큰은 0이 쓰였다. "비었지만 건강함"을 상태 필드에서 `budget_exceeded`·`error`와 구분해 두는 것이, 호출자가 앞의 것을 사고로 취급하지 않으면서 뒤의 둘에만 경보를 걸 수 있게 한다.

`state`는 함수를 지나며 열두 번 묶인다 — 처음 한 번은 `initial_state`가 묶고, 그 뒤의 모든 재바인딩은 노드의 반환값이거나 frozen 모델에 대한 다섯 번의 `model_copy(update=...)` 중 하나다. 아무것도 제자리에서 변형되지 않으므로 어느 줄에서든 현재 `state`는 완결된 확정 스냅샷이다. `notify`가 관찰자에게 건네는 것이 다음 노드가 볼 것과 정확히 같고, 예외가 반쯤 갱신된 상태를 남길 수 없다. 튜토리얼 6의 불변성 약속이 여기서 값어치를 한다.

`run_workflow`가 일부러 하지 않는 일이 하나 있다. 영속화다. `RunReport`를 반환할 뿐 데이터베이스를 건드리지 않는다 — 튜토리얼 5에서 만든 변환 이음새 `report_to_records`와 `persist_run_report`는 호출자의 것이고, 성공 테스트가 `report_to_records(result)`를 직접 호출해 레코드가 리포트를 그대로 비추는지 단언한다. M5의 서비스 계층이 세션과 쓰기를 소유하게 된다. 러너는 데이터베이스 없이도 온전히 쓸 수 있고, 이 파일의 모든 테스트가 순수한 가짜로만 도는 이유가 그것이다.

#### `app/workflow/__init__.py` 생성 — 공개 API

**학습 행동 — 구조 작성:** M5가 의존하게 될 공개 표면을 확인하며 작성한다. 러너 별칭 두 개 — `NodeObserver`와 `Retriever` — 가 모두 올라갔는지 확인한다. `NodeObserver`를 빼먹으면 관찰자에 타입을 붙이려는 호출자마다 `app.workflow.runner`를 직접 임포트하게 된다.

```python
"""Typed evidence-checked workflow with deterministic graph orchestration."""

from app.workflow.nodes import check_node, grade_node, report_node, retrieve_node
from app.workflow.prompts import build_check_prompt, build_grade_prompt
from app.workflow.runner import NodeObserver, Retriever, make_session_retriever, run_workflow
from app.workflow.types import (
    DEFAULT_SYSTEM_PROMPT,
    CitationsFiltered,
    ContextTruncated,
    DocumentQuotaApplied,
    DuplicateEvidenceText,
    DuplicateRetrievedChunks,
    EvidenceCitation,
    GradeCoverageIncomplete,
    GradeReferencesFiltered,
    NodeError,
    ProviderFailure,
    RelevanceBelowThreshold,
    RetrievalEmpty,
    SupportedWithoutCitations,
    WorkflowReason,
    WorkflowReport,
    WorkflowRequest,
    WorkflowState,
    evidence_fetch_k,
    initial_state,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "CitationsFiltered",
    "ContextTruncated",
    "DocumentQuotaApplied",
    "DuplicateEvidenceText",
    "DuplicateRetrievedChunks",
    "EvidenceCitation",
    "GradeCoverageIncomplete",
    "GradeReferencesFiltered",
    "NodeError",
    "ProviderFailure",
    "RelevanceBelowThreshold",
    "RetrievalEmpty",
    "NodeObserver",
    "Retriever",
    "SupportedWithoutCitations",
    "WorkflowReason",
    "WorkflowReport",
    "WorkflowRequest",
    "WorkflowState",
    "build_check_prompt",
    "build_grade_prompt",
    "check_node",
    "evidence_fetch_k",
    "grade_node",
    "initial_state",
    "make_session_retriever",
    "report_node",
    "retrieve_node",
    "run_workflow",
]
```

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/workflow/test_04_nodes.py tests/workflow/test_05_runner.py -q
```

러너 스위트는 이 페이지의 주장 뒤에 있는 측정 기록을 겸한다. 성공 경로는 `node_path == ("retrieve", "grade", "check", "report")`를 못 박으면서 `steps`에는 `("grade", "check")`만 담는다 — 노드 넷을 걸었고 공급자 호출은 둘이었다는, 반복 횟수는 노드를 세고 스텝은 공급자 호출을 세며 둘은 *원래* 달라야 한다는 가장 깨끗한 증명이다. 같은 테스트가 `total_requests == 2`와 `total_input_tokens == 20`을 못 박는다. 그리고 가짜 검색기는 자신이 받는 값이 요청 기본값 5가 아니라 `k == 15`임을 단언한다. `evidence_fetch_k`가 요청을 초과 인출 배수 3만큼 넓혀서, 중복 제거와 문서당 몫가 히트를 걸러낸 뒤에도 선택이 슬롯을 채울 수 있게 한다 — 그 산술은 튜토리얼 6의 소관이다.

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 근거에 없는 청크 ID 인용 | 지어낸 ID가 인용으로 나가지 않는다. |
| 인용이 하나도 남지 않은 `SUPPORTED` | 근거 없는 지지 답변이 강등된다. |
| 노드 중간의 예산 소진 | 이후 호출을 건너뛰고 `budget_exceeded` 리포트가 반환된다. |
| 노드가 던진 예외 | `NodeError`가 되어 리포트에 남는다. |
| 공급자 예산이 워크플로 예산보다 큰 경우 | 호출 하나가 전체 예산을 삼키지 않는다. |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 해당 함수와 연결해 설명해 본다.

- **예산이 두 겹인 이유와 둘이 맞물리는 방식은 무엇인가?**
  - **답:** 워크플로 예산은 전체 실행을, 공급자 예산은 호출 하나를 제한하며, 각 호출에는 공급자 한도와 남은 워크플로 허용량 중 더 작은 값이 전달된다. 이것은 토큰에만 해당하는 이야기다 — 비용에는 워크플로 수준 필드가 없어서, 호출당 비용 상한이 실행 전체에 걸쳐 누적으로 깎여 나간다.
- **`_remaining_provider_budget`이 `<= 0`에서 예외를 던지는 이유는 무엇인가?**
  - **답:** 남은 값이 0 이하라면 노드 전 예산 가드를 건너뛴 것이므로 잘못된 예산을 공급자에게 넘기지 않고 프로그래밍 오류로 처리한다.
- **노드가 실패해도 리포트 노드까지 가는 것이 왜 중요한가?**
  - **답:** 현재 러너는 그렇게 동작하지 않는다. `_failure_report`를 즉시 반환하고 `report_node`로 보내지 않는다. 그래도 직접 실패 경로가 타입화된 실패를 담은 `RunReport`를 만들므로 실행이 조용히 끝나지는 않는다.
- **실패한 공급자 호출도 트레이스를 남겨야 하는 이유는 무엇인가?**
  - **답:** 실패한 호출도 토큰, 비용, 시간을 소비하므로 트레이스를 남겨야 합계와 원인 진단이 정확하다.
- **`_result_hits`가 문자열을 거부하는 이유는 무엇인가?**
  - **답:** 문자열도 파이썬의 `Sequence`라서 그대로 두면 형태 검사를 통과하고 각 문자가 검색 결과로 오인될 수 있기 때문이다.

---

[← 이전: 프롬프트와 노드](07-prompts-nodes.md) · [모듈 개요](../03-build.md)
