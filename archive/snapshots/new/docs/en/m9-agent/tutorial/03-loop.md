# M9.3 Tutorial 3 — The loop is the safety boundary

This is the module's center: the hand-rolled Thought → Tool → Observation loop. No framework runs it, so every guarantee it makes is one you can point at — because **when the model chooses the route, the loop is the only place where evidence gating, budgets, and failure reporting can be enforced at all.**

**Prerequisite:** M9.2 is complete and `uv run pytest tests/agent/test_03_provider.py -q` passes.

### What to define, what to implement, and what to inspect

| Area | Learning action | What to take away |
|---|---|---|
| Instructions and `final_answer` spec | **Write the generated prompt surface** | The finishing move is a tool with a strict schema |
| `_dispatch` and `_final_answer` | **Implement** the failure-to-observation paths | Rejection is feedback, not death |
| `run_agent` | **Implement the loop** | Budgets fail closed, before the next request |

### 1. Finishing is a tool call

The loop never parses prose for an answer. It publishes one extra function, `final_answer`, whose parameters are the strict `AgentAnswer` schema — so the finish line has the same shape discipline as every other call.

#### Create `app/agent/loop.py` — instructions and the finishing spec

**Learning action — write the generated prompt surface:** find every rule in the template that a later code path enforces.

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

**What to look for in the code**

- The tool manual is injected from `registry.manual()` — the prompt is generated from the same declarations the schemas come from.
- Every sentence in the template has an enforcement twin: the citation rule is checked in `_final_answer`, the label rule in `AgentAnswer`, the honesty rule by the evidence gate. **The prompt asks; the code verifies — instructions without enforcement are wishes.**

### 2. Every failure becomes something the model can read

#### Extend `app/agent/loop.py` — dispatch and the evidence gate

**Learning action — implement the failure-to-observation paths:** count the distinct failure classes and confirm each produces an observation, not an exception.

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

**What to look for in the code**

- `_dispatch` converts unknown tools, invalid arguments, runner exceptions, and non-JSON payloads into `Observation(error=...)`. Four different mistakes, one uniform consequence: the model is told, in text, what went wrong.
- `_final_answer` validates with `strict=False`. The strict model still forbids unknown keys, but JSON-wire coercions (array → tuple) are allowed — **strictness belongs to the contract, not to the wire format**, and getting this wrong rejected every valid answer during the build (bug B1).
- The evidence gate compares citations against chunk ids actually returned by tools this run. A violation names the offending ids in the rejection — the model can drop them or search again. **Rejection is an observation, not a terminal failure, so one mistake costs one iteration instead of the whole run.**

### 3. The loop

#### Extend `app/agent/loop.py` — `run_agent`

**Learning action — implement the loop:** before reading, predict where the budget checks must sit for them to fail closed; then verify.

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

**What to look for in the code**

- The token guard runs **before** each provider call. Checking after would mean the budget can only be noticed once it is already blown — the definition of failing open.
- `final_answer` is handled before dispatch, and a valid answer ends the run with `ok`; an invalid one feeds a rejection observation and the loop continues. Both outcomes append to `steps`, so the audit trail includes the mistakes.
- A turn with no tool calls gets an explicit nudge observation and costs an iteration. Silence is not free — an idling model exhausts its budget visibly instead of spinning forever.
- Provider exceptions produce `provider_error` with every step completed so far. **Every exit path returns the full history: a failed run that explains itself is a debugging session; one that doesn't is a shrug.**
- `_append_exchange` replays each iteration into the next request as assistant text, `function_call` items, and `function_call_output` items — the model's memory is exactly what the loop chooses to show it.

### Focused tests and the contract they keep

```bash
uv run pytest tests/agent/test_04_loop.py -q
```

| What the test breaks | Contract it protects |
|---|---|
| A cited answer after one search | The happy path records full provenance and replays it |
| A citation to an unretrieved chunk | The gate rejects, names the ids, and allows recovery |
| `NOT_IN_DOCS` with no searches | An honest empty answer needs no evidence |
| A failing tool mid-run | Failures become observations; the run continues |
| A model that never calls tools | The nudge costs iterations until the budget ends it |
| A run past `max_iterations` or token limits | Budgets fail closed with `budget_exceeded` |
| A provider that raises | `provider_error` still carries the step history |

### What you should be able to explain now

The answers are in the **bold key sentences** above.

- **Why is `final_answer` a function instead of parsed prose?**
  - **Answer:** A strict schema at the finish line makes the answer machine-checkable; prose parsing would reintroduce every ambiguity the contracts exist to remove.
- **Why does a citation violation not end the run?**
  - **Answer:** The rejection is an observation naming the bad ids, so the model can correct within its budget — one mistake costs one iteration, not the run.
- **Why must the token check precede the provider call?**
  - **Answer:** After the call the tokens are already spent; a budget that can only be noticed in hindsight fails open.

---

[← Previous: providers](02-providers.md) · [Module overview](../03-build.md) · [Next: built-in tools →](04-builtin-tools.md)
