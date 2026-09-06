# M6 구현 — 만들지 않은 사람도 이해할 수 있게

## API만으로는 아무도 설득되지 않는다

M5까지로 시스템은 완성됐다. `curl`로 `/review`를 부르면 근거에 묶인 답이 JSON으로 나온다.

그런데 채용 담당자나 동료에게 그 JSON을 보여주면 어떨까. 무엇이 대단한지 안 보인다. 이 프로젝트의 핵심 주장 — **"모든 답이 원문 좌표로 검증된다"** — 이 JSON 필드 이름에 묻힌다.

M6는 그걸 눈에 보이게 만든다. 세 가지를 화면에 드러낸다.

- 이 답이 **문서로 뒷받침되는가, 아닌가** (M4의 `NOT_IN_DOCS`가 여기서 값을 한다)
- 근거가 **원문 어디에서** 왔는가 (좌표와 해시)
- 공급자를 **정말 호출했는가**, 비용은 얼마인가

## 화면을 위한 두 번째 추론 경로를 만들지 않는다

UI를 만들 때 가장 흔한 유혹이다. API가 주는 형태가 화면에 안 맞으니 데모 쪽에서 살짝 다르게 계산하는 것.

그 순간 **데모가 보여주는 것과 시스템이 하는 것이 갈라진다.** 데모에서는 잘 되는데 실제 API는 다르게 동작하는, 포트폴리오로서 최악의 상태가 된다.

그래서 `app/demo.py`는 **투영만** 한다. 타입 지정된 M5 결과를 받아 Gradio 값으로 바꾸는 게 전부다. 판단도, 필터링도, 재계산도 없다.

## 체크포인트 지도

| 순서 | 단계 | 개념 | 주요 파일 | 상태 |
|---:|---|---|---|---|
| 1 | M6.1 | 근거와 거부 동작을 화면에 표시 | `app/demo.py` | 완료 |
| 2 | M6.2 | 측정값과 트레이드오프를 과장 없는 포트폴리오로 | `README.md`, 이중 언어 보고서, M6 문서 | 완료 |
| 3 | M6.3 | 프로덕션 M5 경계에 대해 데모 입증 | 기존 데모/런타임 파일 | 완료 |

---

## M6.1 — 증거를 보여주는 Gradio 데모

### 두 가지 모드를 두는 이유

데모에 **미리 준비된(canned) 모드**와 **런타임 모드**가 있다.

미리 준비된 모드는 결정론적 근거를 반환한다. 공급자를 부르지 않으니 **비용이 0**이고 네트워크도 필요 없다. 누가 링크를 열어도 항상 같은 화면이 뜬다.

런타임 모드는 실제 M5 경계에 위임한다. 진짜로 동작하는 걸 보여줄 때 쓴다.

포트폴리오 데모를 공개해두면 누가 얼마나 호출할지 모른다. 기본을 무료 경로로 두면 API 키가 새거나 비용이 폭주할 걱정 없이 열어둘 수 있다. **자격 증명이 있다고 유료 호출이 자동으로 켜지지 않는다** — M5.3에서 확인한 그 규칙이 여기서도 이어진다.

### 서비스 결과가 화면에 닿는 과정

1. Gradio 이벤트가 쿼리, 모드, 검색 제한을 주입된 `DemoService`로 보낸다. 2. 미리 준비된 모드는 결정론적 근거를 반환하고, 런타임 모드는 M5 서비스 경계에 위임한다. 3. 두 경로 모두 불변 `DemoResult` 하나를 생성한다. 4. `render_result()`가 그 결과를 답변, 지원 여부, 추적, 근거 출력으로 변환한다.

| 계약 | 필드 | 화면에서의 역할 |
|---|---|---|
| `DemoEvidence` | `citation`, `span`, `source_sha256`, `chunk_id`, `body` | 근거 패널에 사람이 읽는 출처와 기계가 읽는 원문 식별자를 함께 제공한다. |
| `DemoTrace` | `mode`, `status`, `model`, 요청 수, 토큰 수, 추정 비용, 지연, 선택적 오류 | 공급자를 호출했는지, 무엇을 소비했는지, 왜 실패했는지 보여준다. |
| `DemoResult` | `answer`, `supported`, `evidence`, `trace` | 도메인 로직을 재계산하지 않고 질문 하나를 렌더링하는 데 필요한 값을 전부 전달한다. |

`render_result()`가 그 투영의 전부다. 코드를 보면 근거 항목마다 `citation`, `span`, `source_sha256`, `chunk_id`, `body`를 그대로 내보낸다. **좌표와 해시를 화면에 노출하는 게 핵심이다.** 검토자가 그 값으로 원문을 직접 열어볼 수 있다.

트레이스 줄도 마찬가지다. `mode`, `status`, `model`, 요청 수, 토큰 수, 추정 비용, 지연까지 그대로 보여준다. **모델을 안 불렀으면 안 불렀다고 화면이 말한다.** 데모가 사실은 하드코딩된 답을 보여주는 게 아닌지 의심할 여지를 없앤다.

### 무엇을 작성하고 어디를 직접 구현할까

`app/demo.py` 하나를 여섯 단계로 만든다. 화면 코드지만 도메인 로직은 한 줄도 없다.

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `DemoEvidence`·`DemoTrace`·`DemoResult` | **레코드 선언 작성** | 화면이 필요한 값의 최소 집합 |
| `DemoService`·`M5Service` | **설계 결정 확인** | 데모가 M5를 느슨하게 잡는 법 |
| `CannedDemoService` | **구조 작성** | 무료 기본 경로가 결정론적인 이유 |
| `RuntimeDemoService` | 경계 변환을 **직접 구현** | M5 결과가 화면 값이 되는 지점 |
| `render_result` | **필드 매핑 작성** | 좌표와 해시를 화면에 올리는 이유 |
| `build_demo` | **구조 작성** | 이벤트 배선과 기본 모드 |

### 1. 화면이 필요한 값의 최소 집합

#### `app/demo.py` 생성 — 모듈 헤더

**학습 행동 — 구조 작성:** import에 `gradio`와 M5의 이음매가 함께 있다.

```python
"""Small, deterministic Gradio portfolio demo for the M5 serving surface."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Literal, Protocol

from app.api.errors import ApiProblemError
from app.api.schemas import RetrieveRequest, ReviewRequest
from app.retrieval import ChunkHit, RetrievalFilters, RetrievalResult
```

#### `app/demo.py` 확장 — 데모 레코드

**학습 행동 — 레코드 선언 작성:** 세 레코드가 M2·M4의 어느 값에서 파생되는지 짚어 본다.

<!-- src: app/demo.py::HERO_EXAMPLES,DemoResult -->
```python
HERO_EXAMPLES = (
    "What revenue did Acme report in fiscal year 2024?",
    "What does the filing say about an acquisition?",
)


@dataclass(frozen=True)
class DemoEvidence:
    """Public evidence identity shown in the demo."""

    citation: str
    span: str
    source_sha256: str
    chunk_id: int
    body: str


@dataclass(frozen=True)
class DemoTrace:
    """Trace and cost summary with no provider secrets."""

    mode: str
    status: str
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: str
    latency_ms: float = 0.0
    error: str | None = None


@dataclass(frozen=True)
class DemoResult:
    """Complete renderable result for one demo query."""

    answer: str
    supported: bool
    evidence: tuple[DemoEvidence, ...]
    trace: DemoTrace
```

**코드에서 꼭 볼 것**

- `DemoEvidence`가 `span`과 `source_sha256`을 든다. **좌표와 해시를 화면에 올리는 것이 요점이다** — 검토자가 그 값으로 원문을 직접 열 수 있다.
- `DemoTrace`가 `mode`·`status`·`model`·요청 수·토큰 수·추정 비용·지연을 든다. 모델을 부르지 않았으면 **화면이 그렇게 말한다** — 데모가 하드코딩된 답을 보여주는 게 아니냐는 의심의 여지를 없앤다.
- `HERO_EXAMPLES`가 상수다. 링크를 연 사람이 무엇을 물어야 할지 몰라 빈 화면을 보는 일을 막는다.

### 2. 데모가 M5를 느슨하게 잡는다

#### `app/demo.py` 확장 — 서비스 프로토콜

**학습 행동 — 설계 결정 확인:** `M5Service`가 `ApiServices` 전체가 아니라 일부만 기술하는 것을 확인한다.

<!-- src: app/demo.py::DemoService,M5Service -->
```python
class DemoService(Protocol):
    """Injectable service boundary for deterministic or live demo mode."""

    def run(self, query: str) -> DemoResult: ...


class M5Service(Protocol):
    """Minimal API seam required by the live adapter."""

    async def retrieve(self, request: RetrieveRequest) -> RetrievalResult: ...

    async def review(self, request: ReviewRequest): ...
```

**코드에서 꼭 볼 것**

- `M5Service`가 데모가 실제로 쓰는 메서드만 기술한다. `ApiServices` 전체를 요구하면 데모 테스트가 일곱 메서드를 다 흉내 내야 한다.
- `DemoService`가 화면 쪽 계약이다. canned와 runtime이 같은 모양을 갖는다.

### 3. 무료 기본 경로

#### `app/demo.py` 확장 — 고정 응답 서비스

**학습 행동 — 구조 작성:** canned 모드가 무엇을 하지 *않는지* 확인한다.

<!-- src: app/demo.py::CannedDemoService,LiveDemoService -->
```python
class CannedDemoService:
    """Offline examples that make supported and unsupported behavior obvious."""

    def run(self, query: str) -> DemoResult:
        normalized = query.strip().lower()
        supported = "revenue" in normalized or "acme" in normalized
        if supported:
            evidence = (
                DemoEvidence(
                    citation="Acme 10-K (2024), Item 8, p. 42",
                    span="chars 1204-1297",
                    source_sha256="a" * 64,
                    chunk_id=42,
                    body="Revenue increased to $12.4 million in fiscal year 2024.",
                ),
            )
            answer = "Supported by the filing: Acme reported $12.4 million in 2024 revenue."
        else:
            evidence = ()
            answer = "Not supported by the supplied documents; the demo will not guess."
        return DemoResult(
            answer=answer,
            supported=supported,
            evidence=evidence,
            trace=DemoTrace(
                mode="canned",
                status="ok" if supported else "retrieval_empty",
                model="deterministic",
                requests=0,
                input_tokens=0,
                output_tokens=0,
                estimated_cost_usd="0.000000",
            ),
        )


class LiveDemoService:
    """Adapter for an injected local service; credentials never enter the UI."""

    def __init__(self, callback: DemoService) -> None:
        self._callback = callback

    def run(self, query: str) -> DemoResult:
        return self._callback.run(query)
```

**코드에서 꼭 볼 것**

- 공급자도 데이터베이스도 부르지 않는다. **무료이고 네트워크가 필요 없다.** 링크를 연 사람이 매번 같은 화면을 본다.
- `status`가 `"canned"`다. 화면에 그대로 나가므로 이게 실제 추론이 아니라는 사실이 감춰지지 않는다.

### 4. M5 결과가 화면 값이 되는 지점

#### `app/demo.py` 확장 — 런타임 서비스

**학습 행동 — 경계 변환 구현:** M5의 결과에서 `DemoTrace`를 만드는 부분을 직접 구현한다.

<!-- src: app/demo.py::RuntimeDemoService -->
```python
class RuntimeDemoService:
    """Use the injected M5 services; never discover credentials or call providers."""

    def __init__(self, services: M5Service) -> None:
        self._services = services

    async def run_async(
        self,
        query: str,
        *,
        mode: Literal["query", "review"] = "query",
        k: int = 5,
        filters: RetrievalFilters | None = None,
    ) -> DemoResult:
        started = time.perf_counter()
        try:
            request_filters = filters or RetrievalFilters()
            retrieval = await self._services.retrieve(
                RetrieveRequest(query=query, k=k, filters=request_filters)
            )
            evidence = tuple(_evidence(item) for item in retrieval.hits)
            if mode == "review":
                report = await self._services.review(
                    ReviewRequest(query=query, k=k, filters=request_filters)
                )
                answer = (
                    str(report.report) if report.report is not None else "No report was produced."
                )
                trace = DemoTrace(
                    mode="review",
                    status=report.status,
                    model=report.steps[-1].model_name if report.steps else "none",
                    requests=report.total_requests,
                    input_tokens=report.total_input_tokens,
                    output_tokens=report.total_output_tokens,
                    estimated_cost_usd="not computed by the API seam",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            else:
                answer = "Evidence retrieved; review mode was not requested."
                trace = DemoTrace(
                    mode="query",
                    status="ok" if evidence else "retrieval_empty",
                    model="retrieval",
                    requests=0,
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost_usd="0.000000",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            return DemoResult(answer, bool(evidence), evidence, trace)
        except ApiProblemError as error:
            return DemoResult(
                answer="The service is unavailable; no provider call was attempted.",
                supported=False,
                evidence=(),
                trace=DemoTrace(
                    mode=mode,
                    status=error.error.code,
                    model="none",
                    requests=0,
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost_usd="0.000000",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=error.error.message,
                ),
            )
```

**코드에서 꼭 볼 것**

- **두 번째 추론 경로를 만들지 않는다.** M5의 이음매를 그대로 부르고 결과만 화면 값으로 옮긴다. 데모가 보여주는 것이 진짜 시스템이라는 보장이 여기서 나온다.
- 예외를 잡아 `DemoTrace.error`에 넣는다. 데모가 스택 트레이스를 화면에 뿌리지 않는다.
- 비용과 토큰이 M4.2의 리포트에서 온다. 데모가 따로 세지 않는다.

### 5. 좌표와 해시를 화면에 올린다

#### `app/demo.py` 확장 — 결과 렌더링

**학습 행동 — 필드 매핑 작성:** 각 근거 항목이 어떤 필드를 그대로 넘기는지 확인한다.

<!-- src: app/demo.py::_evidence,render_result -->
```python
def _evidence(item: ChunkHit) -> DemoEvidence:
    """Convert one M5 evidence card without retaining internal fields."""
    return DemoEvidence(
        citation=item.citation,
        span=f"chars {item.start_char}-{item.end_char}",
        source_sha256=item.source_sha256,
        chunk_id=item.chunk_id,
        body=item.body,
    )


def render_result(result: DemoResult) -> tuple[str, str, str, list[dict[str, object]]]:
    """Convert typed result data into safe Gradio values."""
    evidence = [
        {
            "citation": item.citation,
            "span": item.span,
            "source_sha256": item.source_sha256,
            "chunk_id": item.chunk_id,
            "body": item.body,
        }
        for item in result.evidence
    ]
    trace = (
        f"mode={result.trace.mode} | status={result.trace.status} | model={result.trace.model}\n"
        f"requests={result.trace.requests} | input_tokens={result.trace.input_tokens} | "
        f"output_tokens={result.trace.output_tokens} | "
        f"estimated_cost_usd={result.trace.estimated_cost_usd} | "
        f"latency_ms={result.trace.latency_ms:.2f}"
    )
    if result.trace.error:
        trace += f"\nerror={result.trace.error}"
    support = (
        "Supported by the supplied documents."
        if result.supported
        else "Not in the supplied documents."
    )
    return result.answer, support, trace, evidence
```

**코드에서 꼭 볼 것**

- `citation`·`span`·`source_sha256`·`chunk_id`·`body`가 **그대로** 넘어간다. 가공하지 않는다.
- 트레이스가 한 줄 문자열이다. 실패했을 때만 `error`가 덧붙는다.
- 반환이 네 값 튜플이다. Gradio 출력 컴포넌트 넷과 순서가 맞는다.

### 6. 이벤트 배선과 기본 모드

#### `app/demo.py` 완성 — 데모 조립

**학습 행동 — 구조 작성:** 기본 모드가 무엇인지, 왜 그런지 확인한다.

<!-- src: app/demo.py::build_demo -->
```python
def build_demo(
    service: DemoService | None = None,
    *,
    release_notice: str | None = None,
):
    """Build the UI without starting a server or retaining secrets in client state."""
    try:
        import gradio as gr
    except ImportError as error:
        raise RuntimeError(
            "Install the optional 'demo' dependency to launch the Gradio UI."
        ) from error

    selected_service = service or CannedDemoService()
    selected_notice = release_notice or (
        "Deployment mode: local runtime; provider access depends on server configuration."
        if isinstance(selected_service, RuntimeDemoService)
        else "Deployment mode: canned fixture; provider requests and cost are zero."
    )

    async def submit(
        query: str,
        mode: str,
        k: int,
    ) -> tuple[str, str, str, list[dict[str, object]]]:
        if isinstance(selected_service, RuntimeDemoService):
            result = await selected_service.run_async(query, mode=mode, k=k)
        else:
            result = selected_service.run(query)
        return render_result(result)

    with gr.Blocks(title="Document Review Evidence Demo") as demo:
        gr.Markdown(
            "# Document Review Evidence Demo\n"
            "Explore cited answers without exposing provider secrets.\n\n"
            f"**{selected_notice}**"
        )
        query = gr.Textbox(label="Ask about the filing", value=HERO_EXAMPLES[0])
        gr.Examples(examples=[[example] for example in HERO_EXAMPLES], inputs=query)
        modes = (
            ["query", "review"] if isinstance(selected_service, RuntimeDemoService) else ["canned"]
        )
        mode = gr.Radio(modes, value=modes[0], label="Mode")
        k = gr.Slider(1, 10, value=5, step=1, label="Evidence count")
        run = gr.Button("Review evidence", variant="primary")
        answer = gr.Markdown(label="Answer")
        support = gr.Markdown(label="Evidence boundary")
        trace = gr.Markdown(label="Trace and cost transparency")
        evidence = gr.JSON(label="Evidence cards")
        run.click(submit, inputs=[query, mode, k], outputs=[answer, support, trace, evidence])
    return demo
```

**코드에서 꼭 볼 것**

- 기본 모드가 canned다. **자격증명이 있어도 유료 호출이 자동으로 켜지지 않는다** — M5.3에서 확인한 규칙이 여기서도 이어진다.
- `service`를 주입받는다. 테스트가 가짜를 넣어 화면 배선만 검증할 수 있다.
- 도메인 로직이 한 줄도 없다. 이 파일은 값을 옮기고 배선하는 일만 한다.

파일 마지막에 모듈 실행 가드를 덧붙인다. 이 두 줄이 있어야 `python -m app.demo`가 동작한다.

```python
if __name__ == "__main__":
    build_demo().launch()
```

### 작지만 정직한 데모 띄우기

선행 조건: M5.3을 통과했고 Python 3.14+, uv, 루프백 포트 7861을 사용할 수 있어야 한다.

```bash
uv sync --locked --extra demo
uv run pytest tests/demo -q
uv run --extra demo python - <<'PY'
from app.demo import build_demo

demo = build_demo()
_, local_url, _ = demo.launch(
    server_name="127.0.0.1",
    server_port=7861,
    prevent_thread_lock=True,
    quiet=True,
)
print(local_url)
demo.close()
PY
```

초록색 결과는 이 장에서 주장한 범위의 근거로만 읽고 그보다 넓게 해석하지 않는다.

잠금 동기화가 `uv.lock`을 바꾸지 않고 끝나며, 모든 데모 테스트가 통과하고, 출력된 URL은 `http://127.0.0.1:7861/`이며, 서버가 정상적으로 닫힌다. UI는 지원되는 답변과 지원되지 않는 답변을 구분하고 비밀을 노출하지 않으면서 근거 식별 정보를 표시한다.

의존성 잠금이 예상치 않게 바뀌거나, 정식 심벌 누락으로 테스트 수집이 건너뛰거나, 미리 준비된 모드가 공급자를 호출할 수 있거나, 근거 식별 정보가 없거나, 루프백 시작 및 종료가 실패하면 M6.2를 시작하지 않는다.

결과가 설명과 다르면 처음 달라진 경계부터 추적한다.

- 임포트 또는 테스트 수집이 실패하면 `app/demo.py`와 위의 M6.1 완성 블록을 비교한다.
- 출력 형태가 잘못되면 `DemoResult` -> `render_result()` -> `build_demo()`의 Gradio 출력 컴포넌트 순서로 추적한다.
- 스모크 명령이 바인딩하지 못하면 포트 7861을 비우거나 `server_port`와 예상 URL에서 같은 다른 루프백 포트를 사용하며, 서버를 공개하지 않는다.

## M6.2 — 포트폴리오는 기술 목록이 아니라 증거 지도다

이 프로젝트의 문서에서 가장 하기 쉬운 실수가 있다. **"PostgreSQL, pgvector, FastAPI, LangGraph 사용"** 같은 기술 나열이다.

읽는 사람 입장에서 이건 아무 정보가 아니다. 썼다는 것과 잘 썼다는 것은 다르고, 튜토리얼을 따라 한 것과 문제를 풀어본 것도 다르다.

그래서 M6.2의 규칙은 이렇다.

**모든 수치 주장은 저장소의 무언가를 가리켜야 한다.** 테스트든, M3의 원시 아티팩트든, 측정 보고서든. "재현율 0.82"라고 쓰려면 그 숫자가 나온 파일이 커밋돼 있어야 한다.

**모든 한계는 그 한계가 적용되는 결과 옆에 있어야 한다.** 한계를 맨 뒤에 몰아두면 아무도 안 읽는다. 골든 데이터가 사람 검증을 안 거쳤다는 사실은 그 평가 숫자 바로 옆에 있어야 한다.

**명령은 어느 경로인지 구분해서 적는다.** 미리 준비된 경로인지, 로컬 런타임인지, 유료 호출인지, 배포인지. 독자가 복사해서 붙였을 때 예상 못 한 요금이 나오면 안 된다.

이 원칙이 이 프로젝트 전체를 관통해온 것과 같다는 데 주목하자. M1.1의 좌표, M3의 골든 증거, M4의 인용 검사 — 전부 **"주장에 근거를 붙인다"** 였다. 문서도 예외가 아니다.

### 측정값을 독자가 따라갈 경로로 바꾸기

1. M3 원시 아티팩트가 측정값을 제공한다. 2. 아키텍처 및 평가 문서가 경계, 트레이드오프, 결과를 설명한다. 3. 실패 분석이 좋지 않은 결과를 결정론적 보호 장치와 테스트에 연결한다. 4. 언어별 M6 가이드가 설정부터 검증까지 독자를 안내한다. 5. 루트 README는 해당 아티팩트가 뒷받침하는 명령과 주장만 노출한다.

### 근거에서 바깥쪽으로 포트폴리오 쓰기

M6.2는 애플리케이션 모듈을 추가하지 않는다. 다음 기존 문서 표면을 이 순서대로 업데이트하고 검증한다.

1. `docs/en/architecture.md` 2. `docs/ko/architecture.md` 3. `docs/en/eval-report.md` 4. `docs/ko/eval-report.md` 5. `docs/en/failure-analysis.md` 6. `docs/ko/failure-analysis.md` 7. `docs/en/m6-demo/00-README.md`부터 `docs/en/m6-demo/05-verify.md`까지 8. `docs/ko/m6-demo/00-README.md`부터 `docs/ko/m6-demo/05-verify.md`까지 9. `docs/00-README.md` 10. `docs/project/module-plan.md` 11. `README.md`

### 문서가 스스로를 검사하게 만들기

선행 조건: M5.3과 M6.1을 통과했고 보고된 모든 M3 측정값이 커밋된 원시 아티팩트를 가리켜야 한다.

```bash
uv run pytest tests/test_doc_sync.py tests/test_doc_parity.py -q
```

초록색 결과는 이 장에서 주장한 범위의 근거로만 읽고 그보다 넓게 해석하지 않는다.

선택한 모든 테스트가 통과한다. 소스 연결 블록, 이중 언어 구조, 상대 링크, 보호된 기술 리터럴이 계속 동기화되며, 그럴듯하다는 이유만으로 측정 주장을 허용하지 않는다.

측정값에 저장소 증거가 없거나, 미리 준비된 결과를 실제 결과로 표시하거나, 자리표시자를 스크린샷으로 제시하거나, 명령을 복사할 수 없거나, EN/KO 구조가 다르면 M6.3을 시작하지 않는다.

결과가 설명과 다르면 처음 달라진 경계부터 추적한다.

- 소스 동기화 실패는 처음 보고된 문서와 소스 마커를 사용하며, 검사기를 약화하지 말고 설명이나 정식 소스를 고친다.
- 동등성 실패는 일반 한국어 산문을 번역된 상태로 유지하면서 EN/KO 쌍에서 보고된 구조 필드를 비교한다.
- 링크 실패는 저장소 루트가 아니라 현재 언어 디렉터리를 기준으로 대상을 해석한다.

## M6.3 — 데모가 진짜를 보여주는지 확인한다

M5.3에서 했던 것과 같은 종류의 검증이다. 조각이 각각 통과해도 조립은 틀릴 수 있다.

M6.1의 렌더링 테스트는 미리 준비된 데이터로 돌았다. M6.2의 문서 검사는 텍스트만 봤다. **둘 다 통과해도 런타임 어댑터가 다른 형태를 반환하면** 실제 데모는 깨진다.

포트폴리오에서 이건 치명적이다. 링크를 보낸 사람 앞에서 화면이 깨지는 것보다, 화면은 멀쩡한데 사실은 하드코딩이었다는 게 더 나쁘다.

그래서 M6.3이 확인하는 것은 셋이다.

- 데모가 **진짜 M5 런타임 결과**를 쓰는가
- 모든 인터페이스가 모드·근거·한계를 **일관되게** 표시하는가
- 전체 테스트 스위트 결과를 **새로 측정**했는가 (이전 합계를 복사하지 않고)

마지막이 사소해 보이지만 중요하다. 테스트 개수 같은 숫자를 이전 문서에서 복사하면, 그 순간부터 문서의 숫자가 현실과 어긋나기 시작한다. **문서에 적는 측정값은 그때 실제로 잰 것이어야 한다.**

### 다듬은 화면을 실제 런타임에 다시 연결하기

1. Gradio 이벤트가 `RuntimeDemoService`로 들어온다. 2. 쿼리 모드는 `RetrievalResult.hits`를 사용하고 검토 모드는 M4 최종 보고서를 사용한다. 3. 두 경로 모두 `DemoResult`로 매핑되고 `render_result()`를 재사용한다. 4. 통합 테스트가 데모 경계를 M5 HTTP/CLI 근거 계약과 비교한다. 5. 문서는 새로 관찰한 동작만 기록한다.

### 코드를 더하지 않고 연결부 감사하기

M6.3은 두 번째 구현을 추가하지 않는다. 다음 기존 파일을 이 순서대로 다시 읽고 검증한다.

1. `app/demo.py` 2. `app/api/runtime.py` 3. `tests/demo/test_demo.py` 4. `tests/api/test_08_integration.py` 5. `README.md` 6. `docs/en/m6-demo/05-verify.md` 7. `docs/ko/m6-demo/05-verify.md`

### 실제 경계를 통해 데모 구동하기

선행 조건: M6.1과 M6.2를 통과했고 M5 `RetrievalResult` 도메인 타입을 사용할 수 있어야 한다.

```bash
uv run pytest tests/demo tests/api/test_08_integration.py -q
```

초록색 결과는 이 장에서 주장한 범위의 근거로만 읽고 그보다 넓게 해석하지 않는다.

선택한 모든 테스트가 통과한다. 런타임 결과가 프로덕션 `RetrievalResult.hits` 형태를 사용하고, CLI/API/데모 근거가 일치하며, 미리 준비된 모드와 런타임 모드 표기가 명확하게 유지된다.

정식 심벌 누락으로 테스트 수집이 건너뛰거나, 프로덕션 반환 형태를 우회하거나, 런타임 실행을 미리 준비된 것으로 또는 그 반대로 표시하거나, 스크린샷이 오래되었거나 표기가 없거나, 주변 환경의 자격 증명이 공급자를 활성화하거나, 인터페이스마다 근거가 다르면 M6는 미완성이다.

결과가 설명과 다르면 처음 달라진 경계부터 추적한다.

- 반환 형태 오류는 `RetrievalResult.hits`에서 `DemoEvidence`로 가는 어댑터를 확인하며, 데모 전용 검색 모델을 추가하지 않는다.
- 모드 표기 오류는 렌더링 문구를 바꾸기 전에 선택된 서비스와 모드를 추적한다.
- 근거 불일치는 M5 경계와 데모 투영에서 인용, 구간, 소스 해시, 청크 ID, 본문을 비교한다.

## 최종 품질 게이트

```bash
uv run pytest -o addopts="" -q
uv run ruff check --no-fix app tests scripts
uv run ruff format --check app tests scripts
uv run python scripts/check_doc_code.py docs/en/m6-demo/03-build.md docs/ko/m6-demo/03-build.md
uv run pytest tests/test_doc_sync.py tests/test_doc_parity.py -q
git diff --check
```

예상 결과: 모든 명령이 종료 상태 0으로 끝난다. 이전 개수를 복사하지 말고 측정한 전체 스위트 결과와 의도적인 건너뜀 항목을 기록한다.

---

## 이 모듈이 다음 모듈에 넘기는 것

M6까지로 **보여줄 수 있는 시스템**이 됐다. 남은 건 배포다.

| M6가 만든 것 | 받는 곳 | 거기서 하는 일 |
|---|---|---|
| `app/demo.py` | **M7** | 데모 컨테이너 진입점 |
| 미리 준비된 모드 | **M7** | 자격 증명 없이 공개 배포 |
| 포트폴리오 문서 | **M7** | 릴리스에 포함될 산출물 |
| 문서 동기화 테스트 | **M7** | CI 게이트 |

다음 장 M7은 이걸 배포한다. 여기서도 같은 원칙이 이어진다 — **자격 증명이 있다고 동의한 것이 아니고, 공개 데모가 전체 시스템은 아니다.** 릴리스 구성은 결정론적이어야 하고, 무엇이 실제로 게시됐는지와 무엇이 그냥 메타데이터인지를 구분해야 한다.

## 여기까지 왔을 때 설명할 수 있어야 하는 것

- **화면을 위한 두 번째 추론 경로를 만들면 안 되는 이유는 무엇인가?**
  - **답:** 화면 전용 경로는 M5 로직과 달라져 실제 시스템이 만들지 않은 결과를 표시할 수 있다. M5의 이음매를 재사용해야 데모가 같은 추론 경로의 결과만 화면에 옮긴다.
- **미리 준비된 모드와 실제 런타임 모드를 화면에 구분해 표시해야 하는 이유는 무엇인가?**
  - **답:** 미리 준비된 모드는 공급자를 호출하지 않고 정해진 근거를 반환하지만, 런타임 모드는 실제 M5 경로를 실행한다. 둘을 표시해야 무료 고정 응답을 실시간 추론으로 오해하지 않고 비용 주장도 정직하게 유지된다.
- **좌표와 해시를 화면에 노출하는 것이 데모의 주장에 어떤 차이를 만드는가?**
  - **답:** 좌표는 정확한 원문 구간을, 해시는 그 좌표가 유효한 소스 스냅샷을 식별한다. 따라서 검토자가 인용 표시를 믿는 데 그치지 않고 근거를 직접 대조할 수 있다.
- **포트폴리오를 기술 목록이 아니라 증거 지도로 쓴다는 말은 무슨 뜻인가?**
  - **답:** 각 주장에 그것을 뒷받침하는 산출물·명령·테스트·측정값을 연결하고, 한계는 영향을 받는 결과 옆에 둔다는 뜻이다. 기술 이름만 나열해서는 무엇을 입증했는지 알 수 없다.
- **이전 문서에서 테스트 개수를 복사하면 문서에 어떤 일이 생기는가?**
  - **답:** 테스트 스위트가 바뀌면서 복사한 개수는 낡고, 문서는 과거 숫자를 현재 측정값처럼 제시하게 된다. 테스트 개수는 문서에 기록하는 시점에 다시 측정해야 한다.
- **데모가 보여 주는 것이 진짜인지를 무엇으로 증명하는가?**
  - **답:** 현재 검사 하나만으로 UI부터 M5까지의 전체 경로가 증명되지는 않는다. 데모 라우트 테스트는 통제된 서비스로 근거와 모드 표기를 확인하고, M5 API 통합 테스트는 프로덕션 런타임을 따로 검증한다. 완전한 종단 간 증명에는 UI와 프로덕션 런타임을 직접 잇는 통합 테스트가 필요하다.

## 기계 검증용 최종 기준본

위의 장들이 실제 빌드 경로이다. 아래 자동 생성 절은 M6.1 전에 미리 작성해야 하는 선행 조건이 아니라 `reference_revision`과 바이트 단위로 맞춘 최종 기준본이다. 세 체크포인트를 마친 뒤 완성 파일을 비교할 때 사용한다.

<!-- complete-files:start -->
## 완성 기준본 — 정식 구현 전체

아래 정식 경로를 직접 생성하거나 교체한다. `_mine.py` 또는 별도의 학습자용 복사 모듈을 만들지 않는다. 앞의 발췌 코드는 개별 결정을 설명하고, 이 절의 코드 블록은 체크포인트를 마친 뒤 대조할 완성 파일이다. 표시된 타입 어노테이션과 영어 주석을 유지하며 `pyproject.toml`을 Ruff 정책의 기준으로 사용한다.

### M6.1 — 완성 체크포인트

#### 생성 또는 교체 `app/demo.py`

<!-- file: app/demo.py -->
```python
"""Small, deterministic Gradio portfolio demo for the M5 serving surface."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Literal, Protocol

from app.api.errors import ApiProblemError
from app.api.schemas import RetrieveRequest, ReviewRequest
from app.retrieval import ChunkHit, RetrievalFilters, RetrievalResult

HERO_EXAMPLES = (
    "What revenue did Acme report in fiscal year 2024?",
    "What does the filing say about an acquisition?",
)


@dataclass(frozen=True)
class DemoEvidence:
    """Public evidence identity shown in the demo."""

    citation: str
    span: str
    source_sha256: str
    chunk_id: int
    body: str


@dataclass(frozen=True)
class DemoTrace:
    """Trace and cost summary with no provider secrets."""

    mode: str
    status: str
    model: str
    requests: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: str
    latency_ms: float = 0.0
    error: str | None = None


@dataclass(frozen=True)
class DemoResult:
    """Complete renderable result for one demo query."""

    answer: str
    supported: bool
    evidence: tuple[DemoEvidence, ...]
    trace: DemoTrace


class DemoService(Protocol):
    """Injectable service boundary for deterministic or live demo mode."""

    def run(self, query: str) -> DemoResult: ...


class M5Service(Protocol):
    """Minimal API seam required by the live adapter."""

    async def retrieve(self, request: RetrieveRequest) -> RetrievalResult: ...

    async def review(self, request: ReviewRequest): ...


class CannedDemoService:
    """Offline examples that make supported and unsupported behavior obvious."""

    def run(self, query: str) -> DemoResult:
        normalized = query.strip().lower()
        supported = "revenue" in normalized or "acme" in normalized
        if supported:
            evidence = (
                DemoEvidence(
                    citation="Acme 10-K (2024), Item 8, p. 42",
                    span="chars 1204-1297",
                    source_sha256="a" * 64,
                    chunk_id=42,
                    body="Revenue increased to $12.4 million in fiscal year 2024.",
                ),
            )
            answer = "Supported by the filing: Acme reported $12.4 million in 2024 revenue."
        else:
            evidence = ()
            answer = "Not supported by the supplied documents; the demo will not guess."
        return DemoResult(
            answer=answer,
            supported=supported,
            evidence=evidence,
            trace=DemoTrace(
                mode="canned",
                status="ok" if supported else "retrieval_empty",
                model="deterministic",
                requests=0,
                input_tokens=0,
                output_tokens=0,
                estimated_cost_usd="0.000000",
            ),
        )


class LiveDemoService:
    """Adapter for an injected local service; credentials never enter the UI."""

    def __init__(self, callback: DemoService) -> None:
        self._callback = callback

    def run(self, query: str) -> DemoResult:
        return self._callback.run(query)


class RuntimeDemoService:
    """Use the injected M5 services; never discover credentials or call providers."""

    def __init__(self, services: M5Service) -> None:
        self._services = services

    async def run_async(
        self,
        query: str,
        *,
        mode: Literal["query", "review"] = "query",
        k: int = 5,
        filters: RetrievalFilters | None = None,
    ) -> DemoResult:
        started = time.perf_counter()
        try:
            request_filters = filters or RetrievalFilters()
            retrieval = await self._services.retrieve(
                RetrieveRequest(query=query, k=k, filters=request_filters)
            )
            evidence = tuple(_evidence(item) for item in retrieval.hits)
            if mode == "review":
                report = await self._services.review(
                    ReviewRequest(query=query, k=k, filters=request_filters)
                )
                answer = (
                    str(report.report) if report.report is not None else "No report was produced."
                )
                trace = DemoTrace(
                    mode="review",
                    status=report.status,
                    model=report.steps[-1].model_name if report.steps else "none",
                    requests=report.total_requests,
                    input_tokens=report.total_input_tokens,
                    output_tokens=report.total_output_tokens,
                    estimated_cost_usd="not computed by the API seam",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            else:
                answer = "Evidence retrieved; review mode was not requested."
                trace = DemoTrace(
                    mode="query",
                    status="ok" if evidence else "retrieval_empty",
                    model="retrieval",
                    requests=0,
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost_usd="0.000000",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            return DemoResult(answer, bool(evidence), evidence, trace)
        except ApiProblemError as error:
            return DemoResult(
                answer="The service is unavailable; no provider call was attempted.",
                supported=False,
                evidence=(),
                trace=DemoTrace(
                    mode=mode,
                    status=error.error.code,
                    model="none",
                    requests=0,
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost_usd="0.000000",
                    latency_ms=(time.perf_counter() - started) * 1000,
                    error=error.error.message,
                ),
            )


def _evidence(item: ChunkHit) -> DemoEvidence:
    """Convert one M5 evidence card without retaining internal fields."""
    return DemoEvidence(
        citation=item.citation,
        span=f"chars {item.start_char}-{item.end_char}",
        source_sha256=item.source_sha256,
        chunk_id=item.chunk_id,
        body=item.body,
    )


def render_result(result: DemoResult) -> tuple[str, str, str, list[dict[str, object]]]:
    """Convert typed result data into safe Gradio values."""
    evidence = [
        {
            "citation": item.citation,
            "span": item.span,
            "source_sha256": item.source_sha256,
            "chunk_id": item.chunk_id,
            "body": item.body,
        }
        for item in result.evidence
    ]
    trace = (
        f"mode={result.trace.mode} | status={result.trace.status} | model={result.trace.model}\n"
        f"requests={result.trace.requests} | input_tokens={result.trace.input_tokens} | "
        f"output_tokens={result.trace.output_tokens} | "
        f"estimated_cost_usd={result.trace.estimated_cost_usd} | "
        f"latency_ms={result.trace.latency_ms:.2f}"
    )
    if result.trace.error:
        trace += f"\nerror={result.trace.error}"
    support = (
        "Supported by the supplied documents."
        if result.supported
        else "Not in the supplied documents."
    )
    return result.answer, support, trace, evidence


def build_demo(
    service: DemoService | None = None,
    *,
    release_notice: str | None = None,
):
    """Build the UI without starting a server or retaining secrets in client state."""
    try:
        import gradio as gr
    except ImportError as error:
        raise RuntimeError(
            "Install the optional 'demo' dependency to launch the Gradio UI."
        ) from error

    selected_service = service or CannedDemoService()
    selected_notice = release_notice or (
        "Deployment mode: local runtime; provider access depends on server configuration."
        if isinstance(selected_service, RuntimeDemoService)
        else "Deployment mode: canned fixture; provider requests and cost are zero."
    )

    async def submit(
        query: str,
        mode: str,
        k: int,
    ) -> tuple[str, str, str, list[dict[str, object]]]:
        if isinstance(selected_service, RuntimeDemoService):
            result = await selected_service.run_async(query, mode=mode, k=k)
        else:
            result = selected_service.run(query)
        return render_result(result)

    with gr.Blocks(title="Document Review Evidence Demo") as demo:
        gr.Markdown(
            "# Document Review Evidence Demo\n"
            "Explore cited answers without exposing provider secrets.\n\n"
            f"**{selected_notice}**"
        )
        query = gr.Textbox(label="Ask about the filing", value=HERO_EXAMPLES[0])
        gr.Examples(examples=[[example] for example in HERO_EXAMPLES], inputs=query)
        modes = (
            ["query", "review"] if isinstance(selected_service, RuntimeDemoService) else ["canned"]
        )
        mode = gr.Radio(modes, value=modes[0], label="Mode")
        k = gr.Slider(1, 10, value=5, step=1, label="Evidence count")
        run = gr.Button("Review evidence", variant="primary")
        answer = gr.Markdown(label="Answer")
        support = gr.Markdown(label="Evidence boundary")
        trace = gr.Markdown(label="Trace and cost transparency")
        evidence = gr.JSON(label="Evidence cards")
        run.click(submit, inputs=[query, mode, k], outputs=[answer, support, trace, evidence])
    return demo


if __name__ == "__main__":
    build_demo().launch()
```

체크포인트를 실행한다.

```bash
uv run pytest tests/demo -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M6.2 — 완성 체크포인트

체크포인트를 실행한다.

```bash
uv run pytest tests/test_doc_sync.py tests/test_doc_parity.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

### M6.3 — 완성 체크포인트

체크포인트를 실행한다.

```bash
uv run pytest tests/demo tests/api/test_08_integration.py -q
```

**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다.

**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 진행하지 않는다.

**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 번째로 실패한 계약을 고친 뒤 진행한다.

<!-- complete-files:end -->
