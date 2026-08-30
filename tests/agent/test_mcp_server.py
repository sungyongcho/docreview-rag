"""MCP bridge: the registry schema and typed tool failures."""

import asyncio
import json

import mcp.types as mcp_types
from pydantic import BaseModel, ConfigDict, Field

from app.agent.mcp_server import build_mcp_server
from app.agent.registry import ToolRegistry
from app.agent.tools import Tool


class EchoParams(BaseModel):
    """Closed argument schema for the echo tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)


def registry_with_echo():
    """Build a registry holding one echo tool."""

    async def run(params):
        """Return the text it was given."""
        return {"text": params.text}

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
    """Publish each tool over MCP under the same schema the registry holds."""
    registry = registry_with_echo()
    server = build_mcp_server(registry)

    result = asyncio.run(
        handler_for(server, "tools/list")(None, mcp_types.PaginatedRequestParams())
    )

    (tool,) = result.tools
    assert tool.name == "echo_text"
    assert tool.input_schema["additionalProperties"] is False
    assert tool.input_schema["required"] == ["text"]
    (spec,) = registry.specs()
    assert tool.input_schema == spec["parameters"]


def test_mcp_call_tool_returns_json_payloads_and_typed_errors():
    """Return the tool payload as JSON, and a typed error for a bad call."""
    server = build_mcp_server(registry_with_echo())
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
