"""Expose the registered filing catalog as one MCP tool over stdio."""

from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from app.config import get_settings
from app.ingestion.sources.models import Manifest


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
    server = MCPServer("DocReview catalog")
    server.add_tool(list_corpus)
    return server


if __name__ == "__main__":
    build_server().run(transport="stdio")
