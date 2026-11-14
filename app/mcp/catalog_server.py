"""Expose the registered filing catalog as one MCP tool over stdio."""

from pathlib import Path
from typing import Any

from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.server import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, CallToolResult, InputRequiredResult

from app.config import get_settings
from app.ingestion.sources.models import Manifest


class CatalogServer(MCPServer):
    """High-level server that reports an unknown tool as a protocol error.

    ``MCPServer`` turns a call to an unregistered tool into an ``isError`` result.
    The MCP tools specification makes an unknown tool a JSON-RPC error instead, so
    :meth:`call_tool` raises ``INVALID_PARAMS``, which the SDK's call handler passes
    through as the request's error. Registered tools keep the SDK's own behavior:
    invalid arguments and tool failures stay ``isError`` results.
    """

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[Any, Any] | None = None
    ) -> CallToolResult | InputRequiredResult:
        """Call a registered tool, or raise ``INVALID_PARAMS`` for any other name."""
        if name not in {tool.name for tool in await self.list_tools()}:
            raise MCPError(code=INVALID_PARAMS, message=f"unknown tool: {name}")
        return await super().call_tool(name, arguments, context)


def read_corpus_catalog(manifest_path: Path) -> list[dict[str, Any]]:
    """Return registered filings ordered by document ID from one canonical manifest.

    Parameters
    ----------
    manifest_path : Path
        Canonical ``manifest.json`` of the corpus.

    Returns
    -------
    list[dict[str, Any]]
        JSON-ready document metadata, without artifacts or processing selections.

    Raises
    ------
    OSError
        When the manifest cannot be read; a missing catalog is not an empty one.
    ValueError
        When the manifest violates the shared catalog contract.
    """
    manifest = Manifest.read(manifest_path)
    documents = sorted(manifest.documents, key=lambda document: document.document_id)
    return [document.model_dump(mode="json") for document in documents]


def list_corpus() -> list[dict[str, Any]]:
    """Return registered filings ordered by document ID, without DB or model calls.

    This lists metadata; it does not certify local originals or search readiness.
    Missing files and invalid metadata raise errors rather than returning no filings.
    """
    return read_corpus_catalog(get_settings().corpus_dir / "manifest.json")


def build_server() -> MCPServer:
    """Register the catalog tool on a high-level server that derives its schemas."""
    server = CatalogServer("DocReview catalog")
    server.add_tool(list_corpus)
    return server


if __name__ == "__main__":
    build_server().run(transport="stdio")
