"""Registry resolution for corpus manifest entries."""

import pytest

from app.ingestion.parser import doc_id, parse_filing
from app.ingestion.registry import (
    DEFAULT_REGISTRY,
    REGISTRIES,
    registry_name,
    resolve_registry,
)

EDGAR_ENTRY = {"ticker": "NVDA", "report_date": "2024-01-28", "file": "x.html"}


def test_an_entry_without_a_registry_key_is_read_as_edgar():
    """Read the committed manifest, which predates the registry key, as EDGAR."""
    registry = resolve_registry(EDGAR_ENTRY)

    assert registry_name(EDGAR_ENTRY) == DEFAULT_REGISTRY
    assert registry.name == "sec"
    assert registry.language == "en"


def test_the_edgar_adapter_exposes_the_readers_the_parser_already_defines():
    """Reference the EDGAR readers rather than restating them."""
    registry = resolve_registry(EDGAR_ENTRY)

    assert registry.doc_id is doc_id
    assert registry.parse is parse_filing
    assert registry.doc_id(EDGAR_ENTRY) == "NVDA-FY2024"


def test_an_explicit_registry_name_selects_that_adapter():
    """Select the adapter an entry names instead of the default."""
    entry = {**EDGAR_ENTRY, "registry": "sec"}

    assert resolve_registry(entry) is REGISTRIES["sec"]


def test_an_unknown_registry_fails_closed_and_names_what_is_known():
    """Refuse an unreadable entry rather than parsing it with another registry's rules."""
    with pytest.raises(ValueError, match="unknown registry 'dart'; known registries: sec"):
        resolve_registry({**EDGAR_ENTRY, "registry": "dart"})


def test_edgar_entries_order_by_issuer_then_report_date():
    """Order EDGAR entries by the keys EDGAR writes, with missing keys sorting first."""
    registry = resolve_registry(EDGAR_ENTRY)
    entries = [
        {"ticker": "NVDA", "report_date": "2020-02-20"},
        {"ticker": "AMD", "report_date": "2024-01-31"},
        {"ticker": "NVDA", "report_date": "2024-02-21"},
        {},
    ]

    ordered = sorted(entries, key=registry.sort_key)

    assert [(entry.get("ticker"), entry.get("report_date")) for entry in ordered] == [
        (None, None),
        ("AMD", "2024-01-31"),
        ("NVDA", "2020-02-20"),
        ("NVDA", "2024-02-21"),
    ]


def test_the_registry_table_cannot_be_extended_at_runtime():
    """Keep the readable registries a fixed build-time fact."""
    with pytest.raises(TypeError):
        REGISTRIES["dart"] = REGISTRIES["sec"]  # type: ignore[index]
