"""Expose the agent tool registry as a Model Context Protocol stdio server."""

from typing import Any

from mcp.server import Server
from mcp.server.context import ServerRequestContext
import mcp.types as mcp_types

from app.agent.registry import ToolRegistry, execute_tool

SERVER_NAME = "docreview-agent"


def build_mcp_server(registry: ToolRegistry) -> Server:
    """Build one MCP server whose tool list mirrors the registry exactly.

    Parameters
    ----------
    registry : ToolRegistry
        Shared tool definitions, tolerant input schemas, and executable handlers.

    Returns
    -------
    Server
        Low-level MCP server exposing ``tools/list`` and ``tools/call``.

    Raises
    ------
    TypeError
        If registry is not a ``ToolRegistry``.

    Notes
    -----
    The published tool list is rendered once from :meth:`ToolRegistry.input_schemas`,
    the registry's own tolerant derivation, so this surface cannot drift from the
    registry. Every call dispatches through the shared
    :func:`~app.agent.registry.execute_tool` boundary, so validation, execution,
    and serialization failures carry exactly the errors the agent loop reports —
    a :class:`~app.agent.tools.ToolError` message verbatim, everything unexpected
    redacted — as ``is_error`` data rather than protocol exceptions.
    """
    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry")
    server: Server = Server(SERVER_NAME)
    published_tools = [
        mcp_types.Tool(
            name=item["name"],
            description=item["description"],
            input_schema=item["input_schema"],
        )
        for item in registry.input_schemas()
    ]

    async def list_tools(
        context: ServerRequestContext[Any],
        params: mcp_types.PaginatedRequestParams,
    ) -> mcp_types.ListToolsResult:
        """Publish every registered tool under the registry's own schema."""
        del context, params
        return mcp_types.ListToolsResult(tools=list(published_tools))

    async def call_tool(
        context: ServerRequestContext[Any],
        params: mcp_types.CallToolRequestParams,
    ) -> mcp_types.CallToolResult:
        """Run one registered tool, returning a typed error rather than raising."""
        del context
        outcome = await execute_tool(registry, params.name, params.arguments or {})
        if outcome.error is not None:
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=outcome.error)],
                is_error=True,
            )
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=outcome.output_json or "")],
            is_error=False,
        )

    server.add_request_handler("tools/list", mcp_types.PaginatedRequestParams, list_tools)
    server.add_request_handler("tools/call", mcp_types.CallToolRequestParams, call_tool)
    return server


async def serve_stdio(registry: ToolRegistry) -> None:
    """Run the registry-backed MCP server over stdio until the client closes it.

    Parameters
    ----------
    registry : ToolRegistry
        Tool set published over the stdio transport. Tools must own their
        per-call resources: the transport dispatches each request in its own
        task, so tool calls may run concurrently.

    Notes
    -----
    The transport owns framing only; tool meaning and schemas remain registry-owned.
    """
    from mcp.server.stdio import stdio_server

    server = build_mcp_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
