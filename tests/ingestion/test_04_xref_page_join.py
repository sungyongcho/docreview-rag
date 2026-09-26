"""Source-preserving joins from a filing's cross-reference index and company TOC."""

import pytest

from app.ingestion.edgar import segment_by_xref
from app.ingestion.parser import leaf_blocks, line_offsets, normalize


@pytest.fixture
def xref_filing():
    """Build an abbreviated filing with disjoint Items, a missing TOC entry and page furniture."""
    index = """
<table id="xref">
<tr><td>Item 1.</td><td>Business</td><td>1, 7</td></tr>
<tr><td>Item 1A.</td><td>Risk Factors</td><td>2, 8</td></tr>
<tr><td>Item 3.</td><td>Legal Proceedings</td><td>6</td></tr>
<tr><td>Item 7.</td><td>Management Discussion</td><td>3, 9</td></tr>
<tr><td>Item 8.</td><td>Financial Statements</td><td>4-5</td></tr>
<tr><td>Item 10.</td><td>Directors</td><td>(a)</td></tr>
<tr><td>Item 11.</td><td>Compensation</td><td>(a)</td></tr>
<tr><td>Item 12.</td><td>Ownership</td><td>(a)</td></tr>
<tr><td>Item 13.</td><td>Related Transactions</td><td>(a)</td></tr>
<tr><td>Item 14.</td><td>Audit Fees</td><td>(a)</td></tr>
<tr><td>Item 15.</td><td>Exhibits</td><td>10, 12</td></tr>
<tr><td>(a) Incorporated by reference from the definitive proxy statement.</td></tr>
</table>
"""
    pages = [
        (1, "business", "Business Overview"),
        (2, "risk", "Risk Factors"),
        (3, "discussion", "Management Discussion"),
        (4, "statements", "Financial Statements"),
        (5, "notes", "Notes to Financial Statements"),
        (6, "legal", "Legal Proceedings"),
        (7, "markets", "Market Outlook"),
        (8, "controls", "Risk Management"),
        (9, "capital", "Capital Resources"),
        (10, "exhibits", "Exhibits"),
        (12, "continuation", None),
    ]
    toc = (
        '<table id="toc"><tr><th>Section</th><th>Page</th></tr>'
        + "".join(
            f"<tr><td>{title}</td><td>{page}</td></tr>"
            for page, name, title in pages
            if title is not None and name != "legal"
        )
        + "<tr><td>Signatures</td><td>13</td></tr></table>"
    )
    shared = "Shared evidence remains distinct when disclosed in separate filing sections."
    body = []
    for page, name, title in pages:
        if title is not None:
            body.append(f'<p id="{name}-heading">{title}</p>')
        body.extend(
            [
                f'<p id="{name}-shared">{shared}</p>',
                f'<p id="{name}-fact">The {name} disclosure explains the company position.</p>',
                f'<p id="{name}-detail">Additional evidence for the {name} disclosure.</p>',
            ]
        )
        if name == "statements":
            body.append(
                '<table id="financial"><tr><th>Metric</th><th>2024</th><th>2023</th></tr>'
                "<tr><td>Revenue</td><td>120</td><td>100</td></tr>"
                "<tr><td>Expenses</td><td>80</td><td>70</td></tr></table>"
            )
        body.append("<p>Table of Contents</p>")
        if name != "notes":
            body.append(f"<p>{page}</p>")
    return "\n".join(["<html><body>", index, toc, *body, "</body></html>"])


def test_page_join_preserves_item_ownership_and_distinct_source_occurrences(xref_filing):
    """Recover omitted headings and join disjoint ranges without moving or duplicating evidence."""
    raw = xref_filing
    soup = normalize(raw)
    parsed, _index = segment_by_xref(soup, leaf_blocks(soup), line_offsets(raw), len(raw))
    sections = {section.item: section for section in parsed}
    ownership = {
        "1": ("business", "markets"),
        "1A": ("risk", "controls"),
        "3": ("legal",),
        "7": ("discussion", "capital"),
        "8": ("statements", "notes"),
        "15": ("exhibits", "continuation"),
    }
    emitted = []
    for item, narratives in ownership.items():
        expected = []
        for name in narratives:
            parts = ("shared", "fact", "detail")
            if name != "continuation":
                parts = ("heading", *parts)
            expected.extend(raw.index(f'<p id="{name}-{part}">') for part in parts)
            if name == "statements":
                expected.append(raw.index('<table id="financial">'))
        assert [block.source_pos for block in sections[item].blocks] == expected
        emitted.extend(sections[item].blocks)
    spans = [(block.source_pos, block.end_pos) for block in emitted]
    assert len(spans) == len(set(spans))
    for block in emitted:
        assert block.source_pos is not None and block.end_pos is not None
        assert 0 <= block.source_pos < block.end_pos <= len(raw)
        evidence = normalize(raw[block.source_pos : block.end_pos]).get_text(" ", strip=True)
        visible = (
            normalize(block.html).get_text(" ", strip=True) if block.kind == "table" else block.text
        )
        assert visible and visible in evidence
        assert visible != "Table of Contents" and not visible.isdigit()
    financial = next(block for block in sections["8"].blocks if block.kind == "table")
    assert normalize(financial.html).get_text(" ", strip=True) == (
        "Metric 2024 2023 Revenue 120 100 Expenses 80 70"
    )


def test_reference_only_items_preserve_proxy_provenance_without_body_evidence(xref_filing):
    """A referenced Part III Item retains its note and never acquires unrelated body blocks."""
    raw = xref_filing
    soup = normalize(raw)
    parsed, item_index = segment_by_xref(soup, leaf_blocks(soup), line_offsets(raw), len(raw))
    sections = {section.item: section for section in parsed}
    for item in ("10", "11", "12", "13", "14"):
        section = sections[item]
        assert section.status == "incorporated_by_reference"
        assert section.reference_source == (
            "Incorporated by reference from the definitive proxy statement."
        )
        assert section.blocks == []
        entry = next(entry for entry in item_index if entry["item"] == item)
        assert entry["status"] == section.status
        assert entry["reference_source"] == section.reference_source
        assert entry["pages"] == []
