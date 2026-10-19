"""Builders shared by the MCP tests: real stdio subprocesses and small catalogs."""

import json
import os
from pathlib import Path
import sys

from mcp import StdioServerParameters

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
