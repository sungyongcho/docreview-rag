"""Chunk fixtures that reuse the shared parsed corpus."""

import importlib
import os
from types import ModuleType

import pytest

CHUNK_MODULE_NAME = os.getenv("CHUNK_MODULE", "app.ingestion.chunk")


class ChunkModuleProxy:
    """Expose implemented chunk symbols and skip tests for missing ones."""

    def __init__(self, module: ModuleType) -> None:
        self._module = module

    def __getattr__(self, name: str):
        try:
            return getattr(self._module, name)
        except AttributeError:
            pytest.skip(f"not implemented yet: {name}")


@pytest.fixture(scope="session")
def C():
    """Chunk module selected by `CHUNK_MODULE`."""
    return ChunkModuleProxy(importlib.import_module(CHUNK_MODULE_NAME))


@pytest.fixture(scope="session")
def chunker(C):
    """Return chunk_filing or skip when that study-stage symbol is absent."""
    return C.chunk_filing


@pytest.fixture(scope="session")
def chunks_by_doc(chunker, corpus) -> dict[str, list]:
    """Chunk every parsed corpus filing once for package-wide checks."""
    return {doc_id: chunker(filing) for doc_id, (filing, _raw) in corpus.items()}
