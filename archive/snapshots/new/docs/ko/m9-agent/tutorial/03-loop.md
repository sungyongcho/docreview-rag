# M9.3 튜토리얼 3 — 루프가 안전 경계다

여기가 모듈의 중심이다: 손으로 짠 Thought → Tool → Observation 루프. 어떤 프레임워크도 이것을 대신 돌리지 않으므로, 루프가 하는 모든 보장은 손가락으로 가리킬 수 있는 보장이다 — **모델이 경로를 고르는 순간, 근거 게이트·예산·실패 보고를 강제할 수 있는 곳은 루프뿐이기 때문이다.**

**선행 조건:** M9.2 완료, `uv run pytest tests/agent/test_03_provider.py -q` 통과.

### 무엇을 정의하고, 무엇을 구현하고, 무엇을 들여다볼 것인가

| 영역 | 학습 행동 | 가져갈 것 |
|---|---|---|
| 지시문과 `final_answer` spec | **생성되는 프롬프트 표면을 직접 작성한다** | 마무리 동작은 엄격 스키마를 가진 도구다 |
| `_dispatch`와 `_final_answer` | 실패-관찰 변환 경로를 **구현한다** | 거부는 죽음이 아니라 피드백이다 |
| `run_agent` | 루프를 **구현한다** | 예산은 다음 요청 전에, fail-closed로 |

### 1. 마무리는 도구 호출이다

루프는 답을 산문에서 파싱하지 않는다. 함수 `final_answer` 하나를 추가로 발행하며, 그 파라미터는 엄격한 `AgentAnswer` 스키마다 — 결승선도 다른 모든 호출과 같은 형태 규율을 따르게 하기 위해서다.

#### `app/agent/loop.py` 생성 — 지시문과 마무리 spec

**학습 행동 — 생성되는 프롬프트 표면을 직접 작성한다:** 템플릿의 모든 규칙에 대해 그것을 강제하는 코드 경로를 찾아본다.

<!-- src: app/agent/loop.py::INSTRUCTIONS_TEMPLATE,final_answer_spec -->
```python
INSTRUCTIONS_TEMPLATE = """You are an evidence-checked review agent over SEC filings.

Work in explicit steps: decide what evidence you still need, call exactly the
tool that provides it, read the observation, and repeat. Never invent an
observation — every fact must come from a tool result in this conversation.

{manual}
- final_answer(label, answer, citations, rationale): Finish the run. \
SUPPORTED answers must cite only chunk_id values returned by earlier tool \
calls in this run; when the filings do not contain the answer, return the \
NOT_IN_DOCS label with no citations.

Call final_answer exactly once, only after the evidence in hand actually
supports the answer."""


def build_instructions(registry: ToolRegistry) -> str:
    """Render the default system prompt from the registry's generated manual."""
    return INSTRUCTIONS_TEMPLATE.format(manual=registry.manual())


def final_answer_spec() -> dict[str, Any]:
    """Return the strict function spec for the loop-owned final_answer tool."""
    payload = strict_response_format(AgentAnswer)
    return {
        "type": "function",
        "name": FINAL_ANSWER_NAME,
        "description": "Finish the run with a structured, citation-checked answer.",
        "parameters": payload["schema"],
        "strict": True,
    }
```

**코드에서 꼭 볼 것**

- 도구 매뉴얼은 `registry.manual()`에서 주입된다 — 프롬프트가 스키마와 같은 선언에서 생성된다.
- 템플릿의 모든 문장에는 강제 쌍둥이가 있다: 인용 규칙은 `_final_answer`가, 라벨 규칙은 `AgentAnswer`가, 정직 규칙은 근거 게이트가 검사한다. **프롬프트는 부탁하고, 코드는 검증한다 — 강제 없는 지시는 소원일 뿐이다.**

### 2. 모든 실패는 모델이 읽을 수 있는 것이 된다

#### `app/agent/loop.py` 확장 — dispatch와 근거 게이트

**학습 행동 — 실패-관찰 변환 경로를 구현한다:** 서로 다른 실패 계급을 세고, 각각이 예외가 아니라 관찰을 만드는지 확인한다.

<!-- src: app/agent/loop.py::_parse_arguments,_final_answer -->
```python
def _parse_arguments(arguments_json: str) -> dict[str, Any]:
    value = json.loads(arguments_json, object_pairs_hook=_strict_json_object)
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be a JSON object")
    return value


async def _dispatch(call: ToolCall, registry: ToolRegistry) -> tuple[Observation, tuple[int, ...]]:
    """Run one tool call and always return an explicit observation."""
    try:
        tool = registry.get(call.name)
    except ValueError as error:
        return Observation(call_id=call.call_id, name=call.name, error=str(error)), ()
    try:
        parameters = tool.parameters.model_validate(_parse_arguments(call.arguments_json))
    except (ValueError, ValidationError) as error:
        message = f"invalid arguments for {call.name}: {error}"
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    try:
        output = await tool.run(parameters)
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    try:
        output_json = json.dumps(output, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        message = f"{call.name} returned a non-JSON payload: {error}"
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    evidence = tool.evidence_ids(output) if tool.evidence_ids is not None else ()
    return (
        Observation(call_id=call.call_id, name=call.name, output_json=output_json),
        tuple(evidence),
    )


def _final_answer(call: ToolCall, evidence: frozenset[int]) -> tuple[AgentAnswer | None, str]:
    """Validate one final_answer call against the evidence this run actually saw."""
    try:
        answer = AgentAnswer.model_validate(_parse_arguments(call.arguments_json), strict=False)
    except (ValueError, ValidationError) as error:
        return None, f"invalid final_answer: {error}"
    uncited = tuple(
        citation.chunk_id for citation in answer.citations if citation.chunk_id not in evidence
    )
    if uncited:
        cited = ", ".join(str(chunk_id) for chunk_id in uncited)
        return None, (
            f"final_answer cites chunk ids no tool returned in this run: {cited}. "
            "Cite only retrieved evidence or answer NOT_IN_DOCS."
        )
    return answer, ""
```

**코드에서 꼭 볼 것**

- `_dispatch`는 알 수 없는 도구, 잘못된 인자, 실행 함수의 예외, JSON이 아닌 페이로드를 전부 `Observation(error=...)`로 바꾼다. 네 가지 다른 실수, 하나의 균일한 귀결: 무엇이 잘못됐는지 모델에게 텍스트로 알린다.
- `_final_answer`는 `strict=False`로 검증한다. 엄격 모델은 여전히 낯선 키를 금지하지만 JSON 와이어 강제 변환(배열 → 튜플)은 허용된다 — **엄격함은 계약의 것이지 와이어 포맷의 것이 아니며**, 이것을 틀렸을 때 유효한 답이 전부 거부됐다(버그 B1).
- 근거 게이트는 인용을 이번 실행에서 도구가 실제로 돌려준 chunk id와 대조한다. 위반 시 거부문이 문제의 id를 지목한다 — 모델은 그 id를 빼거나 다시 검색할 수 있다. **거부는 종결 실패가 아니라 관찰이므로, 실수 하나의 값은 실행 전체가 아니라 반복 하나다.**

### 3. 루프

#### `app/agent/loop.py` 확장 — `run_agent`

**학습 행동 — 루프를 구현한다:** 읽기 전에, 예산 검사가 fail-closed가 되려면 어디에 놓여야 하는지 예측하고 확인한다.

<!-- src: app/agent/loop.py::run_agent -->
```python
async def run_agent(
    question: str,
    *,
    registry: ToolRegistry,
    provider: ToolCallingProvider,
    budget: AgentBudget | None = None,
    instructions: str | None = None,
    wall_clock: WallClock = time.perf_counter,
) -> AgentResult:
    """Run the agent loop until final_answer, a budget stop, or a provider failure.

    Every iteration is one provider turn followed by explicit observations for
    each requested tool call. The loop is fail-closed: exhausted budgets and
    provider failures return a typed result instead of a partial answer, and a
    final answer may only cite chunk ids that a tool actually returned.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must not be blank")
    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry")
    if not isinstance(provider, ToolCallingProvider):
        raise TypeError("provider must implement ToolCallingProvider")
    limits = budget or AgentBudget()
    if not isinstance(limits, AgentBudget):
        raise TypeError("budget must be an AgentBudget")
    system_prompt = instructions or build_instructions(registry)

    tool_specs = [*registry.specs(), final_answer_spec()]
    input_items: list[dict[str, Any]] = [{"role": "user", "content": question}]
    steps: list[AgentStep] = []
    evidence: set[int] = set()
    total_input = 0
    total_output = 0
    started = wall_clock()

    def elapsed() -> float:
        seconds = wall_clock() - started
        if seconds < 0:
            raise ValueError("agent wall clock must be monotonic")
        return seconds

    while len(steps) < limits.max_iterations:
        remaining_output = limits.max_total_output_tokens - total_output
        if total_input >= limits.max_total_input_tokens or remaining_output <= 0:
            return _result(
                "budget_exceeded",
                answer=None,
                failure="token budget exhausted before the run could finish",
                steps=steps,
                input_tokens=total_input,
                output_tokens=total_output,
                seconds=elapsed(),
            )
        try:
            turn, request_ms = await provider.turn(
                system_prompt,
                input_items,
                tool_specs,
                max_output_tokens=remaining_output,
            )
        except Exception as error:
            return _result(
                "provider_error",
                answer=None,
                failure=f"{type(error).__name__}: {error}",
                steps=steps,
                input_tokens=total_input,
                output_tokens=total_output,
                seconds=elapsed(),
            )
        total_input += turn.input_tokens
        total_output += turn.output_tokens
        usage = StepUsage(
            model_name=provider.model_name,
            api_url=provider.api_url,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            request_time_ms=request_ms,
        )

        final_call = next(
            (call for call in turn.tool_calls if call.name == FINAL_ANSWER_NAME),
            None,
        )
        if final_call is not None:
            answer, problem = _final_answer(final_call, frozenset(evidence))
            if answer is not None:
                steps.append(
                    AgentStep(
                        step=len(steps) + 1,
                        output_text=turn.output_text,
                        tool_calls=turn.tool_calls,
                        observations=(),
                        usage=usage,
                    )
                )
                return _result(
                    "ok",
                    answer=answer,
                    failure=None,
                    steps=steps,
                    input_tokens=total_input,
                    output_tokens=total_output,
                    seconds=elapsed(),
                )
            rejection = Observation(
                call_id=final_call.call_id,
                name=final_call.name,
                error=problem,
            )
            steps.append(
                AgentStep(
                    step=len(steps) + 1,
                    output_text=turn.output_text,
                    tool_calls=turn.tool_calls,
                    observations=(rejection,),
                    usage=usage,
                )
            )
            _append_exchange(input_items, turn, {final_call.call_id: f"ERROR: {problem}"})
            continue

        if not turn.tool_calls:
            steps.append(
                AgentStep(
                    step=len(steps) + 1,
                    output_text=turn.output_text,
                    tool_calls=(),
                    observations=(),
                    usage=usage,
                )
            )
            if turn.output_text.strip():
                input_items.append({"role": "assistant", "content": turn.output_text})
            input_items.append(
                {
                    "role": "user",
                    "content": "No tool was called. Call a tool, or finish with final_answer.",
                }
            )
            continue

        observations: list[Observation] = []
        outputs: dict[str, str] = {}
        for call in turn.tool_calls:
            observation, chunk_ids = await _dispatch(call, registry)
            observations.append(observation)
            evidence.update(chunk_ids)
            if observation.error is not None:
                outputs[call.call_id] = f"ERROR: {observation.error}"
            else:
                outputs[call.call_id] = observation.output_json
        steps.append(
            AgentStep(
                step=len(steps) + 1,
                output_text=turn.output_text,
                tool_calls=turn.tool_calls,
                observations=tuple(observations),
                usage=usage,
            )
        )
        _append_exchange(input_items, turn, outputs)

    return _result(
        "budget_exceeded",
        answer=None,
        failure="iteration budget exhausted before final_answer",
        steps=steps,
        input_tokens=total_input,
        output_tokens=total_output,
        seconds=elapsed(),
    )
```

**코드에서 꼭 볼 것**

- 토큰 가드는 매 provider 호출 **전에** 돈다. 호출 후에 검사하면 예산은 이미 초과된 뒤에야 알아챌 수 있다 — fail-open의 정의 그 자체다.
- `final_answer`는 dispatch보다 먼저 처리되고, 유효한 답은 실행을 `ok`로 끝낸다. 무효한 답은 거부 관찰을 먹이고 루프는 계속된다. 두 결과 모두 `steps`에 쌓이므로 감사 추적에는 실수까지 포함된다.
- 도구 호출이 없는 턴은 명시적 넛지 관찰을 받고 반복 하나를 소모한다. 침묵은 공짜가 아니다 — 헛도는 모델은 영원히 돌지 않고 예산을 눈에 보이게 소진한다.
- provider 예외는 그때까지 완료된 모든 스텝과 함께 `provider_error`를 만든다. **모든 종료 경로가 전체 이력을 반환한다: 스스로를 설명하는 실패는 디버깅 세션이고, 그렇지 않은 실패는 어깨를 으쓱하는 것이다.**
- `_append_exchange`는 각 반복을 assistant 텍스트, `function_call` 항목, `function_call_output` 항목으로 다음 요청에 재생한다 — 모델의 기억은 정확히 루프가 보여주기로 한 것이다.

### 집중 테스트와 그것이 지키는 계약

```bash
uv run pytest tests/agent/test_04_loop.py -q
```

| 테스트가 깨뜨리는 것 | 지키는 계약 |
|---|---|
| 검색 한 번 뒤의 인용된 답 | 행복 경로는 전체 출처를 기록하고 재생한다 |
| 검색되지 않은 청크를 향한 인용 | 게이트는 거부하고, id를 지목하고, 회복을 허용한다 |
| 검색 없는 `NOT_IN_DOCS` | 정직한 빈 답에는 근거가 필요 없다 |
| 실행 중 실패하는 도구 | 실패는 관찰이 되고 실행은 계속된다 |
| 도구를 끝내 호출하지 않는 모델 | 넛지가 반복을 소모시켜 예산이 끝을 낸다 |
| `max_iterations`나 토큰 한도를 넘는 실행 | 예산은 `budget_exceeded`로 fail-closed |
| 예외를 던지는 provider | `provider_error`도 스텝 이력을 싣는다 |

### 이제 설명할 수 있어야 하는 것

답은 위의 **굵은 핵심 문장**에 있다.

- **`final_answer`는 왜 파싱된 산문이 아니라 함수인가?**
  - **답:** 결승선의 엄격 스키마가 답을 기계 검증 가능하게 만든다. 산문 파싱은 계약이 없애려던 모든 모호함을 다시 불러들인다.
- **인용 위반은 왜 실행을 끝내지 않는가?**
  - **답:** 거부는 나쁜 id를 지목하는 관찰이므로 모델은 예산 안에서 교정할 수 있다 — 실수 하나의 값은 반복 하나이지 실행이 아니다.
- **토큰 검사는 왜 provider 호출보다 먼저여야 하는가?**
  - **답:** 호출 뒤에는 토큰이 이미 쓰였다. 사후에만 알아챌 수 있는 예산은 fail-open이다.

---

[← 이전: provider](02-providers.md) · [모듈 개요](../03-build.md) · [다음: 내장 도구 →](04-builtin-tools.md)
