"""Expose existing DocReview search, chunk reading, and year-grouped evidence over MCP."""

import asyncio

from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from app.agent.tools.filings import build_default_registry
from app.agent.tools.registry import ToolRegistry, execute_tool
from app.db.session_factory import default_session_factory

EXPOSED_TOOLS = ("search_filings", "compare_years", "fetch_chunk")

# Marks a failed result as a system failure (database, serialization) rather than
# one the caller can correct, so an MCP client can end the run instead of
# letting the model treat the failure as "nothing found".
SYSTEM_ERROR_META = "docreview/system_error"

COMPARE_NOTE = (
    " Returns evidence candidates only; does not extract revenue values "
    "or calculate differences or growth rates."
)


def error_result(message: str, *, system: bool) -> CallToolResult:
    """Report a failed call in the tool result, marking system failures."""
    return CallToolResult(
        is_error=True,
        content=[TextContent(type="text", text=message)],
        _meta={SYSTEM_ERROR_META: True} if system else None,
    )


def build_server(registry: ToolRegistry) -> Server:
    """Publish the existing input models and delegate execution to the registry.

    Parameters
    ----------
    registry : ToolRegistry
        Existing filing tools; only :data:`EXPOSED_TOOLS` are published. The
        loop-owned ``final_answer`` is never a server tool.

    Returns
    -------
    Server
        Low-level server whose list and call handlers reuse the registry's
        schemas, validation and error taxonomy.
    """
    exposed = {name: registry.get(name) for name in EXPOSED_TOOLS}

    async def list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        """Advertise the existing input models without copying their field rules."""
        return ListToolsResult(
            tools=[
                Tool(
                    name=tool.name,
                    description=tool.description
                    + (COMPARE_NOTE if tool.name == "compare_years" else ""),
                    input_schema=tool.parameters.model_json_schema(),
                )
                for tool in exposed.values()
            ]
        )

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        """Map existing domain results and safe errors onto MCP result fields."""
        if params.name not in exposed:
            return error_result(f"unknown tool: {params.name}", system=False)
        outcome = await execute_tool(registry, params.name, params.arguments or {})
        if outcome.error is not None:
            return error_result(outcome.error, system=outcome.system_error)
        assert outcome.output_json is not None
        return CallToolResult(
            content=[TextContent(type="text", text=outcome.output_json)],
            structured_content=outcome.output,
        )

    return Server("DocReview filings", on_list_tools=list_tools, on_call_tool=call_tool)


async def serve(registry: ToolRegistry) -> None:
    """Run a real stdio transport; the SDK owns JSON-RPC and lifecycle handling."""
    server = build_server(registry)
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


async def main() -> None:
    """Use the product database configuration and release its pool on shutdown."""
    from app.db.session import engine

    try:
        await serve(build_default_registry(default_session_factory))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
