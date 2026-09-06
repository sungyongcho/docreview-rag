"""M9.6 MCP server bridge and the acceptance CLI."""

import asyncio
import json
import os
import subprocess
import sys

import mcp.types as mcp_types
from pydantic import BaseModel, ConfigDict, Field

from tests.support import need


class EchoParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)


def registry_with_echo(AG):
    async def run(params):
        return {"text": params.text}

    registry = AG.ToolRegistry()
    registry.register(
        AG.Tool(
            name="echo_text",
            description="Echo one nonblank text argument.",
            parameters=EchoParams,
            run=run,
        )
    )
    return registry


def handler_for(server, method):
    entry = server.get_request_handler(method)
    return entry.handler if hasattr(entry, "handler") else entry


def test_mcp_list_tools_mirrors_the_registry_schema(AG):
    need(AG, "build_mcp_server", "ToolRegistry", "Tool")
    registry = registry_with_echo(AG)
    server = AG.build_mcp_server(registry)

    result = asyncio.run(
        handler_for(server, "tools/list")(None, mcp_types.PaginatedRequestParams())
    )

    (tool,) = result.tools
    assert tool.name == "echo_text"
    assert tool.input_schema["additionalProperties"] is False
    assert tool.input_schema["required"] == ["text"]
    (spec,) = registry.specs()
    assert tool.input_schema == spec["parameters"]


def test_mcp_call_tool_returns_json_payloads_and_typed_errors(AG):
    need(AG, "build_mcp_server")
    server = AG.build_mcp_server(registry_with_echo(AG))
    call = handler_for(server, "tools/call")

    ok = asyncio.run(
        call(None, mcp_types.CallToolRequestParams(name="echo_text", arguments={"text": "hi"}))
    )
    assert ok.is_error is False
    assert json.loads(ok.content[0].text) == {"text": "hi"}

    invalid = asyncio.run(
        call(None, mcp_types.CallToolRequestParams(name="echo_text", arguments={"nope": 1}))
    )
    assert invalid.is_error is True and "text" in invalid.content[0].text

    unknown = asyncio.run(call(None, mcp_types.CallToolRequestParams(name="missing", arguments={})))
    assert unknown.is_error is True and "unknown tool" in unknown.content[0].text


def test_mcp_call_tool_converts_execution_and_serialization_failures(AG):
    async def fail(params):
        raise RuntimeError("api_key=sk-super-secret")

    async def non_json(params):
        return object()

    registry = AG.ToolRegistry()
    registry.register(
        AG.Tool(name="fail_tool", description="Fail safely.", parameters=EchoParams, run=fail)
    )
    registry.register(
        AG.Tool(
            name="non_json",
            description="Return a non-JSON value.",
            parameters=EchoParams,
            run=non_json,
        )
    )
    call = handler_for(AG.build_mcp_server(registry), "tools/call")

    failed = asyncio.run(
        call(None, mcp_types.CallToolRequestParams(name="fail_tool", arguments={"text": "x"}))
    )
    invalid = asyncio.run(
        call(None, mcp_types.CallToolRequestParams(name="non_json", arguments={"text": "x"}))
    )

    assert failed.is_error is True
    assert "sk-super-secret" not in failed.content[0].text
    assert invalid.is_error is True
    assert "serialization failed" in invalid.content[0].text


def test_cli_arguments_default_to_the_offline_demo(AG):
    need(AG, "run_agent")
    from app.agent.__main__ import arguments

    args = arguments(["--question", "How much did revenue increase?"])

    assert args.provider == "deterministic"
    assert args.k == 5
    assert args.max_iterations == 8
    assert args.mcp is False


def test_demo_provider_scripts_one_search_and_an_honest_absent_answer(AG):
    need(AG, "DeterministicToolProvider")
    from app.agent.__main__ import _demo_provider

    provider = _demo_provider("How much did revenue increase?", 5)

    first, second = provider._turns
    assert first.tool_calls[0].name == "search_filings"
    assert json.loads(first.tool_calls[0].arguments_json)["query"] == (
        "How much did revenue increase?"
    )
    final = json.loads(second.tool_calls[0].arguments_json)
    assert second.tool_calls[0].name == "final_answer"
    assert final["label"] == "NOT_IN_DOCS" and final["citations"] == []


def test_cli_help_is_independent_of_runtime_settings() -> None:
    environment = {**os.environ, "EMBEDDING_BATCH_SIZE": "0"}

    result = subprocess.run(
        [sys.executable, "-m", "app.agent", "--help"],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Run the evidence-checked filing agent" in result.stdout
