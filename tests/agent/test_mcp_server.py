"""MCP bridge: the registry schema and typed tool failures."""

import asyncio
import json

import mcp.types as mcp_types
from pydantic import BaseModel, ConfigDict, Field

from app.agent.mcp_server import build_mcp_server
from app.agent.registry import ToolRegistry
from app.agent.tools import Tool, ToolError


class EchoParams(BaseModel):
    """Closed argument schema for the echo tool, with one optional field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    repeat: int | None = None


def registry_with_echo():
    """Build a registry holding one echo tool."""

    async def run(params):
        """Return the text it was given, repeated when asked."""
        return {"text": params.text * (params.repeat or 1)}

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="echo_text",
            description="Echo one nonblank text argument.",
            parameters=EchoParams,
            run=run,
        )
    )
    return registry


def handler_for(server, method):
    """Return the server handler registered for one method."""
    entry = server.get_request_handler(method)
    return entry.handler if hasattr(entry, "handler") else entry


def test_mcp_list_tools_mirrors_the_registry_schema():
    """Publish each tool over MCP under the registry's own tolerant schema."""
    registry = registry_with_echo()
    server = build_mcp_server(registry)

    result = asyncio.run(
        handler_for(server, "tools/list")(None, mcp_types.PaginatedRequestParams())
    )

    (tool,) = result.tools
    (published,) = registry.input_schemas()
    assert tool.name == "echo_text"
    assert tool.input_schema == published["input_schema"]
    assert tool.input_schema["additionalProperties"] is False
    assert tool.input_schema["required"] == ["text"]


def test_mcp_call_tool_accepts_omitted_optional_arguments():
    """Run a call that omits optional fields, the idiomatic MCP client shape."""
    call = handler_for(build_mcp_server(registry_with_echo()), "tools/call")

    ok = asyncio.run(
        call(None, mcp_types.CallToolRequestParams(name="echo_text", arguments={"text": "hi"}))
    )

    assert ok.is_error is False
    assert json.loads(ok.content[0].text) == {"text": "hi"}


def test_mcp_call_tool_reports_errors_the_way_the_loop_does():
    """Project validation failures and forward ToolError messages verbatim."""

    async def missing_chunk(params):
        """Raise the model-actionable failure the tool contract forwards."""
        raise ToolError(f"chunk for {params.text!r} does not exist")

    registry = registry_with_echo()
    registry.register(
        Tool(
            name="fetch_probe",
            description="Raise a ToolError naming its cause.",
            parameters=EchoParams,
            run=missing_chunk,
        )
    )
    call = handler_for(build_mcp_server(registry), "tools/call")

    invalid = asyncio.run(
        call(None, mcp_types.CallToolRequestParams(name="echo_text", arguments={"nope": 1}))
    )
    assert invalid.is_error is True
    assert invalid.content[0].text.startswith("invalid arguments for echo_text:")
    assert "input_value" not in invalid.content[0].text

    unknown = asyncio.run(call(None, mcp_types.CallToolRequestParams(name="missing", arguments={})))
    assert unknown.is_error is True and "unknown tool" in unknown.content[0].text

    actionable = asyncio.run(
        call(None, mcp_types.CallToolRequestParams(name="fetch_probe", arguments={"text": "x"}))
    )
    assert actionable.is_error is True
    assert actionable.content[0].text == "chunk for 'x' does not exist"


def test_mcp_call_tool_converts_execution_and_serialization_failures():
    """Convert a raising tool and an unserializable result into typed errors."""

    async def fail(params):
        """Raise so the bridge has an execution failure to convert."""
        raise RuntimeError("api_key=sk-super-secret")

    async def non_json(params):
        """Return a value that cannot be serialized to JSON."""
        return object()

    registry = ToolRegistry()
    registry.register(
        Tool(name="fail_tool", description="Fail safely.", parameters=EchoParams, run=fail)
    )
    registry.register(
        Tool(
            name="non_json",
            description="Return a non-JSON value.",
            parameters=EchoParams,
            run=non_json,
        )
    )
    call = handler_for(build_mcp_server(registry), "tools/call")

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
