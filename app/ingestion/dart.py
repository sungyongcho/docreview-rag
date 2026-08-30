"""Parse a DART 사업보고서 into the source-anchored section contract.

DART publishes its own markup, so the detection rules live here and nothing about
them reaches the neutral ``Section`` contract: no Item label, no CIK, no EDGAR
heading heuristic. What crosses the boundary is a ``ParsedFiling`` whose blocks carry
character offsets into the archived UTF-8 source, exactly as the EDGAR parser produces.

The part structure is read from the markup rather than inferred from presentation.
Every top-level division is a ``<SECTION-1>`` whose first ``<TITLE>`` child names it,
which makes detection exact and leaves no profile to learn.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any, Final
import unicodedata

from bs4 import Tag

from app.ingestion.parser import (
    HEADING_TAGS,
    REPORTED_TITLE_MAX,
    Block,
    ParsedFiling,
    Section,
    block_source_spans,
    leaf_blocks,
    line_offsets,
    normalize,
    read_source,
    source_digest,
)

# The twelve top-level divisions of a 사업보고서, in filing order. Measured identically
# on the FY2024 reports of 005930 and 000660; the spellings are the registry's own.
DART_PARTS: Final[dict[str, str]] = {
    "I": "회사의 개요",
    "II": "사업의 내용",
    "III": "재무에 관한 사항",
    "IV": "이사의 경영진단 및 분석의견",
    "V": "회계감사인의 감사의견 등",
    "VI": "이사회 등 회사의 기관에 관한 사항",
    "VII": "주주에 관한 사항",
    "VIII": "임원 및 직원 등에 관한 사항",
    "IX": "계열회사 등에 관한 사항",
    "X": "대주주 등과의 거래내용",
    "XI": "그 밖에 투자자 보호를 위하여 필요한 사항",
    "XII": "상세표",
}
DART_PART_ORDER: Final[tuple[str, ...]] = tuple(DART_PARTS)

# The counterpart of the EDGAR parser's must-have Items: the business description and
# the financial statements are what a review of this filing is actually about.
CORE_PARTS: Final[tuple[str, ...]] = ("II", "III")

# `<TE>` and `<TU>` are table cells, not blocks, and `<div>` does not occur. Including
# either would emit thousands of cell fragments as standalone paragraphs.
DART_LEAF_TAGS: Final[tuple[str, ...]] = ("title", "p", "table", *HEADING_TAGS)

# Accepts the fullwidth period and the Unicode Roman numerals; the numeral is folded to
# ASCII before lookup so `Ⅷ.` and `VIII.` name the same part.
DART_PART_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<roman>[IVXivxⅠ-Ⅻ]{1,5})\s*[.．]\s*(?P<title>.+?)\s*$"
)

SECTION_TAG: Final[str] = "section-1"
COVERAGE_FLOOR: Final[float] = 0.90


class DartParseError(ValueError):
    """A DART source or its manifest entry violates the parser's input contract."""


def part_numeral(title_text: str) -> tuple[str, str] | None:
    """Return the ASCII Roman numeral and reported title of a part heading.

    Returns ``None`` when the text is not a numbered top-level division, which is how
    the cover section 【 대표이사 등의 확인 】 and every subsection are excluded.
    """
    match = DART_PART_RE.match(title_text)
    if match is None:
        return None
    numeral = unicodedata.normalize("NFKC", match.group("roman")).upper()
    if numeral not in DART_PARTS:
        return None
    return numeral, match.group("title")


def _is_part_heading(element: Tag) -> bool:
    """Report whether an element is the ``<TITLE>`` naming a top-level division."""
    parent = element.parent
    return (
        element.name == "title"
        and parent is not None
        and parent.name == SECTION_TAG
        and part_numeral(element.get_text(" ", strip=True)) is not None
    )


def _block(element: Tag, text: str, start: int, end: int) -> Block:
    """Build one source-positioned block from a DART element."""
    if element.name == "table":
        return Block("table", text, html=str(element), source_pos=start, end_pos=end)
    if element.name == "title" or element.name in HEADING_TAGS:
        # Part headings never reach here (segment() keeps them out of the blocks),
        # so every heading block is a narrative subheading.
        return Block("heading", text, level=2, source_pos=start, end_pos=end)
    return Block("paragraph", text, source_pos=start, end_pos=end)


def segment(elements: list[Tag], source: str) -> tuple[list[Section], list[str]]:
    """Group source-positioned elements into the filing's top-level divisions.

    Parameters
    ----------
    elements : list[Tag]
        Leaf blocks in document order, as ``leaf_blocks`` returned them.
    source : str
        Canonical decoded source the spans index into.

    Returns
    -------
    tuple[list[Section], list[str]]
        Sections in filing order, and warnings about structure that is present but
        irregular. Content before the first numbered division is the cover material
        and is dropped, the same way the EDGAR heading path drops a table of contents.

    Raises
    ------
    DartParseError
        If no numbered division is found at all. An empty section list would seed a
        document with zero chunks and report success.
    """
    offsets = line_offsets(source)
    spans = block_source_spans(elements, offsets, len(source))

    sections: list[Section] = []
    warnings: list[str] = []
    seen: list[str] = []
    current: Section | None = None

    for element, (start, end) in zip(elements, spans, strict=True):
        text = element.get_text(" ", strip=True)
        if start is None or end is None:
            raise DartParseError(f"element <{element.name}> has no source offset")

        if _is_part_heading(element):
            numeral, reported = part_numeral(text) or ("", "")
            if numeral in seen:
                warnings.append(f"part {numeral} appears more than once")
            seen.append(numeral)
            current = Section(
                part=numeral,
                item=numeral,
                canonical_title=DART_PARTS[numeral],
                reported_title=text[:REPORTED_TITLE_MAX] or reported,
                blocks=[],
            )
            sections.append(current)
            # The heading is the section's identity, not its content; keeping it out
            # of the blocks matches the EDGAR parser and keeps the label from being
            # indexed twice in the section's first chunk.
            continue

        if (
            element.name == "title"
            and element.parent is not None
            and (element.parent.name == SECTION_TAG)
        ):
            # A SECTION-1 whose title is not a numbered part is cover material —
            # 【 대표이사 등의 확인 】 before part I, 【 전문가의 확인 】 after the
            # last part — and its content belongs to no division.
            current = None
            continue

        if current is None:
            continue  # cover material outside the numbered divisions
        if not text and element.name != "table":
            continue
        current.blocks.append(_block(element, text, start, end))

    if not sections:
        raise DartParseError("no numbered top-level division found in the source")

    ordered = [numeral for numeral in DART_PART_ORDER if numeral in seen]
    if seen != ordered:
        warnings.append(f"parts are out of filing order: {' '.join(seen)}")
    for numeral in CORE_PARTS:
        if numeral not in seen:
            warnings.append(f"core part {numeral} ({DART_PARTS[numeral]}) is missing")
    return sections, warnings


def _coverage(sections: list[Section], total_chars: int) -> float:
    """Return the fraction of document text the sections actually carry."""
    if total_chars <= 0:
        return 0.0
    covered = sum(len(block.text) for section in sections for block in section.blocks)
    return covered / total_chars


def parse_dart_filing(entry: dict[str, Any]) -> tuple[ParsedFiling, dict[str, Any]]:
    """Parse one archived DART annual report named by a manifest entry.

    Parameters
    ----------
    entry : dict[str, Any]
        Registry-neutral manifest entry written by the DART downloader. Its
        ``source_length`` and ``source_sha256`` are checked against the file so a
        re-transcoded or truncated archive is caught before any span is produced.

    Returns
    -------
    tuple[ParsedFiling, dict[str, Any]]
        The parsed filing and its static segmentation profile. The profile is
        constant because the part vocabulary is fixed markup rather than a learned
        presentation rule, and it is returned only to satisfy the parser contract.

    Raises
    ------
    DartParseError
        If the entry names another registry, the source cannot be read as UTF-8, the
        source no longer matches the digest or length the manifest recorded, line
        offsets disagree with the source, or no numbered division is present.
    """
    registry = str(entry.get("registry", ""))
    if registry != "dart":
        raise DartParseError(f"manifest entry is not a DART filing: registry={registry!r}")

    try:
        raw = read_source(entry["file"])
    except UnicodeDecodeError:
        raise DartParseError(f"{entry['file']} is not UTF-8; re-run the archive step") from None

    _verify_source_identity(entry, raw)

    soup = normalize(raw)
    elements = leaf_blocks(soup, DART_LEAF_TAGS)
    sections, warnings = segment(elements, raw)

    total_chars = sum(len(element.get_text(" ", strip=True)) for element in elements)
    coverage = _coverage(sections, total_chars)
    if coverage < COVERAGE_FLOOR:
        warnings.append(f"section coverage {coverage:.1%} is below {COVERAGE_FLOOR:.0%}")

    filing = ParsedFiling(
        doc_id=dart_doc_id(entry),
        registry="dart",
        issuer=str(entry["issuer"]),
        issuer_id=str(entry["issuer_id"]),
        filing_id=str(entry["filing_id"]),
        form=str(entry["form"]),
        filing_date=str(entry["filing_date"]),
        report_period=str(entry["report_period"]),
        fiscal_year=int(entry["fiscal_year"]),
        source_url=str(entry["url"]),
        source_length=len(raw),
        source_sha256=source_digest(raw),
        sections=sections,
        parse_status="needs_profile_update" if warnings else "parsed",
        warnings=warnings,
        profile_used="static",
        segment_type="dart_part",
        n_blocks=len(elements),
        n_chars=total_chars,
    )
    return filing, {"segmentation": {"kind": "dart_section_1", "parts": list(DART_PARTS)}}


def _verify_source_identity(entry: Mapping[str, Any], raw: str) -> None:
    """Reject a source that drifted from the identity the manifest recorded.

    Raises
    ------
    DartParseError
        If length, digest, or newline-derived line offsets disagree with the file.
    """
    expected_length = entry.get("source_length")
    if isinstance(expected_length, int) and expected_length != len(raw):
        raise DartParseError(
            f"{entry['file']} is {len(raw)} chars, manifest records {expected_length}"
        )
    expected_digest = entry.get("source_sha256")
    if (
        isinstance(expected_digest, str)
        and expected_digest
        and expected_digest != source_digest(raw)
    ):
        raise DartParseError(f"{entry['file']} does not match the manifest source digest")
    if len(line_offsets(raw)) != raw.count("\n") + 1:
        raise DartParseError(f"{entry['file']} produced untrustworthy line offsets")


def dart_doc_id(entry: Mapping[str, Any]) -> str:
    """Return the document ID derived from a DART manifest entry.

    The ``"{issuer}-FY{year}"`` shape is the shared contract; reading it out of the
    stock code and fiscal year is DART-specific.
    """
    return f"{entry['issuer']}-FY{entry['fiscal_year']}"


def dart_sort_key(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Order DART entries by issuer stock code, then receipt number."""
    return (str(entry.get("issuer", "")), str(entry.get("filing_id", "")))


def dart_section_label(item: str) -> str:
    """Return the numeral with its division name, as the filing's own table of contents
    spells it, so a bare citation stays meaningful without the context header.
    """
    title = DART_PARTS.get(item)
    return f"{item}. {title}" if title else item
