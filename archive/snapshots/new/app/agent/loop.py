"""Hand-rolled Thought → Tool → Observation loop with fail-closed budgets."""

from __future__ import annotations

from collections.abc import Callable
import json
import time
from typing import Any

from pydantic import ValidationError

from app.agent.provider import ProviderTurn, ToolCallingProvider
from app.agent.registry import ToolRegistry
from app.agent.types import (
    AgentAnswer,
    AgentBudget,
    AgentResult,
    AgentStep,
    Observation,
    StepUsage,
    ToolCall,
)
from app.llm import strict_response_format

type WallClock = Callable[[], float]

FINAL_ANSWER_NAME = "final_answer"

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


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


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


def _result(
    status: str,
    *,
    answer: AgentAnswer | None,
    failure: str | None,
    steps: list[AgentStep],
    input_tokens: int,
    output_tokens: int,
    seconds: float,
) -> AgentResult:
    return AgentResult.model_validate(
        {
            "status": status,
            "answer": answer,
            "failure": failure,
            "iterations": len(steps),
            "total_input_tokens": input_tokens,
            "total_output_tokens": output_tokens,
            "total_time_seconds": seconds,
            "steps": tuple(steps),
        }
    )


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


def _append_exchange(
    input_items: list[dict[str, Any]],
    turn: ProviderTurn,
    outputs: dict[str, str],
) -> None:
    """Replay one assistant turn and its observations into the conversation."""
    if turn.output_text.strip():
        input_items.append({"role": "assistant", "content": turn.output_text})
    for call in turn.tool_calls:
        input_items.append(
            {
                "type": "function_call",
                "call_id": call.call_id,
                "name": call.name,
                "arguments": call.arguments_json,
            }
        )
        if call.call_id in outputs:
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": outputs[call.call_id],
                }
            )
