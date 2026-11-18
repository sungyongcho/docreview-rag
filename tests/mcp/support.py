"""Catalog builders and protocol assertions shared by the MCP server tests.

The servers these tests connect to come from :mod:`tests.support.transport`.
"""

import json
from pathlib import Path

from mcp.shared.exceptions import MCPError
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS

from tests.support import REPO_ROOT

# Names no DocReview MCP server publishes: an arbitrary name and the loop-owned answer tool.
UNKNOWN_TOOLS = ("search_everything", "final_answer")


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


def assert_unknown_tool(outcome: tuple, name: str) -> None:
    """Require INVALID_PARAMS for ``name``, not a tool result, from :func:`call_or_error`."""
    result, error = outcome
    assert result is None
    assert isinstance(error, MCPError)
    assert error.code == INVALID_PARAMS
    assert name in error.message
