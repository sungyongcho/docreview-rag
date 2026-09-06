"""M9.3 agent loop: evidence gating, explicit observations, and fail-closed stops."""

import asyncio
import json

from pydantic import BaseModel, ConfigDict, Field

from tests.agent.test_03_provider import TickClock, turn
from tests.support import need

SOURCE_SHA256 = "a" * 64


def citation_values(chunk_id=7, **changes):
    values = {
        "chunk_id": chunk_id,
        "doc_id": "NVDA-FY2024",
        "citation": "NVDA FY2024 · Item 7",
        "start_char": 700,
        "end_char": 750,
        "source_sha256": SOURCE_SHA256,
    }
    values.update(changes)
    return values


class SearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1)


def registry_with_search(AG, *, chunk_id=7, fail=False):
    async def run(params):
        if fail:
            raise RuntimeError("index unavailable")
        return {"hits": [citation_values(chunk_id)]}

    registry = AG.ToolRegistry()
    registry.register(
        AG.Tool(
            name="search_notes",
            description="Search the corpus for citable evidence.",
            parameters=SearchParams,
            run=run,
            evidence_ids=lambda output: tuple(
                AG.AgentCitation.model_validate(hit) for hit in output["hits"]
            ),
        )
    )
    return registry


def call(AG, name, arguments, *, call_id="call-1"):
    return AG.ToolCall(call_id=call_id, name=name, arguments_json=json.dumps(arguments))


def answer_arguments(chunk_id=7, *, label="SUPPORTED"):
    if label == "NOT_IN_DOCS":
        return {
            "label": "NOT_IN_DOCS",
            "answer": "NOT_IN_DOCS",
            "citations": [],
            "rationale": "The filings do not discuss this topic.",
        }
    return {
        "label": "SUPPORTED",
        "answer": "Revenue increased by ten percent.",
        "citations": [citation_values(chunk_id)],
        "rationale": "The cited chunk states the increase.",
    }


def run_loop(AG, turns, *, registry=None, budget=None):
    provider = AG.DeterministicToolProvider(turns, clock=TickClock())
    result = asyncio.run(
        AG.run_agent(
            "How much did revenue increase?",
            registry=registry if registry is not None else registry_with_search(AG),
            provider=provider,
            budget=budget,
        )
    )
    return result, provider


def test_search_then_cited_answer_succeeds_with_full_provenance(AG):
    need(AG, "run_agent", "DeterministicToolProvider", "ToolRegistry", "Tool", "ToolCall")
    turns = [
        turn(
            AG,
            output_text="I need evidence first.",
            tool_calls=(call(AG, "search_notes", {"query": "revenue"}),),
        ),
        turn(
            AG,
            tool_calls=(call(AG, "final_answer", answer_arguments(), call_id="call-2"),),
            input_tokens=12,
            output_tokens=6,
        ),
    ]

    result, provider = run_loop(AG, turns)

    assert result.status == "ok"
    assert result.answer is not None
    assert result.answer.citations[0].chunk_id == 7
    assert result.iterations == 2
    assert result.total_input_tokens == 22
    assert result.total_output_tokens == 11
    assert result.steps[0].observations[0].error is None
    replayed = provider.requests[1][1]
    kinds = [item.get("type") or item.get("role") for item in replayed]
    assert kinds == ["user", "assistant", "function_call", "function_call_output"]
    assert json.loads(replayed[3]["output"])["hits"][0]["chunk_id"] == 7


def test_uncited_final_answer_is_rejected_then_corrected(AG):
    need(AG, "run_agent")
    turns = [
        turn(AG, tool_calls=(call(AG, "search_notes", {"query": "revenue"}),)),
        turn(AG, tool_calls=(call(AG, "final_answer", answer_arguments(99), call_id="call-2"),)),
        turn(AG, tool_calls=(call(AG, "final_answer", answer_arguments(7), call_id="call-3"),)),
    ]

    result, _ = run_loop(AG, turns)

    assert result.status == "ok"
    assert result.iterations == 3
    rejection = result.steps[1].observations[0]
    assert rejection.error is not None and "99" in rejection.error


def test_not_in_docs_requires_no_evidence(AG):
    need(AG, "run_agent")
    turns = [
        turn(
            AG,
            tool_calls=(call(AG, "final_answer", answer_arguments(label="NOT_IN_DOCS")),),
        )
    ]

    result, _ = run_loop(AG, turns)

    assert result.status == "ok"
    assert result.answer is not None and result.answer.label == "NOT_IN_DOCS"


def test_tool_failures_become_explicit_observations(AG):
    need(AG, "run_agent")
    turns = [
        turn(
            AG,
            tool_calls=(
                call(AG, "missing_tool", {"query": "x"}, call_id="call-1"),
                call(AG, "search_notes", {"wrong": "shape"}, call_id="call-2"),
                call(AG, "search_notes", {"query": "revenue"}, call_id="call-3"),
            ),
        ),
        turn(AG, tool_calls=(call(AG, "final_answer", answer_arguments(), call_id="call-4"),)),
    ]
    registry = registry_with_search(AG, fail=True)

    result, provider = run_loop(AG, turns, registry=registry)

    observations = result.steps[0].observations
    assert "unknown tool: missing_tool" in observations[0].error
    assert "invalid arguments" in observations[1].error
    assert "RuntimeError: tool search_notes failed" in observations[2].error
    replay = provider.requests[1][1]
    outputs = [item["output"] for item in replay if item.get("type") == "function_call_output"]
    assert all(output.startswith("ERROR:") for output in outputs)
    # The failing search produced no evidence, so the cited final answer is
    # rejected and the exhausted turn queue surfaces as a typed provider error.
    assert result.status == "provider_error"
    assert "99" not in (result.steps[1].observations[0].error or "")
    assert "7" in result.steps[1].observations[0].error


def test_no_tool_call_gets_an_explicit_nudge(AG):
    need(AG, "run_agent")
    turns = [
        turn(AG, output_text="Thinking out loud without acting."),
        turn(AG, tool_calls=(call(AG, "final_answer", answer_arguments(label="NOT_IN_DOCS")),)),
    ]

    result, provider = run_loop(AG, turns)

    assert result.status == "ok"
    assert result.steps[0].tool_calls == ()
    nudge = provider.requests[1][1][-1]
    assert nudge["role"] == "user" and "final_answer" in nudge["content"]


def test_iteration_budget_exhaustion_fails_closed(AG):
    need(AG, "run_agent", "AgentBudget")
    turns = [
        turn(AG, tool_calls=(call(AG, "search_notes", {"query": "revenue"}),)),
        turn(AG, tool_calls=(call(AG, "search_notes", {"query": "revenue"}, call_id="call-2"),)),
    ]

    result, _ = run_loop(AG, turns, budget=AG.AgentBudget(max_iterations=2))

    assert result.status == "budget_exceeded"
    assert result.answer is None
    assert "iteration budget" in result.failure
    assert result.iterations == 2


def test_token_budget_stops_before_another_provider_call(AG):
    need(AG, "run_agent", "AgentBudget")
    turns = [
        turn(
            AG,
            tool_calls=(call(AG, "search_notes", {"query": "revenue"}),),
            input_tokens=90,
            output_tokens=10,
        ),
        turn(AG, tool_calls=(call(AG, "final_answer", answer_arguments(), call_id="call-2"),)),
    ]

    result, provider = run_loop(
        AG,
        turns,
        budget=AG.AgentBudget(max_iterations=8, max_total_input_tokens=80),
    )

    assert result.status == "budget_exceeded"
    assert "token budget" in result.failure
    assert len(provider.requests) == 1


def test_provider_failure_returns_a_typed_result(AG):
    need(AG, "run_agent")

    result, _ = run_loop(AG, [])

    assert result.status == "provider_error"
    assert "RuntimeError" in result.failure


def test_provider_failure_does_not_expose_exception_secrets(AG):
    class SecretProvider(AG.ToolCallingProvider):
        provider_name = "test"
        model_name = "test-model"
        api_url = "test://provider"

        async def _request(
            self,
            instructions,
            input_items,
            tools,
            *,
            max_output_tokens,
        ):
            raise RuntimeError("api_key=sk-super-secret")

    result = asyncio.run(
        AG.run_agent(
            "question",
            registry=registry_with_search(AG),
            provider=SecretProvider(),
        )
    )

    assert result.status == "provider_error"
    assert "sk-super-secret" not in (result.failure or "")


def test_final_answer_requires_the_complete_retrieved_identity(AG):
    forged = answer_arguments()
    forged["citations"][0]["citation"] = "Fabricated citation"
    turns = [
        turn(AG, tool_calls=(call(AG, "search_notes", {"query": "revenue"}),)),
        turn(AG, tool_calls=(call(AG, "final_answer", forged, call_id="call-2"),)),
        turn(AG, tool_calls=(call(AG, "final_answer", answer_arguments(), call_id="call-3"),)),
    ]

    result, _ = run_loop(AG, turns)

    assert result.status == "ok"
    assert "identity" in (result.steps[1].observations[0].error or "")


def test_final_turn_cannot_succeed_after_token_budget_overshoot(AG):
    turns = [
        turn(
            AG,
            tool_calls=(call(AG, "final_answer", answer_arguments(label="NOT_IN_DOCS")),),
            input_tokens=101,
            output_tokens=1,
        )
    ]

    result, _ = run_loop(
        AG,
        turns,
        budget=AG.AgentBudget(max_total_input_tokens=100),
    )

    assert result.status == "budget_exceeded"
    assert result.answer is None
    assert result.total_input_tokens == 101
    assert result.iterations == 1


def test_final_answer_must_be_the_only_call_in_its_turn(AG):
    turns = [
        turn(
            AG,
            tool_calls=(
                call(AG, "search_notes", {"query": "revenue"}),
                call(
                    AG,
                    "final_answer",
                    answer_arguments(label="NOT_IN_DOCS"),
                    call_id="call-2",
                ),
            ),
        ),
        turn(
            AG,
            tool_calls=(
                call(
                    AG,
                    "final_answer",
                    answer_arguments(label="NOT_IN_DOCS"),
                    call_id="call-3",
                ),
            ),
        ),
    ]

    result, _ = run_loop(AG, turns)

    assert result.status == "ok"
    assert len(result.steps[0].observations) == 2
    assert all("only tool call" in (item.error or "") for item in result.steps[0].observations)


def test_malformed_evidence_extractor_becomes_an_observation(AG):
    registry = registry_with_search(AG)
    tool = registry.get("search_notes")
    registry = AG.ToolRegistry()
    registry.register(
        AG.Tool(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters,
            run=tool.run,
            evidence_ids=lambda output: (7,),
        )
    )
    turns = [
        turn(AG, tool_calls=(call(AG, "search_notes", {"query": "revenue"}),)),
        turn(
            AG,
            tool_calls=(
                call(
                    AG,
                    "final_answer",
                    answer_arguments(label="NOT_IN_DOCS"),
                    call_id="call-2",
                ),
            ),
        ),
    ]

    result, _ = run_loop(AG, turns, registry=registry)

    assert result.status == "ok"
    assert "evidence extraction failed" in (result.steps[0].observations[0].error or "")
