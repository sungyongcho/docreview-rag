# M5.4 튜토리얼 6 — 실행이 끝나기 전에 실행을 보여준다

`POST /review`는 끝에 한 번만 답한다. 요청과 그 답 사이에는 검색 한 번과 가드된 LLM 호출 두 번이 있는데, 호출자는 그중 아무것도 보지 못한다. **침묵하는 연결을 십 초 기다리는 클라이언트는 느린 실행과 죽은 실행을 구분할 수 없고, 이 엔드포인트 위에 만든 UI는 모든 것이 끝난 뒤에야 그릴 것이 생긴다.**

워크플로 자체는 처음부터 보고할 진행 상황을 갖고 있었다 — 노드 전이 네 번 — HTTP 경계가 그 구조를 버리고 있었을 뿐이다.

**선행 조건:** 튜토리얼 1–5가 끝나 `uv run pytest tests/api/test_08_integration.py -q`가 통과해야 한다.

### 단방향 진행 보고에는 WebSocket이 아니라 SSE다

실행 중에 클라이언트가 서버에 말을 거는 일은 없다. 요청 하나를 내고 진행 상황을 소비할 뿐이다. 이것이 정확히 Server-Sent Events의 형태다 — `content-type: text/event-stream`을 가진 평범한 HTTP 응답이고, 본문은 `event:`/`data:` 줄 쌍의 나열이다. 연결 업그레이드도, 메시지 라우팅도 없고, 모든 브라우저가 `EventSource`로 소비할 수 있다.

**스트림은 의미가 하나씩인 네 가지 이벤트를 실어 나른다: 완료된 워크플로 노드는 `node`, 종결된 실행은 `report`, 예기치 못한 예외는 `error`, 명시적 스트림 종료 표시는 `done`이다.** 실패한 실행은 `error`가 아니다 — 예산 소진과 스키마 거부는 구조화된 결과이므로 동기 엔드포인트가 보고하던 그대로 `report`로 도착하고, 그 `status`가 무슨 일이 있었는지 말해 준다.

### 옵저버는 두 시임을 건너면서 어느 쪽도 깨뜨리지 않는다

러너는 선택 인자 하나를 얻었다. `run_workflow(..., on_node=...)`는 커밋된 노드 전이마다 노드 이름과 커밋된 상태로 옵저버를 await한다. 기본값이 `None`이라 기존 호출자 전부와 이 튜토리얼 전에 작성된 모든 테스트는 동일하게 동작한다.

서비스 경계도 이를 비춘다. `ApiServices.review_stream(request, on_node)`은 `review`와 같은 가드·영속화 리뷰를 실행하되 노드 보고가 붙는다. **라우트는 큐와 SSE 포매팅을 소유하고, 러너는 노드 의미론을 소유하며, 그 사이 서비스 시임은 평범한 await 호출로 남는다 — 어느 계층도 다른 두 계층의 내부를 모른다.**

### 무엇을 작성하고 어디를 직접 구현할까

| 구간 | 학습 행동 | 여기서 얻어야 하는 것 |
|---|---|---|
| `StreamNodeEvent` | **모델 선언 작성** | 보낼 가치가 있는 최소한의 진행 페이로드 |
| `review_stream` 서비스 시임 | **경계 변환 검토** | 옵저버가 계층을 결합하지 않고 건너는 방법 |
| `_sse`와 스트림 라우트 | 큐 브리지를 **직접 구현** | 큐가 생산과 전송을 분리하는 이유 |

### 1. 진행 페이로드

#### `app/api/schemas.py` 확장 — 노드 이벤트

**학습 행동 — 모델 선언 작성:** 종결 리포트가 나오기 전에 진행 소비자에게 실제로 필요한 것이 무엇인지 먼저 정한다.

<!-- src: app/api/schemas.py::StreamNodeEvent -->
```python
class StreamNodeEvent(StrictApiModel):
    """One completed workflow node reported while a streamed review is running."""

    node: WorkflowNode
    evidence_count: NonnegativeInt
    relevant_count: NonnegativeInt
    step_count: NonnegativeInt
```

**코드에서 꼭 볼 것**

- 카운터 셋과 노드 이름뿐이다. 청크 본문도, 점수도, 부분 답변도 없다 — **진행 이벤트가 흘리는 모든 것은 공개 API 표면이 되므로, 이벤트는 진행 표시줄이 쓸 수 있는 것만 담는다.**
- 카운트는 커밋된 워크플로 상태에서 나온다. `evidence_count`는 `retrieve` 뒤에, `step_count`는 `grade`와 `check` 뒤에 어느 단계가 일했는지를 소비자에게 알려준다.

### 2. 큐 브리지

#### `app/api/routes/stream.py` 생성 — SSE 라우트

**학습 행동 — 큐 브리지 구현:** 누가 큐에 넣고 누가 꺼내는지, 어느 태스크가 먼저 끝나는지 따라간다.

<!-- src: app/api/routes/stream.py::_sse,review_stream -->
```python
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

**코드에서 꼭 볼 것**

- 워크플로는 자기 태스크에서 돌며 **넣기만** 하고, 응답 제너레이터는 **꺼내기만** 한다. **느린 클라이언트와 빠른 워크플로가 서로의 로직을 막지 않고 각자의 속도로 진행하게 해 주는 것이 큐다.**
- `None`은 생산자의 스트림 종료 신호이고, 리뷰가 반환했든 실패했든 예외를 던졌든 반드시 보내지도록 `finally`에 있다. 소비자는 이를 본 뒤에만 `done`을 내보낸다 — 클라이언트는 끝난 스트림과 끊긴 연결을 항상 구분할 수 있다.
- 넓은 `except`가 있는 이유는 이 응답이 이미 시작됐기 때문이다. **`200` 스트림의 첫 바이트가 전송된 뒤에는 예외가 더 이상 상태 코드가 될 수 없다 — 타입이 있는 `error` 이벤트가 남은 유일하게 정직한 채널이다.**
- 제너레이터의 `finally`가 리뷰 태스크를 취소한다. 클라이언트가 도중에 끊으면, 아무도 읽지 않을 LLM 호출에 서버가 계속 비용을 내지 않는다.
- HTTP 수준 검증은 이 모든 것보다 먼저 일어난다. 공백 질의는 스트림에 도달하지 못하고 동기 엔드포인트와 똑같이 평범한 `422`로 실패한다.

### 집중 테스트와 테스트가 지키는 계약

```bash
uv run pytest tests/api/test_09_stream.py -q
```

| 테스트가 깨뜨리는 값 | 지키는 계약 |
|---|---|
| 완전한 성공 실행 | 이벤트가 `node`×4, `report`, `done` 순서로 도착한다 |
| 예산이 소진된 실행 | 구조화된 실패는 `report`로 오고 `error`로 오지 않는다 |
| 예외를 던지는 서비스 | 예기치 못한 예외는 타입이 있는 `error` 이벤트 하나가 된 뒤에야 `done`이 온다 |
| 공백 질의 | 요청 검증이 스트림 시작 전에 `422`로 실패한다 |

### 여기까지 왔을 때 설명할 수 있어야 하는 것

다음 질문의 답은 앞에서 **굵게 표시한 핵심 문장**에 있다. 각 답을 그 답을 소유한 시임과 연결해 설명해 본다.

- **동기 엔드포인트만으로는 진행 UI가 불가능한 이유는 무엇인가?**
  - **답:** 끝에 한 번만 답하므로 기다리는 클라이언트는 느린 실행과 죽은 실행을 구분할 수 없고, 실행이 끝나기 전에는 그릴 것이 없다.
- **실패한 실행이 `report` 이벤트이고 `error` 이벤트가 아닌 이유는 무엇인가?**
  - **답:** 예산 소진과 거부는 자기 status를 가진 구조화된 결과다. `error`는 종결된 실행을 만들지 못한 예외에만 예약된다.
- **옵저버에서 직접 yield하지 않고 큐가 필요한 이유는 무엇인가?**
  - **답:** 생산과 전송은 서로 다른 태스크에서 다른 속도로 돈다. 큐가 둘을 분리해 어느 쪽도 상대의 로직을 막지 않는다.
- **스트림 도중의 예외가 HTTP 상태 코드가 될 수 없는 이유는 무엇인가?**
  - **답:** `200` 헤더와 앞선 바이트들이 이미 전송됐다. 본문 안에 남은 유일하게 정직한 채널은 타입이 있는 `error` 이벤트다.
- **아무도 듣지 않는 실행을 서버가 끝까지 돌리지 않게 막는 것은 무엇인가?**
  - **답:** 클라이언트가 끊으면 제너레이터가 finalize되고, 그 `finally`가 추가 공급자 호출 전에 리뷰 태스크를 취소한다.

---

[← 이전: CLI와 조립](05-cli.md) · [모듈 개요](../03-build.md)
