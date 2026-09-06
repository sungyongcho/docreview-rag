"""Parsing every committed filing end to end."""

import json
from types import ModuleType

import pytest

from tests.ingestion.golden import (
    ALWAYS_OPTIONAL,
    BLOCKS,
    COVERAGE,
    N_ITEMS,
    NVDA_FY2024_ITEM15_MIN_CHARS,
    NVDA_FY2024_OFFSETS,
    PROFILE_RULES,
    SEGMENT_TYPE,
    STATUS_NVDA_FY2024,
    measured,
)

# Block extraction regression


def test_corpus_block_counts_match_golden(blocks_by_doc: dict[str, tuple]) -> None:
    """Keep leaf-block and table counts stable for every measured corpus document."""
    actual = {
        doc: (
            len(blocks),
            sum(block.name == "table" for block in blocks),
            len(soup.find_all("table")),
        )
        for doc, (soup, blocks, _raw) in blocks_by_doc.items()
    }

    assert measured(actual, BLOCKS) == BLOCKS


# Segmentation and learned-rule regression


def test_corpus_segmentation_types_match_golden(parsed: dict) -> None:
    """Keep the expected numbered or xref strategy for every measured document."""
    actual = {doc: result.segment_type for doc, result in parsed.items()}
    assert measured(actual, SEGMENT_TYPE) == SEGMENT_TYPE


def test_every_measured_document_parses_without_warnings(parsed: dict) -> None:
    """Require the measured filings to finish with parsed status and no warning."""
    failed = {
        doc: result.warnings
        for doc, result in parsed.items()
        if doc in SEGMENT_TYPE and result.parse_status != "parsed"
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


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_corpus_has_no_duplicate_items(doc: str, parsed: dict) -> None:
    """Reject a loose heading rule that emits the same SEC Item more than once."""
    items = [section.item for section in parsed[doc].sections if section.item]
    duplicates = sorted(item for item in items if items.count(item) > 1)
    assert len(items) == len(set(items)), f"{doc}: duplicate Items {duplicates}"


def test_learned_corpus_rules_match_golden(
    parsed: dict,
    profiles_dir,
) -> None:
    """Preserve measured heading styles learned during clean profile bootstrapping."""
    for ticker, years in PROFILE_RULES.items():
        data = json.loads((profiles_dir / f"{ticker}.json").read_text())
        for year, expected in years.items():
            rule = data["profiles"][year]["segmentation"]["rules"][0]
            actual = (rule["font_weight"], rule["font_size"], rule["in_table"])
            assert actual == expected, f"{ticker}-{year}: learned rule mismatch"


def test_nvda_fy2024_headings_match_style_and_item_syntax(
    edgar_module: ModuleType,
    blocks_by_doc: dict[str, tuple],
) -> None:
    """Keep exactly 23 styled Item headings in NVDA-FY2024."""
    _soup, blocks, _raw = blocks_by_doc["NVDA-FY2024"]
    rules = [{"font_weight": 700, "font_size": 10.0, "in_table": False}]
    hits = [
        text
        for block in blocks
        if (text := block.get_text(" ", strip=True))
        and len(text) < edgar_module.HEADING_MAX_CHARS
        and edgar_module.ITEM_RE.match(text)
        and edgar_module.matches_any(block, rules)
    ]

    assert len(hits) == 23
    assert hits[0].startswith("Item 1.")
    assert hits[1].startswith("Item 1A.")


def test_corpus_cover_and_toc_are_dropped_before_item1(parsed: dict) -> None:
    """Keep cover and TOC material out of the first NVDA-FY2024 section."""
    first = parsed["NVDA-FY2024"].sections[0]
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
    section = next(section for section in parsed["NVDA-FY2024"].sections if section.item == item)
    assert section.status == expected


def test_nvda_fy2024_item15_contains_the_financial_statement_body(parsed: dict) -> None:
    """Require Item 15 to contain the body and tables omitted from referenced Item 8."""
    section = next(section for section in parsed["NVDA-FY2024"].sections if section.item == "15")

    assert sum(len(block.text) for block in section.blocks) > NVDA_FY2024_ITEM15_MIN_CHARS
    assert sum(block.kind == "table" for block in section.blocks) > 30


# Coverage regression


def _measure(edgar_module: ModuleType, result) -> tuple[int, int]:
    """Measure source characters assigned to section text and table text."""
    body = sum(len(block.text) for section in result.sections for block in section.blocks)
    tables = sum(
        len(edgar_module.BeautifulSoup(block.html, "html.parser").get_text(" ", strip=True))
        for section in result.sections
        for block in section.blocks
        if block.kind == "table" and block.html
    )
    return result.n_chars, body + tables


@pytest.mark.parametrize("doc", sorted(COVERAGE))
def test_document_coverage_matches_golden(
    doc: str,
    edgar_module: ModuleType,
    parsed: dict,
) -> None:
    """Keep exact total and section-assigned character counts for every filing."""
    assert _measure(edgar_module, parsed[doc]) == COVERAGE[doc]


def test_parsed_result_carries_the_original_measurements(
    parsed: dict,
    blocks_by_doc: dict[str, tuple],
) -> None:
    """Keep n_chars and n_blocks tied to the blocks measured during parsing."""
    for doc, result in parsed.items():
        _soup, blocks, _raw = blocks_by_doc[doc]
        assert result.n_chars == sum(len(block.get_text(" ", strip=True)) for block in blocks)
        assert result.n_blocks == len(blocks)


# SEC Item boundaries and source-position regression


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_no_extra_sec_items(doc: str, edgar_module: ModuleType, parsed: dict) -> None:
    """Reject every parsed Item that is absent from the SEC Item order."""
    items = [section.item for section in parsed[doc].sections if section.item]
    assert [item for item in items if item not in edgar_module.ORDER] == []


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
    year = int(doc.split("FY")[1])
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


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_every_section_has_canonical_sec_metadata(
    doc: str,
    edgar_module: ModuleType,
    parsed: dict,
) -> None:
    """Populate canonical title and Part metadata for every segmentation strategy."""
    for section in parsed[doc].sections:
        if section.item:
            assert section.canonical_title == edgar_module.CANONICAL[section.item]
            assert section.part == edgar_module.PART_OF[section.item]


def test_heading_based_items_stay_in_sec_order(
    edgar_module: ModuleType,
    parsed: dict,
) -> None:
    """Require SEC ordering for numbered headings but not scattered xref sections."""
    rank = {item: index for index, item in enumerate(edgar_module.ORDER)}
    for doc, result in parsed.items():
        if result.segment_type != "number":
            continue
        items = [section.item for section in result.sections if section.item]
        assert items == sorted(items, key=lambda item: rank[item]), f"{doc}: Item order mismatch"


def test_nvda_fy2024_heading_offsets_match_the_source(
    parsed: dict,
) -> None:
    """Prove selected Item heading elements against exact source positions."""
    raw = parsed["NVDA-FY2024"].source.read()
    by_item = {section.item: section for section in parsed["NVDA-FY2024"].sections}

    for item, (expected_offset, expected_text) in NVDA_FY2024_OFFSETS.items():
        assert by_item[item].source_pos == expected_offset
        assert expected_text in raw[expected_offset : expected_offset + 500]
