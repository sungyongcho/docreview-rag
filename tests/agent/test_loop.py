"""Agent loop: evidence gating, explicit observations, and fail-closed stops."""

import asyncio
import json
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from app.agent.loop import COMPACTED_OUTPUT, run_agent
from app.agent.provider import DeterministicToolProvider, ToolCallingProvider
from app.agent.registry import ToolRegistry
from app.agent.tools import EvidenceExtractor, Tool, ToolError
from app.agent.types import AgentBudget, AgentCitation, ToolCall
from tests.agent.support import turn

SOURCE_SHA256 = "a" * 64


def citation_values(chunk_id=7, **changes):
    """Build one citation payload with optional field replacements."""
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
    """Closed argument schema for the stand-in search tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1)


def search_tool(run):
    """Wrap one coroutine as the stand-in search tool with the shared extractor."""
    return Tool(
        name="search_notes",
        description="Search the corpus for citable evidence.",
        parameters=SearchParams,
        run=run,
        evidence_ids=lambda output: tuple(
            AgentCitation.model_validate(hit) for hit in output["hits"]
        ),
    )


def registry_with_search(*, chunk_id=7, fail=False):
    """Build a registry holding one search tool, optionally a failing one."""

    async def run(params):
        """Return one citable hit, or fail when the tool was built to fail."""
        if fail:
            raise RuntimeError("index unavailable")
        return {"hits": [citation_values(chunk_id)]}

    registry = ToolRegistry()
    registry.register(search_tool(run))
    return registry


def registry_with_staged_hits(hits_per_call):
    """Build a registry whose search tool returns the next staged hit list per call."""
    staged = list(hits_per_call)

    async def run(params):
        """Return the hits staged for this call position."""
        return {"hits": staged.pop(0)}

    registry = ToolRegistry()
    registry.register(search_tool(run))
    return registry


def call(name, arguments, *, call_id="call-1"):
    """Build one tool call carrying the given arguments."""
    return ToolCall(call_id=call_id, name=name, arguments_json=json.dumps(arguments))


def answer_arguments(chunk_id=7, *, label="SUPPORTED"):
    """Build final-answer arguments for a supported or an absent answer."""
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


def run_loop(turns, *, registry=None, budget=None):
    """Run the agent over a queue of staged turns and return the result and provider."""
    provider = DeterministicToolProvider(turns)
    result = asyncio.run(
        run_agent(
            "How much did revenue increase?",
            registry=registry if registry is not None else registry_with_search(),
            provider=provider,
            budget=budget,
        )
    )
    return result, provider


def test_search_then_cited_answer_succeeds_with_full_provenance():
    """Carry a searched citation into the answer, with the replay showing every step."""
    turns = [
        turn(
            output_text="I need evidence first.",
            tool_calls=(call("search_notes", {"query": "revenue"}),),
        ),
        turn(
            tool_calls=(call("final_answer", answer_arguments(), call_id="call-2"),),
            input_tokens=12,
            output_tokens=6,
        ),
    ]

    result, provider = run_loop(turns)

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


def test_uncited_final_answer_is_rejected_then_corrected():
    """Reject an answer citing what was never retrieved, and accept the corrected one."""
    turns = [
        turn(tool_calls=(call("search_notes", {"query": "revenue"}),)),
        turn(tool_calls=(call("final_answer", answer_arguments(99), call_id="call-2"),)),
        turn(tool_calls=(call("final_answer", answer_arguments(7), call_id="call-3"),)),
    ]

    result, _ = run_loop(turns)

    assert result.status == "ok"
    assert result.iterations == 3
    rejection = result.steps[1].observations[0]
    assert "99" in (rejection.error or "")


def test_not_in_docs_requires_no_evidence():
    """Let an absent answer finish without having retrieved anything."""
    turns = [
        turn(
            tool_calls=(call("final_answer", answer_arguments(label="NOT_IN_DOCS")),),
        )
    ]

    result, _ = run_loop(turns)

    assert result.status == "ok"
    assert result.answer is not None and result.answer.label == "NOT_IN_DOCS"


def test_final_answer_rejection_names_the_broken_field():
    """Name the violated field, so a natural NOT_IN_DOCS phrasing can be corrected."""
    natural = {
        "label": "NOT_IN_DOCS",
        "answer": "The filings do not disclose this.",
        "citations": [],
        "rationale": "No section covers the topic.",
    }
    turns = [
        turn(tool_calls=(call("final_answer", natural),)),
        turn(
            tool_calls=(
                call("final_answer", answer_arguments(label="NOT_IN_DOCS"), call_id="call-2"),
            ),
        ),
    ]

    result, _ = run_loop(turns)

    assert result.status == "ok"
    rejection = result.steps[0].observations[0].error or ""
    assert 'exactly the string "NOT_IN_DOCS"' in rejection


def test_tool_failures_become_explicit_observations():
    """Turn an unknown tool, bad arguments and a raising tool into three stated errors."""
    turns = [
        turn(
            tool_calls=(
                call("missing_tool", {"query": "x"}, call_id="call-1"),
                call("search_notes", {"wrong": "shape"}, call_id="call-2"),
                call("search_notes", {"query": "revenue"}, call_id="call-3"),
            ),
        ),
        turn(tool_calls=(call("final_answer", answer_arguments(), call_id="call-4"),)),
    ]
    registry = registry_with_search(fail=True)

    result, provider = run_loop(turns, registry=registry)

    observations = result.steps[0].observations
    assert "unknown tool: missing_tool" in (observations[0].error or "")
    assert "invalid arguments for search_notes" in (observations[1].error or "")
    assert "wrong" in (observations[1].error or "")
    assert "RuntimeError: tool search_notes failed" in (observations[2].error or "")
    replay = provider.requests[1][1]
    outputs = [item["output"] for item in replay if item.get("type") == "function_call_output"]
    assert all(output.startswith("ERROR:") for output in outputs)
    # The failing search produced no evidence, so the cited final answer is
    # rejected and the exhausted turn queue surfaces as a typed provider error.
    assert result.status == "provider_error"
    assert "99" not in (result.steps[1].observations[0].error or "")
    assert "7" in (result.steps[1].observations[0].error or "")


def test_tool_error_detail_reaches_the_model():
    """Pass a tool-authored safe message through instead of redacting it."""

    async def run(params):
        """Reject with the message the model needs to correct course."""
        raise ToolError("chunk 41 does not exist")

    registry = ToolRegistry()
    registry.register(search_tool(run))
    turns = [
        turn(tool_calls=(call("search_notes", {"query": "revenue"}),)),
        turn(
            tool_calls=(
                call("final_answer", answer_arguments(label="NOT_IN_DOCS"), call_id="call-2"),
            ),
        ),
    ]

    result, provider = run_loop(turns, registry=registry)

    assert result.status == "ok"
    assert result.steps[0].observations[0].error == "chunk 41 does not exist"
    replay = provider.requests[1][1]
    outputs = [item["output"] for item in replay if item.get("type") == "function_call_output"]
    assert outputs == ["ERROR: chunk 41 does not exist"]


def test_strict_argument_json_rejects_duplicates_and_non_finite_values():
    """State a duplicate key and a non-finite number as argument errors."""
    duplicate = ToolCall(
        call_id="call-1",
        name="search_notes",
        arguments_json='{"query": "a", "query": "b"}',
    )
    non_finite = ToolCall(
        call_id="call-2",
        name="search_notes",
        arguments_json='{"query": Infinity}',
    )
    turns = [
        turn(tool_calls=(duplicate, non_finite)),
        turn(
            tool_calls=(
                call("final_answer", answer_arguments(label="NOT_IN_DOCS"), call_id="call-3"),
            ),
        ),
    ]

    result, _ = run_loop(turns)

    assert result.status == "ok"
    observations = result.steps[0].observations
    assert "duplicate JSON key" in (observations[0].error or "")
    assert "non-finite" in (observations[1].error or "")


def test_no_tool_call_gets_an_explicit_nudge():
    """Answer a turn that acted on nothing with an instruction to use the final tool."""
    turns = [
        turn(output_text="Thinking out loud without acting."),
        turn(tool_calls=(call("final_answer", answer_arguments(label="NOT_IN_DOCS")),)),
    ]

    result, provider = run_loop(turns)

    assert result.status == "ok"
    assert result.steps[0].tool_calls == ()
    nudge = provider.requests[1][1][-1]
    assert nudge["role"] == "user" and "final_answer" in nudge["content"]


def test_iteration_budget_exhaustion_fails_closed():
    """Stop at the iteration ceiling with no answer and a stated reason."""
    turns = [
        turn(tool_calls=(call("search_notes", {"query": "revenue"}),)),
        turn(tool_calls=(call("search_notes", {"query": "revenue"}, call_id="call-2"),)),
    ]

    result, _ = run_loop(turns, budget=AgentBudget(max_iterations=2))

    assert result.status == "budget_exceeded"
    assert result.answer is None
    assert "iteration budget" in (result.failure or "")
    assert result.iterations == 2


def test_token_budget_stops_before_another_provider_call():
    """Stop before spending a further turn once the token ceiling is crossed."""
    turns = [
        turn(
            tool_calls=(call("search_notes", {"query": "revenue"}),),
            input_tokens=90,
            output_tokens=10,
        ),
        turn(tool_calls=(call("final_answer", answer_arguments(), call_id="call-2"),)),
    ]

    result, provider = run_loop(
        turns,
        budget=AgentBudget(max_iterations=8, max_total_input_tokens=80),
    )

    assert result.status == "budget_exceeded"
    assert "token budget" in (result.failure or "")
    assert len(provider.requests) == 1


def test_output_floor_stops_before_a_futile_request():
    """Stop when the remaining output allowance is below the provider's minimum."""
    turns = [
        turn(
            tool_calls=(call("search_notes", {"query": "revenue"}),),
            output_tokens=10,
        ),
        turn(tool_calls=(call("final_answer", answer_arguments(), call_id="call-2"),)),
    ]

    result, provider = run_loop(
        turns,
        budget=AgentBudget(max_iterations=8, max_total_output_tokens=20),
    )

    assert result.status == "budget_exceeded"
    assert "token budget" in (result.failure or "")
    assert len(provider.requests) == 1


def test_incomplete_turn_fails_closed_as_budget_exceeded():
    """Stop after a turn the output ceiling cut off instead of nudging a truncated reply."""
    turns = [turn(output_text="The filings sho", incomplete=True)]

    result, provider = run_loop(turns)

    assert result.status == "budget_exceeded"
    assert "cut" in (result.failure or "")
    assert result.iterations == 1
    assert len(provider.requests) == 1


def test_provider_failure_returns_a_typed_result():
    """Report a provider failure as a typed result rather than raising."""
    result, _ = run_loop([])

    assert result.status == "provider_error"
    assert "RuntimeError" in (result.failure or "")


def test_provider_failure_does_not_expose_exception_secrets():
    """Keep a credential inside a provider exception out of the reported failure."""

    class SecretProvider(ToolCallingProvider):
        """Provider whose failure carries a secret that must not escape."""

        provider_name = "test"
        model_name = "test-model"
        api_url = "test://provider"

        async def turn(
            self,
            instructions,
            input_items,
            tools,
            *,
            max_output_tokens,
        ):
            """Fail with a message containing a credential."""
            raise RuntimeError("api_key=sk-super-secret")

    result = asyncio.run(
        run_agent(
            "question",
            registry=registry_with_search(),
            provider=SecretProvider(),
        )
    )

    assert result.status == "provider_error"
    assert "sk-super-secret" not in (result.failure or "")


def test_final_answer_requires_the_complete_retrieved_identity():
    """Reject a citation whose text was altered from what retrieval returned."""
    forged = answer_arguments()
    forged["citations"][0]["citation"] = "Fabricated citation"
    turns = [
        turn(tool_calls=(call("search_notes", {"query": "revenue"}),)),
        turn(tool_calls=(call("final_answer", forged, call_id="call-2"),)),
        turn(tool_calls=(call("final_answer", answer_arguments(), call_id="call-3"),)),
    ]

    result, _ = run_loop(turns)

    assert result.status == "ok"
    assert "identity" in (result.steps[1].observations[0].error or "")


def test_conflicting_chunk_identity_is_rejected_and_kept_out_of_evidence():
    """Refuse a tool result that re-reports a known chunk under an altered identity."""
    registry = registry_with_staged_hits(
        [
            [citation_values(7)],
            [citation_values(7, citation="Rewritten citation")],
        ]
    )
    forged = answer_arguments()
    forged["citations"][0]["citation"] = "Rewritten citation"
    turns = [
        turn(tool_calls=(call("search_notes", {"query": "revenue"}),)),
        turn(tool_calls=(call("search_notes", {"query": "revenue"}, call_id="call-2"),)),
        turn(tool_calls=(call("final_answer", forged, call_id="call-3"),)),
        turn(tool_calls=(call("final_answer", answer_arguments(), call_id="call-4"),)),
    ]

    result, _ = run_loop(turns, registry=registry)

    assert result.status == "ok"
    assert "conflicting immutable identity" in (result.steps[1].observations[0].error or "")
    # The forged identity never entered evidence, so citing it is rejected while
    # the original identity from the first search still validates.
    assert "identity" in (result.steps[2].observations[0].error or "")
    assert result.answer is not None
    assert result.answer.citations[0].citation == "NVDA FY2024 · Item 7"


def test_final_turn_cannot_succeed_after_token_budget_overshoot():
    """Refuse a final answer produced by the turn that broke the token ceiling."""
    turns = [
        turn(
            tool_calls=(call("final_answer", answer_arguments(label="NOT_IN_DOCS")),),
            input_tokens=101,
            output_tokens=1,
        )
    ]

    result, _ = run_loop(
        turns,
        budget=AgentBudget(max_total_input_tokens=100),
    )

    assert result.status == "budget_exceeded"
    assert result.answer is None
    assert result.total_input_tokens == 101
    assert result.iterations == 1


def test_final_answer_must_be_the_only_call_in_its_turn():
    """Reject a turn that pairs the final answer with another call."""
    turns = [
        turn(
            tool_calls=(
                call("search_notes", {"query": "revenue"}),
                call(
                    "final_answer",
                    answer_arguments(label="NOT_IN_DOCS"),
                    call_id="call-2",
                ),
            ),
        ),
        turn(
            tool_calls=(
                call(
                    "final_answer",
                    answer_arguments(label="NOT_IN_DOCS"),
                    call_id="call-3",
                ),
            ),
        ),
    ]

    result, _ = run_loop(turns)

    assert result.status == "ok"
    assert len(result.steps[0].observations) == 2
    assert all("only tool call" in (item.error or "") for item in result.steps[0].observations)


def test_old_observations_are_compacted_out_of_the_replay():
    """Stub observation payloads older than the keep window, keeping recent ones verbatim."""
    turns = [
        turn(tool_calls=(call("search_notes", {"query": "one"}, call_id="call-1"),)),
        turn(tool_calls=(call("search_notes", {"query": "two"}, call_id="call-2"),)),
        turn(tool_calls=(call("search_notes", {"query": "three"}, call_id="call-3"),)),
        turn(tool_calls=(call("final_answer", answer_arguments(), call_id="call-4"),)),
    ]

    result, provider = run_loop(turns)

    assert result.status == "ok"
    outputs_by_call = {
        item["call_id"]: item["output"]
        for item in provider.requests[3][1]
        if item.get("type") == "function_call_output"
    }
    assert outputs_by_call["call-1"] == COMPACTED_OUTPUT
    assert json.loads(outputs_by_call["call-2"])["hits"][0]["chunk_id"] == 7
    assert json.loads(outputs_by_call["call-3"])["hits"][0]["chunk_id"] == 7
    # The request one turn earlier still carried every payload verbatim.
    third_request = {
        item["call_id"]: item["output"]
        for item in provider.requests[2][1]
        if item.get("type") == "function_call_output"
    }
    assert COMPACTED_OUTPUT not in third_request.values()


def test_malformed_evidence_extractor_becomes_an_observation():
    """State a broken evidence extractor as an observation instead of failing the run."""
    registry = registry_with_search()
    tool = registry.get("search_notes")
    registry = ToolRegistry()
    registry.register(
        Tool(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters,
            run=tool.run,
            evidence_ids=cast(EvidenceExtractor, lambda output: (7,)),
        )
    )
    turns = [
        turn(tool_calls=(call("search_notes", {"query": "revenue"}),)),
        turn(
            tool_calls=(
                call(
                    "final_answer",
                    answer_arguments(label="NOT_IN_DOCS"),
                    call_id="call-2",
                ),
            ),
        ),
    ]

    result, _ = run_loop(turns, registry=registry)

    assert result.status == "ok"
    assert "evidence extraction failed" in (result.steps[0].observations[0].error or "")
