"""Expose the agent tool registry as a Model Context Protocol stdio server."""

import json
from typing import Any

from mcp.server import Server
from mcp.server.context import ServerRequestContext
import mcp.types as mcp_types
from pydantic import ValidationError

from app.agent.registry import ToolRegistry
from app.agent.tools import safe_runtime_error
from app.llm import strict_response_format

SERVER_NAME = "docreview-agent"


def build_mcp_server(registry: ToolRegistry) -> Server:
    """Build one MCP server whose tool list mirrors the registry exactly.

    Parameters
    ----------
    registry : ToolRegistry
        Shared tool definitions, strict schemas, and executable handlers.

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
    Schemas come from the same strict transform used by the agent provider. Validation,
    execution, and serialization failures become ``is_error`` data rather than escaping
    as protocol exceptions.
    """
    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry")
    server: Server = Server(SERVER_NAME)

    async def list_tools(
        context: ServerRequestContext[Any],
        params: mcp_types.PaginatedRequestParams,
    ) -> mcp_types.ListToolsResult:
        del context, params
        return mcp_types.ListToolsResult(
            tools=[
                mcp_types.Tool(
                    name=tool.name,
                    description=tool.description,
                    input_schema=dict(strict_response_format(tool.parameters)["schema"]),
                )
                for tool in registry.tools
            ]
        )

    async def call_tool(
        context: ServerRequestContext[Any],
        params: mcp_types.CallToolRequestParams,
    ) -> mcp_types.CallToolResult:
        del context
        try:
            tool = registry.get(params.name)
            parameters = tool.parameters.model_validate(params.arguments or {})
        except (ValueError, ValidationError) as error:
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=str(error))],
                is_error=True,
            )
        try:
            output = await tool.run(parameters)
        except Exception as error:
            message = safe_runtime_error(error, "tool execution")
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=message)],
                is_error=True,
            )
        try:
            payload = json.dumps(output, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as error:
            message = safe_runtime_error(error, "tool serialization")
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=message)],
                is_error=True,
            )
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=payload)],
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
        Tool set published over the stdio transport.

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
