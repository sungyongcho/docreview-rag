"""Shared ingestion fixtures for parser and downstream corpus tests."""

from importlib import import_module
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from app.ingestion.manifest import FilingSource, Manifest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def parser_module() -> ModuleType:
    """Import the neutral parser-contract module from the repository source tree."""
    return import_module("app.ingestion.parser")


@pytest.fixture(scope="session")
def edgar_module() -> ModuleType:
    """Import the EDGAR adapter module from the repository source tree."""
    return import_module("app.ingestion.edgar")


@pytest.fixture(scope="session")
def xref_module() -> ModuleType:
    """Import the xref module from the repository source tree."""
    return import_module("app.ingestion.xref")


@pytest.fixture(scope="session")
def manifest() -> tuple[FilingSource, ...]:
    """Load the corpus manifest when corpus regression tests are available."""
    path = _REPOSITORY_ROOT / "data/corpus/manifest.json"
    if not path.exists():
        pytest.skip("data/corpus/manifest.json is required for corpus regression tests")
    catalog = Manifest.read(path)
    return tuple(
        source
        for source in catalog.selected_sources("sec-regression", path.parent)
        if source.document.registry == "sec"
    )


@pytest.fixture(scope="session")
def blocks_by_doc(
    parser_module: ModuleType, manifest: tuple[FilingSource, ...]
) -> dict[str, tuple]:
    """Parse each corpus file into reusable soup, block, and raw-source values."""
    out = {}
    for entry in manifest:
        raw = entry.read()
        soup = parser_module.normalize(raw)
        out[entry.document.document_id] = (soup, parser_module.leaf_blocks(soup), raw)
    return out


@pytest.fixture(scope="session")
def profiles_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide an isolated profile directory shared by corpus parsing tests."""
    return tmp_path_factory.mktemp("profiles")


@pytest.fixture
def isolated_profiles(edgar_module: ModuleType, tmp_path: Path):
    """Redirect profile I/O to a temporary directory for one test."""
    with patch.object(edgar_module, "PROFILES", tmp_path):
        yield tmp_path


@pytest.fixture(scope="session")
def parsed(
    edgar_module: ModuleType,
    manifest: tuple[FilingSource, ...],
    profiles_dir: Path,
) -> dict:
    """Parse every corpus document while learning profiles from a clean directory."""
    with patch.object(edgar_module, "PROFILES", profiles_dir):
        out = {}
        for entry in sorted(manifest, key=lambda item: item.document.document_id):
            result, _profile = edgar_module.parse_filing(entry)
            out[entry.document.document_id] = result
        return out


@pytest.fixture(scope="session")
def corpus(manifest, parsed, parser_module) -> dict[str, tuple]:
    """Pair parsed filings with the exact canonical source text they cite."""
    entries = {entry.document.document_id: entry for entry in manifest}
    return {
        document: (
            filing,
            entries[document].read(),
        )
        for document, filing in parsed.items()
    }
