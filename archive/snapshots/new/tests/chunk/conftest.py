"""Fixtures for the M1.3 chunking harness.

The chunk implementation is replaceable through `CHUNK_MODULE`, while the parser
remains the fixed input producer. Missing chunk-layer symbols skip instead of fail,
turning pytest output into a progress board.
"""

import importlib
import json
import os
from pathlib import Path

import pytest

from app.ingestion import parser as parser_module

CHUNK_MODULE_NAME = os.getenv("CHUNK_MODULE", "app.ingestion.chunk")


@pytest.fixture(scope="session")
def C():
    """Chunk module selected by `CHUNK_MODULE`."""
    return importlib.import_module(CHUNK_MODULE_NAME)


@pytest.fixture(scope="session")
def manifest() -> list[dict]:
    return json.loads(Path("data/corpus/manifest.json").read_text())


@pytest.fixture(scope="session")
def corpus(manifest, tmp_path_factory) -> dict[str, tuple]:
    """`doc_id -> (ParsedFiling, raw_html)` parsed once with isolated profiles."""
    profiles = tmp_path_factory.mktemp("chunk_profiles")
    original = parser_module.PROFILES
    parser_module.PROFILES = profiles
    try:
        out = {}
        for entry in sorted(manifest, key=lambda item: (item["ticker"], item["report_date"])):
            filing, _ = parser_module.parse_filing(entry)
            out[filing.doc_id] = (filing, parser_module.read_source(entry["file"]))
        return out
    finally:
        parser_module.PROFILES = original


@pytest.fixture(scope="session")
def chunker(C):
    if not hasattr(C, "chunk_filing"):
        pytest.skip("not implemented yet: chunk_filing")
    return C.chunk_filing


@pytest.fixture(scope="session")
def chunks_by_doc(chunker, corpus) -> dict[str, list]:
    return {doc_id: chunker(filing) for doc_id, (filing, _raw) in corpus.items()}
