"""Bridge MCP-discovered filing tools into the agent's tool registry.

The agent loop keeps validating arguments, extracting evidence and checking
citations against the registry's own contracts; only execution travels over MCP.
"""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Protocol

from mcp.types import CallToolResult, ListToolsResult
from pydantic import BaseModel

from app.tools.registry import ToolError, ToolRegistry


class MCPSystemError(RuntimeError):
    """A successful-looking tool result the bridge cannot use, such as one without data.

    It is deliberately not a :class:`ToolError`, so the registry treats it as an
    unexpected failure and the agent run ends as ``tool_error`` instead of letting
    the model answer as though nothing were found. A server-reported system failure
    needs no such mapping: it arrives as a JSON-RPC error the client already raises.
    """


class ToolCaller(Protocol):
    """The one MCP client call a bridged tool makes."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Call one server tool with JSON arguments."""
        ...


class ToolServerClient(ToolCaller, Protocol):
    """What the bridge needs from a connected MCP client: listing and calling tools.

    ``mcp.Client`` satisfies it; the bridge depends on nothing else of the client.
    """

    async def list_tools(self) -> ListToolsResult:
        """List the server's tools."""
        ...


def mcp_runner(client: ToolCaller, name: str) -> Callable[[BaseModel], Awaitable[dict[str, Any]]]:
    """Bind one discovered tool name to a call over the shared MCP client."""

    async def run(params: BaseModel) -> dict[str, Any]:
        """Send the validated arguments over MCP and map the result back.

        A JSON-RPC error the client raises, such as a system failure, propagates
        unchanged; only an ``isError`` result becomes a correctable :class:`ToolError`.
        """
        result = await client.call_tool(name, params.model_dump(mode="json"))
        if result.is_error:
            raise ToolError("; ".join(item.text for item in result.content if item.type == "text"))
        if not isinstance(result.structured_content, dict):
            raise MCPSystemError(f"tool {name} returned no structured content")
        return result.structured_content

    return run


async def mcp_tool_registry(client: ToolServerClient, contracts: ToolRegistry) -> ToolRegistry:
    """Register every tool the server lists, executing each one over MCP.

    Parameters
    ----------
    client : ToolServerClient
        Connected MCP client; every call of every question shares it.
    contracts : ToolRegistry
        The app's own tools, which supply parameter models, descriptions and
        evidence extraction. Their ``run`` functions are never called.

    Returns
    -------
    ToolRegistry
        Tools whose execution is an MCP ``tools/call``.

    Raises
    ------
    ValueError
        When the server lists a tool the app does not know or publishes an input
        schema that differs from the app's parameter model.
    """
    listing = await client.list_tools()
    bridge = ToolRegistry()
    for discovered in listing.tools:
        original = contracts.get(discovered.name)
        if discovered.input_schema != original.parameters.model_json_schema():
            raise ValueError(f"MCP tool {discovered.name} publishes a different input schema")
        bridge.register(
            replace(
                original,
                description=discovered.description or original.description,
                run=mcp_runner(client, discovered.name),
            )
        )
    return bridge
