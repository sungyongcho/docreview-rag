"""Parsing every committed filing end to end."""

from types import ModuleType

import pytest

from tests.ingestion.golden import (
    ALWAYS_OPTIONAL,
    COVERAGE,
    N_ITEMS,
    NVDA_FY2024_ITEM15_MIN_CHARS,
    NVDA_FY2024_OFFSETS,
    STATUS_NVDA_FY2024,
    measured,
)

# Segmentation and learned-rule regression


def test_every_measured_document_parses_without_warnings(parsed: dict) -> None:
    """Require the measured filings to finish with parsed status and no warning."""
    failed = {
        doc: result.warnings
        for doc, result in parsed.items()
        if doc in N_ITEMS and result.parse_status != "parsed"
    }
    assert failed == {}


def test_every_document_in_the_corpus_yields_sections(parsed: dict) -> None:
    """Require every corpus filing, including widened additions, to yield sections."""
    assert [doc for doc, result in parsed.items() if not result.sections] == []


def test_no_document_invents_an_item_outside_the_sec_vocabulary(
    parsed: dict, edgar_module: ModuleType
) -> None:
    """The Item vocabulary is the parser's contract, so it holds for the whole corpus."""
    for doc, result in parsed.items():
        items = [section.item for section in result.sections if section.item]
        assert [item for item in items if item not in edgar_module.ORDER] == [], doc


def test_corpus_item_counts_match_golden(parsed: dict) -> None:
    """Preserve the expected Item count for every measured filing year."""
    actual = {
        doc: len([section for section in result.sections if section.item])
        for doc, result in parsed.items()
    }
    assert measured(actual, N_ITEMS) == N_ITEMS


def test_corpus_cover_and_toc_are_dropped_before_item1(parsed: dict) -> None:
    """Keep cover and TOC material out of the first NVDA-FY2024 section."""
    first = parsed["sec-0001045810-24-000029"].sections[0]
    body = " ".join(block.text for block in first.blocks[:3])

    assert first.item == "1"
    assert first.block_index is not None and first.block_index > 0
    assert "Securities registered pursuant" not in body


# Section-status regression


@pytest.mark.parametrize("item, expected", sorted(STATUS_NVDA_FY2024.items()))
def test_nvda_fy2024_section_statuses_match_golden(
    item: str,
    expected: str,
    parsed: dict,
) -> None:
    """Preserve every expected non-parsed section status in NVDA-FY2024."""
    section = next(
        section for section in parsed["sec-0001045810-24-000029"].sections if section.item == item
    )
    assert section.status == expected


def test_nvda_fy2024_item15_contains_the_financial_statement_body(parsed: dict) -> None:
    """Require Item 15 to contain the body and tables omitted from referenced Item 8."""
    section = next(
        section for section in parsed["sec-0001045810-24-000029"].sections if section.item == "15"
    )

    assert sum(len(block.text) for block in section.blocks) > NVDA_FY2024_ITEM15_MIN_CHARS
    assert sum(block.kind == "table" for block in section.blocks) > 30


# Coverage regression


def _measure(edgar_module: ModuleType, result, blocks) -> tuple[int, int]:
    """Measure the leaf-block text total and the section-assigned text and table characters."""
    body = sum(len(block.text) for section in result.sections for block in section.blocks)
    tables = sum(
        len(edgar_module.BeautifulSoup(block.html, "html.parser").get_text(" ", strip=True))
        for section in result.sections
        for block in section.blocks
        if block.kind == "table" and block.html
    )
    total = sum(len(block.get_text(" ", strip=True)) for block in blocks)
    return total, body + tables


@pytest.mark.parametrize("doc", sorted(COVERAGE))
def test_document_coverage_matches_golden(
    doc: str,
    edgar_module: ModuleType,
    parsed: dict,
    blocks_by_doc: dict[str, tuple],
) -> None:
    """Keep exact total and section-assigned character counts for every filing."""
    assert _measure(edgar_module, parsed[doc], blocks_by_doc[doc][1]) == COVERAGE[doc]


# SEC Item boundaries and source-position regression


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_missing_items_are_only_optional_items(
    doc: str,
    edgar_module: ModuleType,
    parsed: dict,
) -> None:
    """Allow only historically unavailable or optional Items to be absent."""
    items = {section.item for section in parsed[doc].sections if section.item}
    missing = {item for item in edgar_module.ORDER if item not in items}
    assert missing <= ALWAYS_OPTIONAL, f"{doc}: unexplained missing Items {sorted(missing)}"


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_new_items_do_not_appear_before_their_effective_year(doc: str, parsed: dict) -> None:
    """Reject Items parsed in filing years before the SEC introduced them."""
    year = parsed[doc].source.document.fiscal_year
    items = {section.item for section in parsed[doc].sections if section.item}

    if year <= 2022:
        assert "1C" not in items
    if year <= 2020:
        assert "9C" not in items


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_core_items_have_real_body_content(doc: str, parsed: dict) -> None:
    """Require substantive body depth for every parsed core Item."""
    for section in parsed[doc].sections:
        if section.item in ("1", "1A", "7", "8") and section.status == "parsed":
            assert len(section.blocks) >= 20, (
                f"{doc} Item {section.item}: only {len(section.blocks)} blocks"
            )


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_sections_carry_verifiable_source_positions(doc: str, parsed: dict) -> None:
    """Keep block and source positions for every emitted parsed section."""
    for section in parsed[doc].sections:
        if section.status != "parsed" or not section.blocks:
            continue
        assert section.block_index is not None, f"{doc} Item {section.item}: no block index"
        assert section.source_pos is not None, f"{doc} Item {section.item}: no source offset"
        assert section.block_range is not None


def test_nvda_fy2024_heading_offsets_match_the_source(
    parsed: dict,
) -> None:
    """Prove selected Item heading elements against exact source positions."""
    raw = parsed["sec-0001045810-24-000029"].source.read()
    by_item = {section.item: section for section in parsed["sec-0001045810-24-000029"].sections}

    for item, (expected_offset, expected_text) in NVDA_FY2024_OFFSETS.items():
        assert by_item[item].source_pos == expected_offset
        assert expected_text in raw[expected_offset : expected_offset + 500]
