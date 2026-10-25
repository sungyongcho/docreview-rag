"""Builders shared by the MCP tests: real stdio subprocesses and small catalogs."""

import json
import os
from pathlib import Path
import sys

from mcp import StdioServerParameters
from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_MODE = "2026-07-28"


def module_server(module: str, *args: str, env: dict[str, str] | None = None):
    """Launch ``python -m module`` from the repository root as a stdio server."""
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", module, *args],
        env={**os.environ, **(env or {})},
        cwd=REPO_ROOT,
    )


def write_catalog(directory: Path, document_count: int) -> list[str]:
    """Write a valid manifest with the first repository documents in reverse order."""
    source = json.loads((REPO_ROOT / "data/corpus/manifest.json").read_text(encoding="utf-8"))
    documents = source["documents"][:document_count][::-1]
    manifest = {"corpus": source["corpus"], "documents": documents}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return sorted(document["document_id"] for document in documents)


def text_of(result) -> str:
    """Join the text blocks of one tool result."""
    return "".join(item.text for item in result.content if item.type == "text")


def controlled_filings(log_path: Path, *args: str):
    """Launch the filings server with controlled retrieval logging to ``log_path``."""
    log_path.touch()
    return module_server("tests.mcp.controlled_filings", str(log_path), *args)


def logged_events(log_path: Path, start: int = 0) -> list[dict]:
    """Read data-layer events recorded after line ``start``."""
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[start:]]


async def call_or_error(client, name: str, arguments: dict):
    """Call one tool; return ``(result, None)``, or ``(None, error)`` for a JSON-RPC error.

    A system failure arrives as a JSON-RPC error that the client raises as
    :class:`~mcp.shared.exceptions.MCPError`; every other outcome is a tool result.
    """
    try:
        return await client.call_tool(name, arguments), None
    except MCPError as error:
        return None, error


def assert_internal_error(error, tool: str) -> None:
    """Require the redacted INTERNAL_ERROR a system failure of ``tool`` reports."""
    assert isinstance(error, MCPError)
    assert error.code == INTERNAL_ERROR
    assert error.message == f"RuntimeError: tool {tool} failed"
    assert error.data is None
