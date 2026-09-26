"""Publishing registries resolve only explicitly typed filing sources."""

from collections.abc import MutableMapping
from typing import cast

import pytest

from app.ingestion.parsing.dart import DART_PARTS, parse_dart_filing
from app.ingestion.parsing.registry import REGISTRIES, Registry, registry_for, section_title
from app.ingestion.parsing.sec import CANONICAL, parse_filing
from tests.ingestion.support import filing_document, filing_source


def test_explicit_source_selects_the_registered_parser(tmp_path):
    """Both registries dispatch from shared document metadata."""
    path = tmp_path / "source.html"
    path.write_text("<html>source</html>")
    for name, parser in [("sec", parse_filing), ("dart", parse_dart_filing)]:
        source = filing_source(path, document=filing_document(registry=name))
        assert registry_for(source.document.registry).parse is parser
        assert registry_for(source.document.registry).name == name


def test_unknown_registry_fails_closed():
    """Report an unknown registry without guessing an adapter."""
    with pytest.raises(ValueError, match="unknown registry"):
        registry_for("unknown")


def test_registry_configuration_is_immutable_and_keeps_registry_labels():
    """Keep source syntax in adapters and processing budgets in the shared contract."""
    with pytest.raises(TypeError):
        # Write through a mutable view on purpose: the read-only proxy must refuse it.
        cast(MutableMapping[str, Registry], REGISTRIES)["other"] = REGISTRIES["sec"]
    assert registry_for("dart").language == "ko"
    assert registry_for("sec").language == "en"
    assert registry_for("sec").section_label("7") == "Item 7"
    assert "회사" in registry_for("dart").section_label("I")
    assert registry_for("sec").section_title("7") == "Management's Discussion and Analysis"
    assert registry_for("dart").section_title("II") == "사업의 내용"


def test_section_title_uses_only_the_named_registry():
    """A known registry answers for its own codes and stays silent about foreign ones."""
    market_risk = "Quantitative and Qualitative Disclosures About Market Risk"
    assert section_title("7A", "sec") == market_risk
    assert section_title("II", "dart") == "사업의 내용"
    assert section_title("II", "sec") is None
    assert section_title("7", "dart") is None


def test_section_title_falls_back_across_registries_without_a_name():
    """Registry-less hits still resolve because the two code spaces never collide."""
    assert section_title("7") == "Management's Discussion and Analysis"
    assert section_title("III") == "재무에 관한 사항"
    assert section_title("III", "unknown") == "재무에 관한 사항"
    assert section_title("99") is None
    assert section_title(None) is None
    assert section_title("") is None


def test_registry_less_lookup_gives_every_code_its_own_registry_title():
    """The fallback takes the first registry that knows a code, so no code may know two."""
    for registry, codes in (("sec", CANONICAL), ("dart", DART_PARTS)):
        for code in codes:
            assert section_title(code) == section_title(code, registry), (registry, code)
