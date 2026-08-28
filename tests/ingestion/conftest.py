"""Fixtures for parser-only ingestion unit tests."""

from importlib import import_module
import json
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from app.ingestion.parser import doc_id

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def parser_module() -> ModuleType:
    """Import the parser module from the repository source tree."""
    return import_module("app.ingestion.parser")


@pytest.fixture(scope="session")
def xref_module() -> ModuleType:
    """Import the xref module from the repository source tree."""
    return import_module("app.ingestion.xref")


@pytest.fixture(scope="session")
def manifest() -> list[dict]:
    """Load the corpus manifest when corpus regression tests are available."""
    path = _REPOSITORY_ROOT / "data/corpus/manifest.json"
    if not path.exists():
        pytest.skip("data/corpus/manifest.json is required for corpus regression tests")
    return json.loads(path.read_text())


@pytest.fixture(scope="session")
def blocks_by_doc(parser_module: ModuleType, manifest: list[dict]) -> dict[str, tuple]:
    """Parse each corpus file into reusable soup, block, and raw-source values."""
    out = {}
    for entry in manifest:
        path = _REPOSITORY_ROOT / entry["file"]
        if not path.exists():
            pytest.skip(f"corpus file is missing: {entry['file']}")
        raw = parser_module.read_source(path)
        soup = parser_module.normalize(raw)
        out[doc_id(entry)] = (soup, parser_module.leaf_blocks(soup), raw)
    return out


@pytest.fixture(scope="session")
def profiles_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide an isolated profile directory shared by corpus parsing tests."""
    return tmp_path_factory.mktemp("profiles")


@pytest.fixture
def isolated_profiles(parser_module: ModuleType, tmp_path: Path):
    """Redirect profile I/O to a temporary directory for one test."""
    with patch.object(parser_module, "PROFILES", tmp_path):
        yield tmp_path


@pytest.fixture(scope="session")
def parsed(
    parser_module: ModuleType,
    manifest: list[dict],
    profiles_dir: Path,
) -> dict:
    """Parse every corpus document while learning profiles from a clean directory."""
    with patch.object(parser_module, "PROFILES", profiles_dir):
        out = {}
        for entry in sorted(manifest, key=lambda item: (item["ticker"], item["report_date"])):
            result, _profile = parser_module.parse_filing(entry)
            out[doc_id(entry)] = result
        return out
