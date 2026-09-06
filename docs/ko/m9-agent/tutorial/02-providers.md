# M9.2 튜토리얼 2 — 턴은 측정된 단위다

루프는 매 반복마다 하나의 질문에 답이 필요하다: 지금까지의 대화와 발행된 도구가 주어졌을 때, 모델은 다음에 무엇을 하고 싶은가? 이 문서는 그 질문에 답하는 provider 경계를 만든다 — **루프는 어떤 provider가 돌았는지 결코 알아서는 안 되고, 어떤 provider도 비용이 붙지 않은 턴을 반환해서는 안 되기 때문이다.**

**선행 조건:** M9.1 완료, `uv run pytest tests/agent/test_01_contracts.py tests/agent/test_02_registry.py -q` 통과.

### 무엇을 정의하고, 무엇을 구현하고, 무엇을 들여다볼 것인가

| 영역 | 학습 행동 | 가져갈 것 |
|---|---|---|
| `ProviderTurn`과 ABC | **중립 턴 형태를 직접 작성한다** | 사용량 기록은 텔레메트리가 아니라 계약의 일부다 |
| `DeterministicToolProvider` | 스크립트 큐를 **구현한다** | 오프라인 테스트는 루프의 모조품이 아니라 실제 루프를 돌린다 |
| `OpenAIToolProvider` | Responses 어댑터를 **구현한다** | 와이어 포맷이 끝나고 중립 형태가 시작되는 곳 |

### 1. 중립 턴

#### `app/agent/provider.py` 생성 — 모든 provider가 반환하는 형태

**학습 행동 — 중립 턴 형태를 직접 작성한다:** 루프가 보도록 허락되는 것을 결정하고, M4의 `LLMProvider`와 비교한다.

<!-- src: app/agent/provider.py::ProviderTurn,ToolCallingProvider -->
```python
class ProviderTurn(StrictAgentModel):
    """One raw provider response: prose, requested tool calls, and usage."""

    output_text: str
    tool_calls: tuple[ToolCall, ...]
    input_tokens: NonnegativeInt
    output_tokens: NonnegativeInt
    request_id: str | None = None


class ToolCallingProvider(ABC):
    """Async boundary that turns conversation state into one provider turn."""

    provider_name: str
    model_name: str
    api_url: str

    def __init__(self, *, clock: Clock = time.perf_counter_ns) -> None:
        self._clock = clock

    @abstractmethod
    async def _request(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        """Return one provider-neutral turn without retrying."""

    async def turn(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> tuple[ProviderTurn, float]:
        """Run one timed request and return the turn with its wall-clock milliseconds."""
        started = self._clock()
        result = await self._request(
            instructions,
            input_items,
            tools,
            max_output_tokens=max_output_tokens,
        )
        elapsed_ms = (self._clock() - started) / 1_000_000
        if elapsed_ms < 0:
            raise ValueError("provider clock must be monotonic")
        return result, elapsed_ms
```

**코드에서 꼭 볼 것**

- `ProviderTurn`은 텍스트, 파싱된 도구 호출, 토큰 수를 싣는다 — provider 고유의 것은 이 경계를 넘어 살아남지 못한다. **루프는 응답이 아니라 턴을 소비하므로, provider를 바꿔도 루프 동작은 절대 변할 수 없다.**
- ABC가 `_request`를 직접 계시한다. M4의 provider와 똑같이 지연은 한 곳에서 한 번 측정되고, 어떤 서브클래스도 이를 잊을 수 없다.
- `request_id`는 관측 가능성을 위해 함께 실린다. 라이브 실행이 이상해지면 스텝 추적이 조회할 정확한 provider 요청을 지목한다.

### 2. 결정론적 provider가 곧 테스트 하니스다

#### `app/agent/provider.py` 확장 — 스크립트 큐

**학습 행동 — 스크립트 큐를 구현한다:** 무엇을 반환하는지만이 아니라 무엇을 기록하는지 눈여겨본다.

<!-- src: app/agent/provider.py::DeterministicToolProvider -->
```python
class DeterministicToolProvider(ToolCallingProvider):
    """Queue-backed offline provider for deterministic agent tests and demos."""

    provider_name = "deterministic"
    api_url = "deterministic://local"

    def __init__(
        self,
        turns: Sequence[ProviderTurn],
        *,
        model_name: str = "deterministic-agent",
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        if not model_name.strip():
            raise ValueError("model_name must not be blank")
        if any(not isinstance(turn, ProviderTurn) for turn in turns):
            raise TypeError("turns must contain ProviderTurn values")
        super().__init__(clock=clock)
        self.model_name = model_name
        self._turns = list(turns)
        self._requests: list[
            tuple[str, tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]
        ] = []

    @property
    def requests(
        self,
    ) -> tuple[tuple[str, tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]], ...]:
        """Return (instructions, input items, tool specs) per request, in order."""
        return tuple(self._requests)

    async def _request(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        del max_output_tokens
        self._requests.append((instructions, tuple(input_items), tuple(tools)))
        if not self._turns:
            raise RuntimeError("deterministic tool provider turn queue is empty")
        return self._turns.pop(0)
```

**코드에서 꼭 볼 것**

- 턴은 큐에서 소비되므로, 테스트는 여러 스텝의 대화 전체를 미리 스크립트한다 — 먼저 검색, 그다음 답 — 그리고 테스트 대상 루프는 실제 루프다.
- `requests`는 provider가 받은 모든 입력을 기록한다. **테스트는 루프가 보낸 것 — 재생된 function call과 관찰 — 을 단언하며, 그것이 네트워크 없이 대화 조립 로직을 고정하는 방법이다.**
- 큐가 바닥나면 예외를 던진다. 턴을 한 번 더 도는 테스트는 잘못된 테스트이고, 루프에 빈 턴을 먹이는 대신 시끄럽게 실패한다.

### 3. OpenAI 어댑터

#### `app/agent/provider.py` 확장 — Responses API 어댑터

**학습 행동 — Responses 어댑터를 구현한다:** 날 응답의 `function_call` 항목 하나가 `ToolCall`이 되기까지를 따라간다.

<!-- src: app/agent/provider.py::_turn_tool_calls,OpenAIToolProvider -->
```python
def _turn_tool_calls(response: object) -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    for item in getattr(response, "output", ()):
        if getattr(item, "type", None) != "function_call":
            continue
        calls.append(
            ToolCall(
                call_id=str(getattr(item, "call_id", "") or ""),
                name=str(getattr(item, "name", "") or ""),
                arguments_json=str(getattr(item, "arguments", "") or ""),
            )
        )
    return tuple(calls)


class OpenAIToolProvider(ToolCallingProvider):
    """OpenAI Responses API adapter with strict function tools and injected clients."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        model_name: str,
        client: AsyncOpenAI | None = None,
        api_key: str | None = None,
        api_url: str = "https://api.openai.com/v1/responses",
        clock: Clock = time.perf_counter_ns,
    ) -> None:
        if not model_name.strip() or not api_url.strip():
            raise ValueError("model_name and api_url must not be blank")
        super().__init__(clock=clock)
        self.model_name = model_name
        self.api_url = api_url
        self._client = client or AsyncOpenAI(api_key=api_key)

    async def _request(
        self,
        instructions: str,
        input_items: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        *,
        max_output_tokens: int,
    ) -> ProviderTurn:
        response = await self._client.responses.create(
            model=self.model_name,
            instructions=instructions,
            input=cast(ResponseInputParam, list(input_items)),
            tools=cast(list[ToolParam], list(tools)),
            max_output_tokens=max_output_tokens,
            store=False,
        )
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise ValueError("OpenAI response did not include token usage")
        output_text = getattr(response, "output_text", "")
        return ProviderTurn(
            output_text=output_text if isinstance(output_text, str) else "",
            tool_calls=_turn_tool_calls(response),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_id=getattr(response, "id", None),
        )
```

**코드에서 꼭 볼 것**

- 요청은 `tools=`에 `registry.specs()`의 결과를 손대지 않고 넘기고 `store=False`를 건다 — API는 M9.1이 생성한 엄격 스키마를 그대로 보고, 서버 쪽에는 어떤 대화 상태도 남지 않는다.
- `_turn_tool_calls`는 `type == "function_call"`인 출력 항목만 읽는다. reasoning과 텍스트 항목은 산문으로 통과한다. 인자는 날 JSON 문자열로 남는다 — 파싱은 실패가 관찰이 될 수 있는 dispatch의 몫이다.
- 사용량 없는 응답은 0으로 기본 처리하는 대신 예외를 던진다. **비용을 모르는 턴은 토큰 예산을 조용히 무장 해제시키므로, 어댑터는 그런 턴을 만들기를 거부한다.**

### 집중 테스트와 그것이 지키는 계약

```bash
uv run pytest tests/agent/test_03_provider.py -q
```

| 테스트가 깨뜨리는 것 | 지키는 계약 |
|---|---|
| 지연을 스스로 보고하는 서브클래스 | 계시는 ABC가 균일하게 소유한다 |
| 바닥난 스크립트 큐 | 테스트 스크립트는 루프의 실제 턴 수와 맞아야 한다 |
| 토큰 사용량이 빠진 응답 | 비용 없는 턴은 루프에 들어오지 못한다 |

### 이제 설명할 수 있어야 하는 것

답은 위의 **굵은 핵심 문장**에 있다.

- **루프는 왜 OpenAI 응답이 아니라 `ProviderTurn`을 소비하는가?**
  - **답:** 중립 형태가 요점 그 자체다 — provider 고유의 것이 경계를 넘지 못하므로 provider 교체가 루프 동작을 바꿀 수 없다.
- **결정론적 provider는 왜 입력을 기록하는가?**
  - **답:** 루프가 보낸 것을 단언해야 대화 조립 로직이 오프라인으로 고정된다. 준비된 턴만 반환한다면 스크립트 자신만 테스트하는 셈이다.
- **사용량이 없을 때 왜 0 토큰으로 처리하지 않고 예외를 던지는가?**
  - **답:** 비용 0인 턴은 토큰 예산을 영원히 통과시킨다. 예산은 모든 턴이 정직하게 가격 매겨질 때만 의미가 있다.

---

[← 이전: 계약과 레지스트리](01-contracts-registry.md) · [모듈 개요](../03-build.md) · [다음: 루프 →](03-loop.md)
