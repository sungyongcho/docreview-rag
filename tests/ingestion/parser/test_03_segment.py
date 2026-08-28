from types import ModuleType

from tests.ingestion.parser.support import (
    NUMBERED_ITEMS,
    build_blocks,
    build_numbered_body,
)


def test_detect_number_returns_empty_without_item_heading_candidates(
    parser_module: ModuleType,
) -> None:
    """Reject the numbered-heading strategy when no Item headings exist.

    An xref filing can contain Item labels inside its mapping table without using Item
    headings in the narrative body. Treating ordinary text as headings would prevent
    the required xref fallback.
    """
    _soup, blocks = build_blocks(
        parser_module,
        "<p>Fundamentals of Our Business</p><p>Risk Factors</p><p>Our Capital</p>",
    )

    assert parser_module.detect_number(blocks) == {}


def test_detect_number_learns_the_loosest_observed_heading_rule(
    parser_module: ModuleType,
) -> None:
    """Learn a numbered-heading rule from enough styled Item candidates.

    The rule uses the minimum observed weight and size so it retains every valid
    heading instead of dropping the least emphasized one.
    """
    _soup, blocks = build_blocks(parser_module, build_numbered_body())

    strategy = parser_module.detect_number(blocks)

    assert strategy == {
        "type": "number",
        "rules": [{"font_weight": 700, "font_size": 10.0, "in_table": False}],
    }


def test_number_segmentation_supports_semantic_and_class_based_bold(
    parser_module: ModuleType,
) -> None:
    """Detect headings expressed by HTML semantics or a simple internal CSS class."""
    soup, blocks = build_blocks(
        parser_module,
        """
        <style>.item-heading { font-weight: 700; }</style>
        <p><strong>Item 1. Business</strong></p>
        <h2>Item 1A. Risk Factors</h2>
        <p class="item-heading">Item 7. Management Discussion</p>
        <p><b>Item 8. Financial Statements</b></p>
        <h3>Item 9. Accountant Changes</h3>
        """,
    )

    strategy = parser_module.detect_number(blocks)
    sections = parser_module.segment_by_heading(blocks, strategy)

    assert soup.find("style") is None
    assert strategy["type"] == "number"
    assert [section.item for section in sections] == ["1", "1A", "7", "8", "9"]


def test_heading_length_limit_is_inclusive_during_detection_and_segmentation(
    parser_module: ModuleType,
) -> None:
    """Treat an exactly 300-character heading consistently in both phases."""
    items = ["1", "1A", "7", "8", "9"]
    headings = []
    for item in items:
        prefix = f"Item {item}. "
        text = prefix + "X" * (parser_module.HEADING_MAX_CHARS - len(prefix))
        headings.append(f'<p style="font-weight:700">{text}</p>')

    _soup, blocks = build_blocks(parser_module, "".join(headings))
    strategy = parser_module.detect_number(blocks)
    sections = parser_module.segment_by_heading(blocks, strategy)

    assert strategy["type"] == "number"
    assert [section.item for section in sections] == items


def test_toc_detector_fires_for_densely_clustered_item_candidates(
    parser_module: ModuleType,
) -> None:
    """Detect a dense Item index instead of mistaking it for narrative headings.

    TOC entries have little body content between them, so their candidate positions
    occupy only a small fraction of the complete document.
    """
    body = build_numbered_body() + "<p>Following body text</p>" * 200
    _soup, blocks = build_blocks(parser_module, body)

    assert parser_module._looks_like_toc(blocks) is True


def test_toc_detector_ignores_item_headings_distributed_through_the_body(
    parser_module: ModuleType,
) -> None:
    """Do not classify real headings as a TOC when body blocks separate them.

    A change from False to True would indicate that block extraction or the density
    threshold no longer distinguishes document structure correctly.
    """
    _soup, blocks = build_blocks(parser_module, build_numbered_body(gap=20))

    assert parser_module._looks_like_toc(blocks) is False


def test_find_item_requires_both_item_syntax_and_heading_style(
    parser_module: ModuleType,
) -> None:
    """Accept a styled Item heading while rejecting an inline cross-reference.

    Item text alone is insufficient because the same Item number can appear repeatedly
    in narrative sentences and in the table of contents.
    """
    _soup, blocks = build_blocks(
        parser_module,
        """
        <p style="font-weight: 700; font-size: 10pt">Item 1A. Risk Factors</p>
        <p style="font-weight: 700; font-size: 10pt">See Item 1A for more information.</p>
        <p>Item 7. Management Discussion</p>
        """,
    )
    strategy = {
        "type": "number",
        "rules": [{"font_weight": 700, "font_size": 10.0, "in_table": False}],
    }

    assert parser_module.find_item(blocks[0], blocks[0].get_text(" ", strip=True), strategy) == "1A"
    assert parser_module.find_item(blocks[1], blocks[1].get_text(" ", strip=True), strategy) is None
    assert parser_module.find_item(blocks[2], blocks[2].get_text(" ", strip=True), strategy) is None


def test_segment_by_heading_drops_cover_and_toc_blocks_before_the_first_heading(
    parser_module: ModuleType,
) -> None:
    """Discard cover and TOC content that precedes the first verified Item heading.

    Assigning that material to Item 1 would create false coverage and contaminate the
    first section with text that belongs to no SEC Item.
    """
    soup, blocks = build_blocks(
        parser_module,
        """
        <p>Cover page</p>
        <p>Item 1. Business</p>
        <p style="font-weight: 700; font-size: 10pt">Item 1. Business</p>
        <p>Business body</p>
        <p style="font-weight: 700; font-size: 10pt">Item 1A. Risk Factors</p>
        <p>Risk body</p>
        """,
    )
    strategy = {
        "type": "number",
        "rules": [{"font_weight": 700, "font_size": 10.0, "in_table": False}],
    }

    sections = parser_module.segment_by_heading(blocks, strategy)

    assert [section.item for section in sections] == ["1", "1A"]
    assert sections[0].block_index == 2
    assert [block.text for block in sections[0].blocks] == ["Business body"]
    emitted = " ".join(block.text for section in sections for block in section.blocks)
    assert "Cover page" not in emitted
    assert soup.get_text(" ", strip=True).startswith("Cover page")


def test_segment_classifies_empty_and_incorporated_sections(parser_module: ModuleType) -> None:
    """Classify valid short disclosures instead of reporting them as parser failures.

    Empty disclosures and proxy references are meaningful filing states even though
    they contain too little body text for a normal parsed section.
    """
    soup, blocks = build_blocks(
        parser_module,
        """
        <p style="font-weight: 700; font-size: 10pt">Item 10. Directors</p>
        <p>Information required by this Item is incorporated by reference from the proxy.</p>
        <p style="font-weight: 700; font-size: 10pt">Item 16. Form 10-K Summary</p>
        <p>Not applicable.</p>
        """,
    )
    strategy = {
        "type": "number",
        "rules": [{"font_weight": 700, "font_size": 10.0, "in_table": False}],
    }

    sections, index = parser_module.segment(soup, blocks, strategy)
    by_item = {section.item: section for section in sections}

    assert index == []
    assert by_item["10"].status == "incorporated_by_reference"
    assert by_item["16"].status == "empty_disclosure"


def test_build_profile_records_detected_rules_and_item_count(parser_module: ModuleType) -> None:
    """Store the learned segmentation rule and observed Item count in the profile.

    A numbered profile must describe the exact rule used for section construction so a
    later filing can reproduce the same deterministic decision.
    """
    soup, blocks = build_blocks(parser_module, build_numbered_body(gap=1))

    profile = parser_module.build_profile(soup, blocks, "TEST-FY2024")

    assert profile["segmentation"] == {
        "type": "number",
        "rules": [{"font_weight": 700, "font_size": 10.0, "in_table": False}],
    }
    assert profile["validation"] == {
        "expected_items": len(NUMBERED_ITEMS),
        "must_have": ["1", "1A", "7", "8"],
    }
    assert profile["learned_from"] == "TEST-FY2024"
    assert profile["learned_by"] == "bootstrap"
