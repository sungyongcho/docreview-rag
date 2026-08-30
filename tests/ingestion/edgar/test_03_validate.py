"""Structural validation of a segmented filing."""

from types import ModuleType

import pytest

NUMBER_PROFILE = {
    "segmentation": {"type": "number"},
    "validation": {"expected_items": 23, "must_have": ["1", "1A", "7", "8"]},
}


def _sections(edgar_module: ModuleType, items: list[str], blocks_each: int = 30):
    return [
        edgar_module.Section(
            part=edgar_module.PART_OF.get(item),
            item=item,
            canonical_title=edgar_module.CANONICAL.get(item, ""),
            reported_title="",
            blocks=[edgar_module.Block("paragraph", "Body") for _ in range(blocks_each)],
        )
        for item in items
    ]


def test_validate_collects_multiple_problems_in_a_list(edgar_module: ModuleType) -> None:
    """Collect all validation failures instead of raising at the first one.

    The caller decides on relearning from one complete, diagnosable list.
    """
    problems = edgar_module.validate(_sections(edgar_module, ["1", "1A"]), NUMBER_PROFILE)

    assert isinstance(problems, list)
    assert len(problems) >= 2


def test_validate_catches_count_missing_items_duplicates_and_order(
    edgar_module: ModuleType,
) -> None:
    """Reject the principal structural failures of numbered segmentation."""
    missing = " ".join(edgar_module.validate(_sections(edgar_module, ["1", "1A"]), NUMBER_PROFILE))
    duplicate_profile = {
        **NUMBER_PROFILE,
        "validation": {**NUMBER_PROFILE["validation"], "expected_items": 5},
    }
    duplicate = edgar_module.validate(
        _sections(edgar_module, ["1", "1A", "1A", "7", "8"]), duplicate_profile
    )
    ordered_profile = {
        **NUMBER_PROFILE,
        "validation": {**NUMBER_PROFILE["validation"], "expected_items": 4},
    }

    assert "2" in missing and "23" in missing
    assert "7" in missing and "8" in missing
    assert any("1A" in problem for problem in duplicate)
    assert (
        edgar_module.validate(_sections(edgar_module, ["1", "1A", "7", "8"]), ordered_profile) == []
    )
    assert edgar_module.validate(_sections(edgar_module, ["7", "1", "1A", "8"]), ordered_profile)


def test_validate_rejects_perfect_structure_without_body_content(
    edgar_module: ModuleType,
) -> None:
    """Catch a TOC mistaken for headings even when count and order look perfect.

    Structure alone passes on TOC-only sections, so core sections also need body depth.
    """
    items = list(edgar_module.CANONICAL)[:23]

    assert edgar_module.validate(_sections(edgar_module, items, 30), NUMBER_PROFILE) == []
    assert edgar_module.validate(_sections(edgar_module, items, 2), NUMBER_PROFILE)


@pytest.mark.parametrize("text", ["None.", "Not applicable.", "N/A", "none"])
def test_classify_sections_recognizes_empty_disclosures(
    edgar_module: ModuleType,
    text: str,
) -> None:
    """Treat explicit empty disclosures as valid filing states."""
    section = edgar_module.Section(
        part=None,
        item="4",
        canonical_title="",
        reported_title="",
        blocks=[edgar_module.Block("paragraph", text)],
    )

    edgar_module.classify_sections([section])

    assert section.status == "empty_disclosure"


def test_classify_sections_recognizes_proxy_references(edgar_module: ModuleType) -> None:
    """Recognize a short section whose required information lives in the proxy."""
    section = edgar_module.Section(
        part=None,
        item="11",
        canonical_title="",
        reported_title="",
        blocks=[
            edgar_module.Block(
                "paragraph",
                "The information required by this Item is incorporated herein by "
                "reference to the Proxy Statement.",
            )
        ],
    )

    edgar_module.classify_sections([section])

    assert section.status == "incorporated_by_reference"


def test_classify_sections_leaves_real_content_parsed(edgar_module: ModuleType) -> None:
    """Avoid reclassifying a substantive section that merely contains familiar words."""
    section = edgar_module.Section(
        part=None,
        item="1",
        canonical_title="",
        reported_title="",
        blocks=[edgar_module.Block("paragraph", "Accelerated computing. " * 40)],
    )

    edgar_module.classify_sections([section])

    assert section.status == "parsed"
