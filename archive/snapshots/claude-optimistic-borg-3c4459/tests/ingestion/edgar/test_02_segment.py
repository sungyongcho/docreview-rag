"""Item-number detection, table-of-contents rejection, and heading segmentation."""

from types import ModuleType

from tests.ingestion.edgar.support import (
    NUMBERED_ITEMS,
    build_blocks,
    build_numbered_body,
)


def test_detect_number_returns_empty_without_item_heading_candidates(
    edgar_module: ModuleType,
) -> None:
    """Reject the numbered-heading strategy when no Item headings exist.

    An xref filing carries Item labels only in its mapping table, so the fallback must run.
    """
    _soup, blocks = build_blocks(
        edgar_module,
        "<p>Fundamentals of Our Business</p><p>Risk Factors</p><p>Our Capital</p>",
    )

    assert edgar_module.detect_number(blocks) == {}


def test_detect_number_learns_the_loosest_observed_heading_rule(
    edgar_module: ModuleType,
) -> None:
    """Learn a numbered-heading rule from enough styled Item candidates.

    Minimum observed weight and size retain every heading, not just the emphasized ones.
    """
    _soup, blocks = build_blocks(edgar_module, build_numbered_body())

    strategy = edgar_module.detect_number(blocks)

    assert strategy == {
        "type": "number",
        "rules": [{"font_weight": 700, "font_size": 10.0, "in_table": False}],
    }


def test_number_segmentation_supports_semantic_and_class_based_bold(
    edgar_module: ModuleType,
) -> None:
    """Detect headings expressed by HTML semantics or a simple internal CSS class."""
    soup, blocks = build_blocks(
        edgar_module,
        """
        <style>.item-heading { font-weight: 700; }</style>
        <p><strong>Item 1. Business</strong></p>
        <h2>Item 1A. Risk Factors</h2>
        <p class="item-heading">Item 7. Management Discussion</p>
        <p><b>Item 8. Financial Statements</b></p>
        <h3>Item 9. Accountant Changes</h3>
        """,
    )

    strategy = edgar_module.detect_number(blocks)
    sections = edgar_module.segment_by_heading(blocks, strategy)

    assert soup.find("style") is None
    assert strategy["type"] == "number"
    assert [section.item for section in sections] == ["1", "1A", "7", "8", "9"]


def test_heading_length_limit_is_inclusive_during_detection_and_segmentation(
    edgar_module: ModuleType,
) -> None:
    """Treat an exactly 300-character heading consistently in both phases."""
    items = ["1", "1A", "7", "8", "9"]
    headings = []
    for item in items:
        prefix = f"Item {item}. "
        text = prefix + "X" * (edgar_module.HEADING_MAX_CHARS - len(prefix))
        headings.append(f'<p style="font-weight:700">{text}</p>')

    _soup, blocks = build_blocks(edgar_module, "".join(headings))
    strategy = edgar_module.detect_number(blocks)
    sections = edgar_module.segment_by_heading(blocks, strategy)

    assert strategy["type"] == "number"
    assert [section.item for section in sections] == items


def test_toc_detector_fires_for_densely_clustered_item_candidates(
    edgar_module: ModuleType,
) -> None:
    """Detect a dense Item index instead of mistaking it for narrative headings.

    TOC entries carry little body text between them, so they occupy a small span of the document.
    """
    body = build_numbered_body() + "<p>Following body text</p>" * 200
    _soup, blocks = build_blocks(edgar_module, body)

    assert edgar_module._looks_like_toc(blocks) is True


def test_toc_detector_ignores_item_headings_distributed_through_the_body(
    edgar_module: ModuleType,
) -> None:
    """Do not classify real headings as a TOC when body blocks separate them.

    A flip here means block extraction or the density threshold stopped seeing structure.
    """
    _soup, blocks = build_blocks(edgar_module, build_numbered_body(gap=20))

    assert edgar_module._looks_like_toc(blocks) is False


def test_find_item_requires_both_item_syntax_and_heading_style(
    edgar_module: ModuleType,
) -> None:
    """Accept a styled Item heading while rejecting an inline cross-reference.

    The same Item number recurs in narrative sentences and in the table of contents.
    """
    _soup, blocks = build_blocks(
        edgar_module,
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

    assert edgar_module.find_item(blocks[0], blocks[0].get_text(" ", strip=True), strategy) == "1A"
    assert edgar_module.find_item(blocks[1], blocks[1].get_text(" ", strip=True), strategy) is None
    assert edgar_module.find_item(blocks[2], blocks[2].get_text(" ", strip=True), strategy) is None


def test_segment_by_heading_drops_cover_and_toc_blocks_before_the_first_heading(
    edgar_module: ModuleType,
) -> None:
    """Discard cover and TOC content that precedes the first verified Item heading.

    Assigning it to Item 1 would invent coverage for text that belongs to no Item.
    """
    soup, blocks = build_blocks(
        edgar_module,
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

    sections = edgar_module.segment_by_heading(blocks, strategy)

    assert [section.item for section in sections] == ["1", "1A"]
    assert sections[0].block_index == 2
    assert [block.text for block in sections[0].blocks] == ["Business body"]
    emitted = " ".join(block.text for section in sections for block in section.blocks)
    assert "Cover page" not in emitted
    assert soup.get_text(" ", strip=True).startswith("Cover page")


def test_segment_classifies_empty_and_incorporated_sections(edgar_module: ModuleType) -> None:
    """Classify valid short disclosures instead of reporting them as parser failures.

    An empty disclosure or a proxy reference is a filing state, not a parser failure.
    """
    soup, blocks = build_blocks(
        edgar_module,
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

    sections, index = edgar_module.segment(soup, blocks, strategy)
    by_item = {section.item: section for section in sections}

    assert index == []
    assert by_item["10"].status == "incorporated_by_reference"
    assert by_item["16"].status == "empty_disclosure"


def test_build_profile_records_detected_rules_and_item_count(edgar_module: ModuleType) -> None:
    """Store the learned segmentation rule and observed Item count in the profile.

    A later filing reproduces the same decision only from the exact recorded rule.
    """
    soup, blocks = build_blocks(edgar_module, build_numbered_body(gap=1))

    profile = edgar_module.build_profile(soup, blocks, "TEST-FY2024")

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
