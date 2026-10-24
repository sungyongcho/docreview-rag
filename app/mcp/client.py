"""Bridge MCP-discovered filing tools into the agent's tool registry.

The agent loop keeps validating arguments, extracting evidence and checking
citations against the registry's own contracts; only execution travels over MCP.
"""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from mcp import Client
from pydantic import BaseModel

from app.agent.tools.registry import ToolError, ToolRegistry


class MCPSystemError(RuntimeError):
    """A successful-looking tool result the bridge cannot use, such as one without data.

    It is deliberately not a :class:`ToolError`, so the registry treats it as an
    unexpected failure and the agent run ends as ``tool_error`` instead of letting
    the model answer as though nothing were found. A server-reported system failure
    needs no such mapping: it arrives as a JSON-RPC error the client already raises.
    """


def mcp_runner(client: Client, name: str) -> Callable[[BaseModel], Awaitable[dict[str, Any]]]:
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


async def mcp_tool_registry(client: Client, contracts: ToolRegistry) -> ToolRegistry:
    """Register every tool the server lists, executing each one over MCP.

    Parameters
    ----------
    client : Client
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
