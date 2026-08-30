"""Hand-rolled Thought → Tool → Observation loop with fail-closed budgets."""

from collections.abc import Callable, Mapping
import functools
import json
import time
from typing import Any

from pydantic import ValidationError

from app.agent.provider import ProviderTurn, ToolCallingProvider
from app.agent.registry import ToolRegistry
from app.agent.tools import FINAL_ANSWER_NAME, ToolError, safe_runtime_error
from app.agent.types import (
    AgentAnswer,
    AgentBudget,
    AgentCitation,
    AgentResult,
    AgentStatus,
    AgentStep,
    Observation,
    StepUsage,
    ToolCall,
)
from app.llm.provider import strict_json_loads, strict_response_format, validation_errors

type WallClock = Callable[[], float]

# The Responses API rejects max_output_tokens below 16, so a smaller remaining
# allowance can only buy a failed request: the run is out of budget, and saying
# so beats reporting the resulting 400 as a provider error.
MIN_TURN_OUTPUT_TOKENS = 16

# Observation payloads older than this many exchanges are compacted out of the
# replay. Every turn resends the whole history, so old multi-KB tool outputs
# cost quadratic input tokens; the loop's evidence map keeps their identities,
# the citation gate never reads the replay, and the model can re-fetch a chunk.
KEEP_OUTPUT_EXCHANGES = 2
COMPACTED_OUTPUT = (
    "[compacted to save tokens; the chunk ids this call returned remain "
    "citable — call fetch_chunk again if the text itself is needed]"
)

INSTRUCTIONS_TEMPLATE = """You are an evidence-checked review agent over SEC filings.

Work in explicit steps: decide what evidence you still need, call exactly the
tool that provides it, read the observation, and repeat. Never invent an
observation — every fact must come from a tool result in this conversation.

{manual}
- {final_answer_signature}: Finish the run. SUPPORTED answers must cite only \
chunk_id values returned by earlier tool calls in this run. When the filings \
do not contain the answer, set label to NOT_IN_DOCS, set answer to exactly \
the string "NOT_IN_DOCS", and cite nothing.

Call final_answer exactly once, only after the evidence in hand actually
supports the answer."""


def build_instructions(registry: ToolRegistry) -> str:
    """Render the default system prompt from the registry's generated manual.

    The final_answer signature is generated from :class:`AgentAnswer` the same
    way the registry generates every tool line from its schema, so the prose
    the model reads cannot drift from the spec it must satisfy.
    """
    properties = AgentAnswer.model_json_schema().get("properties", {})
    signature = f"{FINAL_ANSWER_NAME}({', '.join(sorted(properties))})"
    return INSTRUCTIONS_TEMPLATE.format(
        manual=registry.manual(),
        final_answer_signature=signature,
    )


@functools.cache
def final_answer_spec() -> dict[str, Any]:
    """Return the strict function spec for the loop-owned final_answer tool.

    The spec is a pure function of :class:`AgentAnswer`, so it is generated once
    per process instead of once per run.
    """
    payload = strict_response_format(AgentAnswer)
    return {
        "type": "function",
        "name": FINAL_ANSWER_NAME,
        "description": "Finish the run with a structured, citation-checked answer.",
        "parameters": payload["schema"],
        "strict": True,
    }


def _parse_arguments(arguments_json: str) -> dict[str, Any]:
    """Parse tool arguments as a strict JSON object with no duplicate or non-finite values."""
    try:
        value = strict_json_loads(arguments_json)
    except RecursionError:
        # json.loads recurses; without this a pathologically nested argument
        # string would escape the ValueError handlers and crash the run.
        raise ValueError("tool arguments nest too deeply") from None
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be a JSON object")
    return value


async def _dispatch(
    call: ToolCall,
    registry: ToolRegistry,
) -> tuple[Observation, tuple[AgentCitation, ...]]:
    """Run one tool call and return an explicit, identity-checked observation.

    Parameters
    ----------
    call : ToolCall
        Provider-requested tool identity and raw strict-JSON arguments.
    registry : ToolRegistry
        Single source of executable tools and parameter schemas.

    Returns
    -------
    tuple[Observation, tuple[AgentCitation, ...]]
        JSON observation plus complete evidence identities, or an error and no
        evidence when lookup, validation, execution, serialization, or extraction fails.

    Notes
    -----
    Tool exceptions never escape into the agent loop. A :class:`ToolError` and a
    validation failure carry their model-actionable detail verbatim — both are
    authored against the model's own input, never against provider payloads —
    while every unexpected exception is redacted through
    :func:`safe_runtime_error` so raw messages cannot leak into public results.
    """
    try:
        tool = registry.get(call.name)
    except ValueError as error:
        return Observation(call_id=call.call_id, name=call.name, error=str(error)), ()
    try:
        parameters = tool.parameters.model_validate(_parse_arguments(call.arguments_json))
    except ValidationError as error:
        details = "; ".join(validation_errors(error))
        message = f"invalid arguments for {call.name}: {details}"
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    except ValueError as error:
        message = f"invalid arguments for {call.name}: {error}"
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    try:
        output = await tool.run(parameters)
    except ToolError as error:
        message = str(error).strip() or safe_runtime_error(error, f"tool {call.name}")
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    except Exception as error:
        message = safe_runtime_error(error, f"tool {call.name}")
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    try:
        output_json = json.dumps(output, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        message = safe_runtime_error(error, f"tool {call.name} serialization")
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    try:
        evidence = tool.evidence_ids(output) if tool.evidence_ids is not None else ()
        if not isinstance(evidence, tuple) or any(
            not isinstance(item, AgentCitation) for item in evidence
        ):
            raise TypeError("evidence extractor must return AgentCitation values")
        evidence_ids = [item.chunk_id for item in evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence extractor returned duplicate chunk ids")
    except Exception as error:
        message = safe_runtime_error(error, f"tool {call.name} evidence extraction")
        return Observation(call_id=call.call_id, name=call.name, error=message), ()
    return (
        Observation(call_id=call.call_id, name=call.name, output_json=output_json),
        evidence,
    )


def _final_answer(
    call: ToolCall,
    evidence: Mapping[int, AgentCitation],
) -> tuple[AgentAnswer | None, str]:
    """Validate one final answer against every immutable identity the run observed.

    Parameters
    ----------
    call : ToolCall
        The loop-owned ``final_answer`` call.
    evidence : Mapping[int, AgentCitation]
        Complete source identities returned by successful tool observations.

    Returns
    -------
    tuple[AgentAnswer | None, str]
        Accepted answer and an empty problem, or no answer and a rejection whose
        field-level detail the model can act on. The detail is rendered from the
        model's own arguments, so passing it back leaks nothing.
    """
    try:
        answer = AgentAnswer.model_validate(_parse_arguments(call.arguments_json), strict=False)
    except ValidationError as error:
        details = "; ".join(validation_errors(error))
        return None, f"invalid final_answer: {details}"
    except ValueError as error:
        return None, f"invalid final_answer: {error}"
    missing = tuple(
        citation.chunk_id for citation in answer.citations if citation.chunk_id not in evidence
    )
    if missing:
        cited = ", ".join(str(chunk_id) for chunk_id in missing)
        return None, (
            f"final_answer cites chunk ids no tool returned in this run: {cited}. "
            "Cite only retrieved evidence or answer NOT_IN_DOCS."
        )
    mismatched = tuple(
        citation.chunk_id
        for citation in answer.citations
        if evidence[citation.chunk_id] != citation
    )
    if mismatched:
        cited = ", ".join(str(chunk_id) for chunk_id in mismatched)
        return None, f"final_answer citation identity does not match retrieved evidence: {cited}."
    return answer, ""


def _compact_exchanges(
    input_items: list[dict[str, Any]],
    exchange_ends: list[int],
) -> None:
    """Replace observation payloads older than the keep window with a stub.

    Only successful ``function_call_output`` items are compacted: error outputs
    stay verbatim so the model does not repeat a rejected call, and the last
    ``KEEP_OUTPUT_EXCHANGES`` exchanges stay verbatim so the model can read what
    it just retrieved.
    """
    if len(exchange_ends) <= KEEP_OUTPUT_EXCHANGES:
        return
    cutoff = exchange_ends[-(KEEP_OUTPUT_EXCHANGES + 1)]
    for item in input_items[:cutoff]:
        if item.get("type") != "function_call_output":
            continue
        output = item.get("output", "")
        if output == COMPACTED_OUTPUT or output.startswith("ERROR:"):
            continue
        item["output"] = COMPACTED_OUTPUT


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

    Parameters
    ----------
    question : str
        Nonblank filing question that starts the conversation.
    registry : ToolRegistry
        Immutable-by-convention tool set shared with provider schemas and MCP.
    provider : ToolCallingProvider
        Injected deterministic or OpenAI turn provider.
    budget : AgentBudget | None
        Optional cumulative turn and token limits.
    instructions : str | None
        Optional complete system prompt; the registry-generated prompt is the default.
    wall_clock : WallClock
        Monotonic seconds clock used for request latency and end-to-end duration.

    Returns
    -------
    AgentResult
        Accepted identity-checked answer or a typed fail-closed terminal result.

    Raises
    ------
    ValueError
        If the question is blank or the wall clock moves backwards.
    TypeError
        If registry, provider, or budget does not satisfy its declared contract.

    Notes
    -----
    Every iteration is one provider turn followed by explicit observations. A final
    answer must be the turn's only call and every citation must match the complete
    source identity previously returned by a tool. The run stops as
    ``budget_exceeded`` before a request whose remaining output allowance is below
    the provider floor, after a turn whose usage overshoots a cumulative limit,
    and after an ``incomplete`` turn the output ceiling cut off — a truncated turn
    can never produce an accepted answer. Observation payloads older than
    ``KEEP_OUTPUT_EXCHANGES`` exchanges are compacted out of the replay to keep
    input tokens linear in run length.
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
    exchange_ends: list[int] = []
    steps: list[AgentStep] = []
    evidence: dict[int, AgentCitation] = {}
    total_input = 0
    total_output = 0
    started = wall_clock()

    def elapsed() -> float:
        """Seconds since the run began, refusing a clock that went backwards."""
        seconds = wall_clock() - started
        if seconds < 0:
            raise ValueError("agent wall clock must be monotonic")
        return seconds

    def finish(
        status: AgentStatus,
        *,
        answer: AgentAnswer | None = None,
        failure: str | None = None,
    ) -> AgentResult:
        """Build the terminal result, letting the model reject impossible success states."""
        return AgentResult.model_validate(
            {
                "status": status,
                "answer": answer,
                "failure": failure,
                "iterations": len(steps),
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_time_seconds": elapsed(),
                "steps": tuple(steps),
            }
        )

    def record_step(
        turn: ProviderTurn,
        observations: tuple[Observation, ...],
        usage: StepUsage,
    ) -> None:
        """Append one billed provider turn with its explicit observations."""
        steps.append(
            AgentStep(
                step=len(steps) + 1,
                output_text=turn.output_text,
                tool_calls=turn.tool_calls,
                observations=observations,
                usage=usage,
            )
        )

    def mark_exchange() -> None:
        """Record the replay boundary of the exchange that just ended."""
        exchange_ends.append(len(input_items))

    while len(steps) < limits.max_iterations:
        remaining_output = limits.max_total_output_tokens - total_output
        out_of_input = total_input >= limits.max_total_input_tokens
        if out_of_input or remaining_output < MIN_TURN_OUTPUT_TOKENS:
            return finish(
                "budget_exceeded",
                failure="token budget exhausted before the run could finish",
            )
        _compact_exchanges(input_items, exchange_ends)
        request_started = wall_clock()
        try:
            turn = await provider.turn(
                system_prompt,
                input_items,
                tool_specs,
                max_output_tokens=remaining_output,
            )
        except Exception as error:
            return finish(
                "provider_error",
                failure=safe_runtime_error(error, "provider request"),
            )
        request_ms = (wall_clock() - request_started) * 1000.0
        if request_ms < 0:
            raise ValueError("agent wall clock must be monotonic")
        total_input += turn.input_tokens
        total_output += turn.output_tokens
        usage = StepUsage(
            model_name=provider.model_name,
            api_url=provider.api_url,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            request_time_ms=request_ms,
        )

        if (
            total_input > limits.max_total_input_tokens
            or total_output > limits.max_total_output_tokens
        ):
            record_step(turn, (), usage)
            return finish(
                "budget_exceeded",
                failure="provider usage exceeded the cumulative token budget",
            )
        if turn.incomplete:
            record_step(turn, (), usage)
            return finish(
                "budget_exceeded",
                failure="the output-token ceiling cut the provider turn off before it finished",
            )

        final_calls = tuple(call for call in turn.tool_calls if call.name == FINAL_ANSWER_NAME)
        final_call = final_calls[0] if len(final_calls) == 1 else None
        if final_calls and len(turn.tool_calls) != 1:
            problem = "final_answer must be the only tool call in its provider turn"
            rejections = tuple(
                Observation(call_id=call.call_id, name=call.name, error=problem)
                for call in turn.tool_calls
            )
            record_step(turn, rejections, usage)
            _append_exchange(
                input_items,
                turn,
                {call.call_id: f"ERROR: {problem}" for call in turn.tool_calls},
            )
            mark_exchange()
            continue
        if final_call is not None:
            answer, problem = _final_answer(final_call, evidence)
            if answer is not None:
                record_step(turn, (), usage)
                return finish("ok", answer=answer)
            rejection = Observation(
                call_id=final_call.call_id,
                name=final_call.name,
                error=problem,
            )
            record_step(turn, (rejection,), usage)
            _append_exchange(input_items, turn, {final_call.call_id: f"ERROR: {problem}"})
            mark_exchange()
            continue

        if not turn.tool_calls:
            record_step(turn, (), usage)
            if turn.output_text.strip():
                input_items.append({"role": "assistant", "content": turn.output_text})
            input_items.append(
                {
                    "role": "user",
                    "content": "No tool was called. Call a tool, or finish with final_answer.",
                }
            )
            mark_exchange()
            continue

        observations: list[Observation] = []
        outputs: dict[str, str] = {}
        for call in turn.tool_calls:
            observation, citations = await _dispatch(call, registry)
            observations.append(observation)
            conflict = next(
                (
                    citation
                    for citation in citations
                    if citation.chunk_id in evidence and evidence[citation.chunk_id] != citation
                ),
                None,
            )
            if conflict is not None:
                observation = Observation(
                    call_id=call.call_id,
                    name=call.name,
                    error=(
                        "tool returned conflicting immutable identity for "
                        f"chunk {conflict.chunk_id}"
                    ),
                )
                observations[-1] = observation
            else:
                evidence.update({citation.chunk_id: citation for citation in citations})
            if observation.error is not None:
                outputs[call.call_id] = f"ERROR: {observation.error}"
            else:
                outputs[call.call_id] = observation.output_json
        record_step(turn, tuple(observations), usage)
        _append_exchange(input_items, turn, outputs)
        mark_exchange()

    return finish(
        "budget_exceeded",
        failure="iteration budget exhausted before final_answer",
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
