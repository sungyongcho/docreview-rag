"""Immutable evidence identities agree across the sequential and middleware agents."""

import asyncio
import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel
import pytest

from app.agent.loop import run_agent
from app.agent.review_middleware import ReviewGate, StopOnSystemFailure, final_answer_format
from app.agent.tools.registry import Tool, ToolRegistry
from app.agent.types import ToolCall
from app.contracts.evidence import EvidenceCitation
from tests.agent.support import RecordingToolProvider, ScriptedChatModel, turn


class ReadParams(BaseModel):
    """Identify a synthetic stored version to read."""

    version: str


def identity(version: str) -> dict[str, Any]:
    """One chunk whose immutable source digest varies between storage reads."""
    return dict(
        chunk_id=1,
        doc_id="d",
        citation="source",
        start_char=0,
        end_char=10,
        source_sha256=version * 64,
    )


def calls(*versions: str) -> list[dict[str, Any]]:
    """Read the same stored chunk once per requested version."""
    return [
        dict(name="read_chunk", args={"version": v}, id=f"read-{i}", type="tool_call")
        for i, v in enumerate(versions)
    ]


@pytest.mark.parametrize("versions", [("a", "b"), ("b", "a"), ("a", "a")])
@pytest.mark.parametrize("candidate", ["a", "b"])
@pytest.mark.parametrize("parallel", [True, False])
def test_stored_identity_changes_end_both_agents_before_final(versions, candidate, parallel):
    """Collisions stop before either proposed citation; identical reads still support an answer."""
    if versions[0] == versions[1] and candidate != versions[0]:
        return

    async def read(params):
        """Read a staged source identity, without a database or provider."""
        return {"hits": [identity(params.version)]}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="read_chunk",
            description="Read a stored chunk",
            parameters=ReadParams,
            run=read,
            evidence_ids=lambda out: tuple(EvidenceCitation.model_validate(h) for h in out["hits"]),
        )
    )

    @tool(response_format="content_and_artifact")
    async def read_chunk(version: str):
        """Read one version of a stored chunk."""
        out = await read(ReadParams(version=version))
        return json.dumps(out), {"structured_content": out}

    batches = [calls(*versions)] if parallel else [calls(v) for v in versions]
    final = dict(
        name="final_answer",
        id="final",
        type="tool_call",
        args=dict(
            label="SUPPORTED",
            answer="The source names the entity.",
            citations=[identity(candidate)],
            rationale="Checked identity",
        ),
    )
    replies = [AIMessage(content="", tool_calls=batch) for batch in [*batches, [final]]]
    model = ScriptedChatModel.from_replies(*replies)
    agent = create_agent(
        model,
        [read_chunk],
        middleware=[StopOnSystemFailure(), ReviewGate(registry)],
        response_format=final_answer_format(),
        checkpointer=InMemorySaver(),
    )
    provider = RecordingToolProvider(
        [
            turn(
                tool_calls=tuple(
                    ToolCall(call_id=c["id"], name=c["name"], arguments_json=json.dumps(c["args"]))
                    for c in batch
                )
            )
            for batch in [*batches, [final]]
        ]
    )

    async def run():
        """Exercise both entry points on the same staged tool reads."""
        state = await agent.ainvoke(
            {"messages": [HumanMessage("Read the entity")]},
            {"configurable": {"thread_id": "ledger"}},
        )
        result = await run_agent("Read the entity", registry=registry, provider=provider)
        return state, result

    state, result = asyncio.run(run())
    if versions[0] != versions[1]:
        assert "conflicting immutable identity for chunk 1" in state["failure"]
        assert state.get("structured_response") is None
        assert result.status == "tool_error"
        assert "conflicting immutable identity for chunk 1" in result.failure
        assert len(model.requests) == len(batches)
        assert len(provider.requests) == len(batches)
    else:
        assert state["structured_response"].label == "SUPPORTED"
        assert result.status == "ok"
