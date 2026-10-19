"""Section 3.1–3.2: list the registered catalog directly and through a real client."""

import asyncio
import json

from mcp import Client
import pytest

from app.mcp.catalog_server import read_corpus_catalog
from tests.mcp.support import PROTOCOL_MODE, module_server, write_catalog


def test_catalog_is_ordered_by_document_id(tmp_path):
    """Return every registered filing sorted, without artifacts or selections."""
    expected = write_catalog(tmp_path, 3)
    documents = read_corpus_catalog(tmp_path / "manifest.json")
    assert [document["document_id"] for document in documents] == expected
    assert {"issuer", "fiscal_year", "form", "source_url"} <= set(documents[0])


def test_missing_catalog_is_an_error_not_an_empty_list(tmp_path):
    """A missing manifest must not look like a corpus with no filings."""
    with pytest.raises(OSError):
        read_corpus_catalog(tmp_path / "manifest.json")


def test_duplicate_documents_are_rejected_by_the_catalog_contract(tmp_path):
    """The shared manifest contract rejects a repeated document identity."""
    write_catalog(tmp_path, 1)
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["documents"].append(manifest["documents"][0])
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        read_corpus_catalog(path)


def test_real_client_discovers_and_calls_list_corpus(tmp_path):
    """A stdio client sees the derived schema and receives structured documents."""
    expected = write_catalog(tmp_path, 2)

    async def exercise():
        server = module_server("app.mcp.catalog_server", env={"CORPUS_DIR": str(tmp_path)})
        async with Client(server, mode=PROTOCOL_MODE) as client:
            listing = await client.list_tools()
            result = await client.call_tool("list_corpus", {})
        return listing, result

    listing, result = asyncio.run(exercise())
    (tool,) = listing.tools
    assert tool.name == "list_corpus"
    assert tool.input_schema["properties"] == {}
    assert not result.is_error
    assert [item["document_id"] for item in result.structured_content["result"]] == expected
