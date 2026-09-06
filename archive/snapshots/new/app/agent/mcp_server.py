"""Expose the agent tool registry as a Model Context Protocol stdio server."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.context import ServerRequestContext
import mcp.types as mcp_types
from pydantic import ValidationError

from app.agent.registry import ToolRegistry
from app.llm import strict_response_format

SERVER_NAME = "docreview-agent"


def build_mcp_server(registry: ToolRegistry) -> Server:
    """Build one MCP server whose tool list mirrors the registry exactly.

    The input schemas come from the same strict transform the agent loop sends
    to the LLM, so an MCP client and the in-process agent see one contract.
    Tool failures come back as ``is_error`` results with a readable message —
    the same explicit-observation rule the loop applies.
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
            output = await tool.run(parameters)
            payload = json.dumps(output, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        except (ValueError, ValidationError) as error:
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=str(error))],
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
    """Run the registry-backed MCP server over stdio until the client closes it."""
    from mcp.server.stdio import stdio_server

    server = build_mcp_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
