"""Publishing registries resolve only explicitly typed filing sources."""

import pytest

from app.ingestion.dart import parse_dart_filing
from app.ingestion.edgar import parse_filing
from app.ingestion.registry import REGISTRIES, registry_for, resolve_registry
from tests.ingestion.support import filing_document, filing_source


def test_explicit_source_selects_the_registered_parser(tmp_path):
    """Both registries dispatch from shared document metadata."""
    path = tmp_path / "source.html"
    path.write_text("<html>source</html>")
    for name, parser in [("sec", parse_filing), ("dart", parse_dart_filing)]:
        source = filing_source(path, document=filing_document(registry=name))
        assert resolve_registry(source).parse is parser
        assert resolve_registry(source).name == name


def test_missing_registry_never_defaults_to_sec():
    """Reject a legacy dictionary instead of implicitly treating it as SEC."""
    with pytest.raises(AttributeError):
        resolve_registry({})


def test_unknown_registry_fails_closed():
    """Report an unknown registry without guessing an adapter."""
    with pytest.raises(ValueError, match="unknown registry"):
        registry_for("unknown")


def test_registry_configuration_is_immutable_and_has_no_chunk_profiles():
    """Keep source syntax in adapters and processing budgets in the shared contract."""
    with pytest.raises(TypeError):
        REGISTRIES["other"] = REGISTRIES["sec"]
    assert registry_for("dart").language == "ko"
    assert registry_for("sec").language == "en"
    assert registry_for("sec").section_label("7") == "Item 7"
    assert "회사" in registry_for("dart").section_label("I")
    assert not hasattr(registry_for("sec"), "chunk_target")
