"""Expose existing DocReview search, chunk reading, and year-grouped evidence over MCP."""

import argparse
import asyncio
from collections.abc import Sequence
import signal
import sys
from types import FrameType

from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INTERNAL_ERROR,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from starlette.applications import Starlette
import uvicorn

from app.agent.tools.filings import build_default_registry
from app.agent.tools.registry import ToolRegistry, execute_tool
from app.config import get_settings
from app.db.session_factory import default_session_factory

EXPOSED_TOOLS = ("search_filings", "compare_years", "fetch_chunk")

# The HTTP transport binds loopback only; the SDK's DNS-rebinding protection then
# accepts loopback Host and Origin headers alone. There is no authentication yet.
HTTP_HOST = "127.0.0.1"

COMPARE_NOTE = (
    " Returns evidence candidates only; does not extract revenue values "
    "or calculate differences or growth rates."
)


def error_result(message: str) -> CallToolResult:
    """Report a failure the caller can correct, such as invalid arguments, in the result."""
    return CallToolResult(is_error=True, content=[TextContent(type="text", text=message)])


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
        """Map existing domain results and safe errors onto MCP results or JSON-RPC errors.

        A failure the model can correct is an ``isError`` result it can read. A system
        failure, such as a database error, is raised as a JSON-RPC ``INTERNAL_ERROR``
        instead: clients raise that rather than hand it to the model, which would
        otherwise read a failed search as "nothing found". ``outcome.error`` is
        already redacted by :func:`execute_tool`.
        """
        if params.name not in exposed:
            return error_result(f"unknown tool: {params.name}")
        outcome = await execute_tool(registry, params.name, params.arguments or {})
        if outcome.error is not None:
            if outcome.system_error:
                raise MCPError(code=INTERNAL_ERROR, message=outcome.error)
            return error_result(outcome.error)
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


def build_http_app(registry: ToolRegistry) -> Starlette:
    """Mount the unchanged low-level server at ``/mcp``; the SDK owns HTTP framing.

    The SDK's default SSE-capable responses are kept: on that path a client that
    cancels a call closes its response stream and the running tool is cancelled,
    which the ``json_response=True`` path does not do.
    """
    return build_server(registry).streamable_http_app(host=HTTP_HOST)


def _exit_on_sigterm(signum: int, frame: FrameType | None) -> None:
    """Turn SIGTERM into :class:`SystemExit` so pending ``finally`` blocks still run."""
    del frame
    raise SystemExit(128 + signum)


async def serve_http(registry: ToolRegistry, *, port: int) -> None:
    """Serve Streamable HTTP on loopback until a signal stops the process.

    Unlike stdio, no client owns this process: it outlives every client. uvicorn
    shuts down gracefully on SIGINT or SIGTERM and then re-raises the signal
    against the previous handler. Under the default SIGTERM handler that would
    kill the process before its caller's cleanup, so while serving SIGTERM ends
    in ``SystemExit(143)`` instead. Call this from the main thread.
    """
    config = uvicorn.Config(
        build_http_app(registry), host=HTTP_HOST, port=port, log_level="warning"
    )
    previous = signal.signal(signal.SIGTERM, _exit_on_sigterm)
    try:
        await uvicorn.Server(config).serve()
    finally:
        signal.signal(signal.SIGTERM, previous)


def _port(text: str) -> int:
    """Parse a TCP port a client can be told, rejecting 0 and out-of-range values."""
    try:
        port = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a port number: {text!r}") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port must be between 1 and 65535: {port}")
    return port


def parse_http_port(argv: Sequence[str]) -> int | None:
    """Return the ``--http`` port, or None for the default stdio transport.

    Invalid arguments exit with code 2 and a usage message on stderr.
    """
    parser = argparse.ArgumentParser(
        prog="python -m app.mcp.filings_server",
        description="Serve the DocReview filing tools over MCP (stdio by default).",
    )
    parser.add_argument(
        "--http",
        type=_port,
        metavar="PORT",
        help=f"serve Streamable HTTP at http://{HTTP_HOST}:PORT/mcp instead of stdio",
    )
    return parser.parse_args(argv).http


async def main(http_port: int | None = None) -> None:
    """Use the product database configuration and release its pool on shutdown.

    The server is a development tool run with the developer's own key, so it
    refuses ``MODE=prod`` before touching the database or a provider credential.
    ``http_port`` selects Streamable HTTP on loopback; None keeps stdio.
    """
    if get_settings().environment == "prod":
        # stdout carries the MCP protocol; the refusal goes to stderr only.
        print("The MCP filings server is a development tool; refusing MODE=prod.", file=sys.stderr)
        raise SystemExit(2)
    from app.db.session import engine

    try:
        registry = build_default_registry(default_session_factory)
        if http_port is None:
            await serve(registry)
        else:
            await serve_http(registry, port=http_port)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(parse_http_port(sys.argv[1:])))
