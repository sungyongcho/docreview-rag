# M9.1 튜토리얼 1 — 자율성보다 계약이 먼저

에이전트는 도구 사이의 경로를 스스로 고르게 된다. 루프의 단 한 반복이 존재하기 전에, 이 문서는 에이전트가 말할 수 있는 것과 도구를 선언하는 방식을 먼저 못박는다 — **모델이 행동을 고르는 순간, 그럴듯한 답과 조작된 답 사이에 서 있는 것은 타입이 표현을 거부하는 상태들의 집합뿐이기 때문이다.**

**선행 조건:** M1–M8 완료, `uv run pytest -o addopts="" tests/workflow -q` 통과.

### 무엇을 정의하고, 무엇을 구현하고, 무엇을 들여다볼 것인가

| 영역 | 학습 행동 | 가져갈 것 |
|---|---|---|
| `ToolCall`, `Observation`, `AgentStep` | **모델 선언을 직접 작성한다** | 에러가 예외가 아니라 관찰인 이유 |
| `AgentAnswer`, `AgentResult` | 배타성 검증자를 **구현한다** | 새 경계에서 다시 강제되는 M4 라벨 계약 |
| `Tool`과 `ToolRegistry` | **구조를 작성하고, 표면을 검토한다** | 세 소비자를 먹이는 하나의 선언 |

### 1. 에러는 관찰이다

루프는 모든 도구 결과를 모델에게 되먹인다. 실패한 호출도 같은 방식으로 — 모델이 읽을 수 있는 데이터로 — 돌아와야 하므로, 관찰 타입은 출력 또는 에러 중 하나를 싣는다. 둘 다는 안 되고, 둘 다 없어도 안 된다.

#### `app/agent/types.py` 생성 — 호출과 관찰

**학습 행동 — 모델 선언을 직접 작성한다:** 검증자가 어떤 조합들을 표현 불가능하게 만드는지 눈여겨본다.

<!-- src: app/agent/types.py::ToolCall,Observation -->
```python
class ToolCall(StrictAgentModel):
    """One tool invocation requested by the model, with raw JSON arguments."""

    call_id: NonBlank
    name: NonBlank
    arguments_json: StrictStr


class Observation(StrictAgentModel):
    """The explicit result the loop feeds back for one tool call.

    Errors are observations too: a failed call must come back as a typed
    message the model can read, never as a silently dropped step.
    """

    call_id: NonBlank
    name: NonBlank
    output_json: StrictStr = ""
    error: NonBlank | None = None

    @model_validator(mode="after")
    def require_output_or_error(self) -> Self:
        """Keep successful output and typed failure mutually exclusive."""
        if self.error is None and not self.output_json:
            raise ValueError("observations require output_json or an error")
        if self.error is not None and self.output_json:
            raise ValueError("failed observations must not also carry output")
        return self
```

**코드에서 꼭 볼 것**

- `arguments_json`은 날 것의 문자열로 남는다. 파싱은 실패가 관찰이 될 수 있는 dispatch 시점에 일어난다. 여기서 파싱하면 모델의 실수가 예외로 변한다.
- `Observation.require_output_or_error`는 "조용히 비어 있음"과 "둘 다 있음"을 무효 상태로 만든다. **모델이 무슨 일이 있었는지 추측하게 두어서는 안 된다 — 이제 타입 시스템이 루프가 알림을 잊을 수 없음을 보장한다.**

### 2. 답 계약은 새 경계를 넘어 살아남는다

#### `app/agent/types.py` 확장 — 최종 답

**학습 행동 — 배타성 검증자를 구현한다:** 각 분기를 작성하기 전에 M4의 `AnswerDecision`과 비교한다.

<!-- src: app/agent/types.py::AgentCitation,AgentAnswer -->
```python
class AgentCitation(StrictAgentModel):
    """One retrieved chunk the final answer stands on."""

    chunk_id: PositiveInt
    doc_id: NonBlank
    citation: NonBlank


class AgentAnswer(StrictAgentModel):
    """The structured final answer with the M4 label and citation contract."""

    label: Literal["SUPPORTED", "NOT_IN_DOCS"]
    answer: NonBlank
    citations: tuple[AgentCitation, ...]
    rationale: NonBlank

    @model_validator(mode="after")
    def validate_label_contract(self) -> Self:
        """Keep supported and absent answers mutually exclusive."""
        chunk_ids = [citation.chunk_id for citation in self.citations]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("citation chunk ids must be unique")
        if self.label == "SUPPORTED":
            if not self.citations:
                raise ValueError("SUPPORTED answers require at least one citation")
            if self.answer == "NOT_IN_DOCS":
                raise ValueError("SUPPORTED answers require a supported answer")
        else:
            if self.answer != "NOT_IN_DOCS":
                raise ValueError("NOT_IN_DOCS answers must use the NOT_IN_DOCS answer")
            if self.citations:
                raise ValueError("NOT_IN_DOCS answers must not carry citations")
        return self
```

**코드에서 꼭 볼 것**

- 라벨 계약은 정신적으로 M4 그대로다: **인용 없는 `SUPPORTED`와 인용 있는 `NOT_IN_DOCS`는 둘 다 표현 불가능하므로, 하류의 어떤 코드도 이 조합을 다시 검사할 필요가 없다.**
- 인용은 `chunk_id`, `doc_id`, 사람이 읽는 citation을 담는다 — 다른 모든 모듈이 싣고 다니는 것과 같은 출처 정보다. 유일성은 여기서 검증하고, 그 id들이 실제로 검색됐는지는 튜토리얼 3에서 루프가 맡는다.

#### `app/agent/types.py` 확장 — 종결 결과

<!-- src: app/agent/types.py::AgentResult -->
```python
class AgentResult(StrictAgentModel):
    """One terminal agent run: an answer or a typed failure, never both."""

    status: AgentStatus
    answer: AgentAnswer | None
    failure: NonBlank | None
    iterations: NonnegativeInt
    total_input_tokens: NonnegativeInt
    total_output_tokens: NonnegativeInt
    total_time_seconds: NonnegativeFloat
    steps: tuple[AgentStep, ...]

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> Self:
        """Keep success and failure states mutually exclusive."""
        if self.status == "ok":
            if self.answer is None or self.failure is not None:
                raise ValueError("successful runs require an answer and no failure")
        else:
            if self.answer is not None or self.failure is None:
                raise ValueError("failed runs require a failure and no answer")
        return self
```

**코드에서 꼭 볼 것**

- `ok`는 답을 요구하고 실패를 금지한다. 다른 모든 상태는 정반대를 요구한다. 실행은 잘 끝나거나 타입 있게 끝난다 — 둘 다는 없고, 둘 다 아님도 없다.
- 전체 `steps` 이력이 함께 실린다. 스텝 없는 결과는 근거 없는 점수이고, 그것이 왜 무가치한지는 M3가 이미 가르쳤다.

### 3. 하나의 선언, 세 소비자

#### `app/agent/tools.py` 생성 — 도구 경계

**학습 행동 — 구조를 작성한다:** LLM, MCP 서버, 프롬프트가 전부 생성될 수 있으려면 도구가 무엇을 선언해야 하는지 결정한다.

<!-- src: app/agent/tools.py::TOOL_NAME,Tool -->
```python
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_TOOL_NAMES = frozenset({"final_answer"})

type EvidenceExtractor = Callable[[Any], tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class Tool[ParamsT: BaseModel]:
    """One callable capability with a validated parameter schema.

    ``run`` receives the already-validated parameters model and returns any
    JSON-serializable payload. ``evidence_ids`` optionally names the chunk ids
    a payload puts into evidence, so the loop can hold final answers to the
    chunks the run actually saw.
    """

    name: str
    description: str
    parameters: type[ParamsT]
    run: Callable[[ParamsT], Awaitable[Any]]
    evidence_ids: EvidenceExtractor | None = None

    def __post_init__(self) -> None:
        """Reject tools whose identity or schema cannot be published."""
        if TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("tool name must be snake_case ascii")
        if self.name in RESERVED_TOOL_NAMES:
            raise ValueError(f"tool name {self.name!r} is reserved for the agent loop")
        if not self.description.strip():
            raise ValueError("tool description must not be blank")
        if not isinstance(self.parameters, type) or not issubclass(self.parameters, BaseModel):
            raise ValueError("tool parameters must be a Pydantic model class")
```

**코드에서 꼭 볼 것**

- `parameters`는 손으로 쓴 스키마가 아니라 Pydantic 모델 클래스다. 그 외 전부 — function spec, MCP 스키마, 매뉴얼 — 가 여기서 파생된다.
- `evidence_ids`는 페이로드가 어떤 chunk id를 근거로 만들었는지 루프가 알아내는 훅이다. 이것 없는 도구는 인용 가능한 근거를 기여하지 못한다.
- `final_answer`는 예약되어 있다: 실행을 끝내는 것은 루프 고유의 원시 동작이므로, 어떤 레지스트리도 비슷한 이름의 도구로 이를 가릴 수 없다.

#### `app/agent/registry.py` 생성 — 레지스트리

**학습 행동 — 표면을 검토한다:** 도구 스키마가 나타나는 곳을 세고, 전부가 이 클래스에서 읽는지 확인한다.

<!-- src: app/agent/registry.py::ToolRegistry -->
```python
class ToolRegistry:
    """Named, immutable-by-convention collection of agent tools.

    The registry is the single source for three consumers: the provider gets
    strict function specs, the MCP server gets input schemas, and the system
    prompt gets a generated manual. One registration feeds all three, so the
    documentation the model reads can never drift from the schema it must obey.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool[Any]] = {}

    def register(self, tool: Tool[Any]) -> None:
        """Add one tool, rejecting duplicates instead of silently replacing them."""
        if not isinstance(tool, Tool):
            raise TypeError("only Tool values can be registered")
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool[Any]:
        """Return one registered tool or fail with the known names."""
        try:
            return self._tools[name]
        except KeyError:
            known = ", ".join(self.names) or "none"
            raise ValueError(f"unknown tool: {name} (registered: {known})") from None

    @property
    def names(self) -> tuple[str, ...]:
        """Return registered tool names in deterministic order."""
        return tuple(sorted(self._tools))

    @property
    def tools(self) -> tuple[Tool[Any], ...]:
        """Return registered tools in deterministic name order."""
        return tuple(self._tools[name] for name in self.names)

    def specs(self) -> list[dict[str, Any]]:
        """Return strict Responses-API function specs for every tool."""
        specs: list[dict[str, Any]] = []
        for tool in self.tools:
            payload = strict_response_format(tool.parameters)
            specs.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": payload["schema"],
                    "strict": True,
                }
            )
        return specs

    def manual(self) -> str:
        """Render the tool manual the system prompt feeds to the model."""
        lines = ["Available tools:"]
        for tool in self.tools:
            properties = tool.parameters.model_json_schema().get("properties", {})
            arguments = ", ".join(sorted(properties)) or "no arguments"
            lines.append(f"- {tool.name}({arguments}): {tool.description}")
        return "\n".join(lines)
```

**코드에서 꼭 볼 것**

- 중복은 대체가 아니라 거부다. 조용한 대체는 두 모듈이 한 이름을 놓고 싸우게 하고, 진 쪽은 영원히 모른다.
- `specs()`는 M4.4의 `strict_response_format`을 재사용한다 — **완성 응답을 구속하던 그 엄격 변환이 이제 도구 인자도 구속하므로, 하나의 스키마 규율이 두 경계를 모두 덮는다.**
- `manual()`은 생성된다. 모델이 읽는 문서는 모델이 지켜야 할 스키마와 어긋날 수 없다. 둘 다 같은 선언에서 나오기 때문이다.

### 집중 테스트와 그것이 지키는 계약

```bash
uv run pytest tests/agent/test_01_contracts.py tests/agent/test_02_registry.py -q
```

| 테스트가 깨뜨리는 것 | 지키는 계약 |
|---|---|
| 출력과 에러를 동시에 가진 관찰 | 실패와 성공은 상호 배타로 남는다 |
| 스텝이 하지 않은 호출에 답하는 관찰 | 스텝 출처는 조작될 수 없다 |
| 인용 없는 `SUPPORTED` | M4 라벨 계약이 에이전트 경계에서도 유지된다 |
| 답과 실패를 함께 가진 결과 | 종결 상태는 배타적이다 |
| 중복되거나 예약된 도구 이름 | 레지스트리는 하나의 정직한 이름 공간으로 남는다 |
| 열려 있거나 기본값이 있는 파라미터 스키마 | 엄격하게 강제 가능한 도구만 발행된다 |

### 이제 설명할 수 있어야 하는 것

답은 위의 **굵은 핵심 문장**에 있다.

- **실패한 도구 호출은 왜 예외가 아니라 관찰인가?**
  - **답:** 모델은 읽을 수 있는 것만 교정할 수 있다. 예외는 실행을 끝내고, 관찰은 다음 스텝을 가르친다.
- **답 계약은 왜 M4의 라벨 규칙을 반복하는가?**
  - **답:** 에이전트는 조작된 근거가 들어올 수 있는 새 경계다. 무효 조합을 표현 불가능하게 만들면 모든 소비자에게서 그 검사가 사라진다.
- **매뉴얼을 손으로 쓰면 무엇이 깨지는가?**
  - **답:** 매뉴얼과 스키마가 어긋나고, 모델은 존재하지 않는 도구를 호출하거나 스키마가 거부할 인자를 보내기 시작한다.

---

[모듈 개요](../03-build.md) · [다음: provider →](02-providers.md)
