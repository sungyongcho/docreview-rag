"""Amendment Items are bounded conservatively and never touch a report's profile."""

from pathlib import Path

import pytest

from app.ingestion.parsing.registry import registry_for
from app.ingestion.parsing.sec import parse_filing
from app.ingestion.parsing.sec_amendment import parse_amendment
from app.ingestion.pipeline import structure_values
from app.ingestion.sources.models import FilingSource
from tests.ingestion.edgar.support import build_numbered_body
from tests.ingestion.support import filing_document, filing_source

ITEM_8 = "<h2>Item 8. Financial Statements and Supplementary Data</h2>"
PROFILE = "sec/TEST/profile.json"
# One tagged number with the context and unit it refers to, as a filing declares them.
TAGGED_REVENUE = (
    '<ix:header><ix:resources><xbrli:context id="fy24"><xbrli:entity>'
    '<xbrli:identifier scheme="cik">1</xbrli:identifier></xbrli:entity><xbrli:period>'
    "<xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate>"
    '</xbrli:period></xbrli:context><xbrli:unit id="usd">'
    "<xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></ix:resources></ix:header>"
    '<p>Revenue was <ix:nonFraction name="us-gaap:Revenues" contextRef="fy24" unitRef="usd"'
    ' scale="6" decimals="-6">100</ix:nonFraction> million.</p>'
)


def source_for(tmp_path: Path, body: str, *, form: str = "10-K/A") -> FilingSource:
    """Bind a compact filing of the given form to exact source bytes under ``tmp_path``."""
    path = tmp_path / ("amendment.html" if form == "10-K/A" else "original.html")
    path.write_text(f"<html>\n<body>\n{body}\n</body></html>")
    document = filing_document(issuer="TEST").model_copy(update={"form": form})
    return filing_source(path, document=document)


def section_text(result) -> str:
    """Join every block text of every section of one parsed filing."""
    return " ".join(block.text for section in result.sections for block in section.blocks)


def test_comma_separated_exhibit_title_bounds_part_three(tmp_path: Path) -> None:
    """The BUKS layout uses separate bold runs and a comma in the Item 15 title."""
    # Layout observed in the 2024-08-28 amendment, accession 0001437749-24-027935:
    # https://www.sec.gov/Archives/edgar/data/15847/000143774924027935/buks20240430_10ka.htm
    source = source_for(
        tmp_path,
        "<div><b>Item 14. PRINCIPAL ACCOUNTANT FEES AND SERVICES</b></div>"
        "<p>Accountant fee disclosure.</p><div><b>PART IV</b></div>"
        "<div><b>Item 15.</b>&nbsp;<b> EXHIBITS, FINANCIAL STATEMENT SCHEDULES</b></div>"
        "<p>New certification exhibits.</p><div><b>SIGNATURES</b></div>",
    )

    result, _ = parse_amendment(source)

    assert result.parse_status == "parsed"
    assert [section.item for section in result.sections] == ["14", "15"]
    assert [block.text for block in result.sections[0].blocks] == ["Accountant fee disclosure."]
    assert result.sections[0].blocks[-1].end_pos == source.read().index("<div><b>PART IV")
    assert [block.text for block in result.sections[1].blocks] == ["New certification exhibits."]


def test_linked_number_only_toc_and_inline_word_split_use_body_anchors(tmp_path: Path) -> None:
    """RAIL's number-only TOC and split 'and' resolve to its later numbered body headings."""
    # Layout observed in the 2020-04-06 amendment, accession 0001564590-20-015513:
    # https://www.sec.gov/Archives/edgar/data/1320854/000156459020015513/rail-10ka_20191231.htm
    source = source_for(
        tmp_path,
        '<table><tr><td><p><a href="#Item_8">Item 8.</a></p></td>'
        "<td><p>Financial Statements and Supplementary Data</p></td></tr>"
        '<tr><td><p><a href="#Item_15">Item 15.</a></p></td>'
        "<td><p>Exhibits, Financial Statement Schedules</p></td></tr></table>"
        '<p style="font-weight:bold"><a name="Item_8"></a>'
        "<font>Item 8. Financial Statements an</font><font>d Supplementary Data.</font></p>"
        "<p>Auditor signature page only.</p>"
        '<p style="font-weight:bold"><a name="Item_15"></a>'
        "Item 15. Exhibits, Financial Statement Schedules.</p><p>Consent exhibit.</p>",
    )

    result, _ = parse_amendment(source)

    assert result.parse_status == "parsed"
    assert [section.item for section in result.sections] == ["8", "15"]
    assert (
        result.sections[0].reported_title == "Item 8. Financial Statements and Supplementary Data."
    )
    raw = source.read()
    assert result.sections[0].source_pos == raw.index('<p style="font-weight:bold">')
    assert result.sections[0].blocks[-1].end_pos == raw.index(
        '<p style="font-weight:bold"><a name="Item_15">'
    )
    assert [block.text for block in result.sections[0].blocks] == ["Auditor signature page only."]


def _layout_heading(item: str, title: str) -> str:
    """Render a single-row heading table with a blank spacer and two bold content cells."""
    return (
        '<table><tr><td>&nbsp;</td><td><font><b><a name="body_' + item + '"></a>'
        f"Item {item}.</b></font></td><td><font><b>{title}</b></font></td></tr></table>"
    )


def test_layout_table_newlines_and_historical_titles_preserve_item_boundaries(
    tmp_path: Path,
) -> None:
    """HZON's body headings are short layout tables, with newlines and historical vocabulary."""
    # Layout observed in the 2021-05-18 amendment, accession 0001104659-21-068901:
    # https://www.sec.gov/Archives/edgar/data/1821788/000110465921068901/tm2116165d1_10ka.htm
    source = source_for(
        tmp_path,
        _layout_heading("6", "Selected Financial Data.")
        + "<p>Selected data disclosure.</p>"
        + _layout_heading("9A", "Controls and\n Procedures")
        + "<p>Restated control assessment.</p>"
        + _layout_heading("10", "Directors, Officers and Corporate Governance")
        + "<p>Director disclosure.</p>"
        + _layout_heading("16", "Form&nbsp;10-K Summary")
        + "<p>None.</p>",
    )

    result, _ = parse_amendment(source)

    assert result.parse_status == "parsed"
    assert [section.item for section in result.sections] == ["6", "9A", "10", "16"]
    assert result.sections[0].canonical_title == "Selected Financial Data"
    assert [section.blocks[0].text for section in result.sections] == [
        "Selected data disclosure.",
        "Restated control assessment.",
        "Director disclosure.",
        "None.",
    ]
    assert result.sections[1].blocks[-1].end_pos == result.sections[2].source_pos
    assert result.sections[3].status == "empty_disclosure"


def test_cover_and_explanatory_note_stay_outside_uppercase_span_headings(tmp_path: Path) -> None:
    """AMD's bold-span headings bound Items 7 and 15; the note before them joins no section."""
    # Layout observed in the FY2025 amendment, accession 0000002488-26-000021: upper-case
    # headings in a bold span, a typographic apostrophe, and no Part IV heading.
    bold = "font-size:10pt;font-weight:700"
    source = source_for(
        tmp_path,
        f'<div style="text-align:center"><span style="{bold}">FORM 10-K/A</span></div>'
        f'<div style="text-align:center"><span style="{bold}">Explanatory Note</span></div>'
        "<div><span>This Amendment corrects one sentence of Item 7 of the Original Filing."
        "</span></div>"
        f'<div style="text-align:center"><span style="{bold}">PART II</span></div>'
        f'<div style="margin-top:14pt"><span style="{bold}">ITEM&#160;7.       '
        "MANAGEMENT&#8217;S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF "
        "OPERATIONS</span></div><div><span>Corrected discussion.</span></div>"
        f'<div style="margin-top:14pt"><span style="{bold}">ITEM&#160;15.       '
        "EXHIBITS AND FINANCIAL STATEMENT SCHEDULES</span></div>"
        "<div><span>Index to Consolidated Financial Statements</span></div>"
        f'<div><span style="{bold}">SIGNATURES</span></div><div>Officer signature.</div>',
    )

    result, _ = parse_amendment(source)

    assert (result.parse_status, result.warnings) == ("parsed", [])
    assert [(section.item, section.part) for section in result.sections] == [
        ("7", "II"),
        ("15", "IV"),
    ]
    assert result.sections[0].canonical_title == "Management's Discussion and Analysis"
    assert [[block.text for block in section.blocks] for section in result.sections] == [
        ["Corrected discussion."],
        ["Index to Consolidated Financial Statements"],
    ]
    heading_at = result.sections[0].source_pos
    assert heading_at is not None and heading_at > source.read().index("This Amendment corrects")


@pytest.mark.parametrize(
    "pointer",
    [
        "Our financial statements and notes thereto begin on Page F-1.",
        "Our financial statement appendix begins on page F-1.",
        "Refer to the statements beginning on page F-1.",
        "The financial statement appendix starts on page F-1.",
    ],
)
def test_local_financial_appendix_pointer_stays_non_ready(tmp_path: Path, pointer: str) -> None:
    """The observed HZON F-1 pointer must not absorb or silently omit post-signature statements."""
    source = source_for(
        tmp_path,
        _layout_heading("8", "Financial Statements and Supplementary Data.")
        + f"<p>{pointer}</p>"
        + _layout_heading("9A", "Controls and\n Procedures")
        + "<p>Restated control assessment.</p><p><b>SIGNATURES</b></p>"
        + "<p>Officer signature.</p><p>F-1</p><p>Restated balance sheet.</p>",
    )

    result, _ = parse_amendment(source)

    assert result.parse_status == "needs_profile_update"
    assert [section.item for section in result.sections] == ["8", "9A"]
    assert any(
        "unresolved amendment Item 8 page reference" in warning for warning in result.warnings
    )
    assert [block.text for block in result.sections[0].blocks] == [pointer]
    assert [block.text for block in result.sections[1].blocks] == ["Restated control assessment."]


def test_item_eight_only_has_source_spans_without_training_a_profile(tmp_path: Path) -> None:
    """An explicit Item 8 can stand alone; the note remains in the original artifact."""
    source = source_for(
        tmp_path,
        "<h2>Explanatory Note</h2><p>This amendment updates the auditor report.</p>"
        f"{ITEM_8}<p>Auditor report replacement text.</p>"
        "<h2>SIGNATURES</h2><p>Officer signature.</p>",
    )

    result, profile = parse_amendment(source)

    assert (result.parse_status, result.warnings) == ("parsed", [])
    assert (result.profile_used, result.segment_type) == ("amendment", "amendment_number")
    assert profile["segmentation"]["type"] == "amendment_number"
    (section,) = result.sections
    assert (section.item, section.part) == ("8", "II")
    (block,) = section.blocks
    raw = source.read()
    assert block.text == "Auditor report replacement text."
    assert (block.source_pos, block.end_pos) == (
        raw.index("<p>Auditor report"),
        raw.index("<h2>SIGNATURES"),
    )
    assert "This amendment updates the auditor report." not in section_text(result)
    assert not (tmp_path / PROFILE).exists()


def test_amendment_carries_the_same_source_identity_as_a_report_parse(tmp_path: Path) -> None:
    """Length, digest and tagged facts match what the report parser records for the same bytes."""
    body = f"{ITEM_8}{TAGGED_REVENUE}"
    amendment, _ = parse_amendment(source_for(tmp_path, body))
    report, _ = parse_filing(source_for(tmp_path, body, form="10-K"))

    assert len(amendment.facts.facts) == 1
    assert (amendment.source_length, amendment.source_sha256, amendment.facts) == (
        report.source_length,
        report.source_sha256,
        report.facts,
    )
    # A heading-segmented parse lists no index entries, and the stored structure accepts that.
    assert amendment.item_index == []
    assert structure_values(amendment)["parse_status"] == "parsed"


def test_part_three_additions_remain_separate_numbered_items(tmp_path: Path) -> None:
    """Partial Part III Items have their own boundaries without inferred replacement scope."""
    source = source_for(
        tmp_path,
        "<h2>PART III</h2>"
        "<h3>Item 10. Directors, Executive Officers and Corporate Governance</h3>"
        "<p>New director information.</p>"
        "<h3>Item 11. Executive Compensation</h3><p>New compensation information.</p>"
        "<p>Item 402(v) of Regulation S-K requires the pay comparison below.</p>"
        "<h2>PART IV</h2>"
        "<h3>Item 15. Exhibits and Financial Statement Schedules</h3>"
        "<p>Certification exhibit.</p>",
    )

    result, _ = parse_amendment(source)

    assert (result.parse_status, result.warnings) == ("parsed", [])
    assert [(section.item, section.part) for section in result.sections] == [
        ("10", "III"),
        ("11", "III"),
        ("15", "IV"),
    ]
    # A Regulation S-K citation is body text, not a heading of Item 4.
    assert [block.text for block in result.sections[1].blocks] == [
        "New compensation information.",
        "Item 402(v) of Regulation S-K requires the pay comparison below.",
    ]
    raw = source.read()
    assert result.sections[1].blocks[-1].end_pos == raw.index("<h2>PART IV")


@pytest.mark.parametrize(
    ("item", "title"),
    [
        ("9C", "Disclosure Regarding Foreign Jurisdictions that Prevent Inspections"),
        ("15", "Exhibit and Financial Statement Schedules"),
    ],
)
def test_form_titles_longer_than_the_canonical_one_are_recognized(
    tmp_path: Path, item: str, title: str
) -> None:
    """A heading printed with the title Form 10-K itself gives still names its Item."""
    source = source_for(tmp_path, f"<h2>Item {item}. {title}</h2><p>Disclosure.</p>")

    result, _ = parse_amendment(source)

    assert (result.parse_status, result.warnings) == ("parsed", [])
    assert [section.item for section in result.sections] == [item]
    assert result.sections[0].canonical_title == title


def test_replacement_table_retains_exact_source_boundaries(tmp_path: Path) -> None:
    """A supported table carries its original HTML and cannot cross the next Item."""
    source = source_for(
        tmp_path,
        f"{ITEM_8}<table><tr><th>Revenue</th><th>2024</th><th>2023</th></tr>"
        "<tr><td>Total</td><td>100</td><td>90</td></tr></table>"
        "<h2>SIGNATURES</h2><p>Officer signature.</p>"
        "<h2>Item 15. Exhibits and Financial Statement Schedules</h2>"
        "<p>Certification exhibit.</p>",
    )

    result, _ = parse_amendment(source)

    assert result.parse_status == "parsed"
    assert [section.item for section in result.sections] == ["8", "15"]
    table = result.sections[0].blocks[0]
    raw = source.read()
    assert table.kind == "table"
    assert table.html == raw[raw.index("<table>") : raw.index("</table>") + len("</table>")]
    assert (table.source_pos, table.end_pos) == (raw.index("<table>"), raw.index("<h2>SIGNATURES"))
    assert table.cell_spans is not None and len(table.cell_spans) == 6
    assert all(raw[start:end].startswith(("<th>", "<td>")) for start, end in table.cell_spans)
    assert "Officer signature" not in section_text(result)


@pytest.mark.parametrize(
    ("body", "warning"),
    [
        ("<p>No numbered sections.</p>", "no confidently bounded amendment Items"),
        (ITEM_8, "empty Item 8"),
        (
            f"{ITEM_8}<p>First.</p>{ITEM_8}<p>Second.</p>",
            "duplicate amendment Items",
        ),
        (
            "<h2>Item 11. Executive Compensation</h2><p>Compensation.</p>"
            "<h2>Item 10. Directors, Executive Officers and Corporate Governance</h2>"
            "<p>Directors.</p>",
            "amendment Item order mismatch",
        ),
        (
            '<h2><a href="#item8">Item 8. Financial Statements and Supplementary Data</a></h2>'
            "<p>This could be a table of contents.</p>",
            "uncertain amendment Item heading",
        ),
        (
            '<p><a href="#exhibits">Item 8.</a></p>'
            '<h2 id="exhibits">Item 15. Exhibits and Financial Statement Schedules</h2>'
            "<p>A target belonging to another Item cannot validate a TOC entry.</p>",
            "uncertain amendment Item heading",
        ),
        (
            "<table><tr><td><b>Item 8.</b></td>"
            "<td><b>Financial Statements and Supplementary Data</b></td></tr>"
            "<tr><td><b>Revenue</b></td><td><b>100</b></td></tr></table>",
            "uncertain amendment Item heading",
        ),
        (
            f"{ITEM_8}<p>Financials.</p><p>Item 9A. Controls and Procedures</p><p>Controls.</p>",
            "uncertain amendment Item heading",
        ),
        (
            f"{ITEM_8}<p>Financials.</p><h2>Item 9A. Unknown heading</h2><p>Controls.</p>",
            "uncertain amendment Item heading",
        ),
        (
            f'{ITEM_8}<table><tr><td colspan="invalid">Broken</td><td>100</td></tr></table>',
            "malformed amendment table",
        ),
        (
            f'{ITEM_8}<table><tr><td rowspan="2">Broken</td><td>100</td></tr></table>',
            "malformed amendment table",
        ),
        (
            f'{ITEM_8}<table><tr><td colspan="0">Broken</td><td>100</td></tr></table>',
            "malformed amendment table",
        ),
    ],
)
def test_uncertain_partial_structure_is_not_ready(tmp_path: Path, body: str, warning: str) -> None:
    """Ambiguous boundaries and malformed tables cannot become ready amendment evidence."""
    result, _ = parse_amendment(source_for(tmp_path, body))

    assert result.parse_status == "needs_profile_update"
    assert any(warning in problem for problem in result.warnings)
    assert structure_values(result)["parse_status"] == "needs_profile_update"
    assert not (tmp_path / PROFILE).exists()


def test_each_parser_refuses_the_other_kind_of_filing(tmp_path: Path) -> None:
    """A direct call can neither parse an amendment as a report nor a report as an amendment."""
    amendment = source_for(tmp_path, f"{ITEM_8}<p>New report.</p>")
    report = source_for(tmp_path, build_numbered_body(gap=21), form="10-K")

    with pytest.raises(ValueError, match="is an amendment"):
        parse_filing(amendment)
    with pytest.raises(ValueError, match="is not an amendment"):
        parse_amendment(report)
    assert not (tmp_path / PROFILE).exists()


def test_registry_routes_each_kind_of_filing_to_its_parser(tmp_path: Path) -> None:
    """The EDGAR adapter parses an amendment without a profile and a report with one."""
    parse = registry_for("sec").parse
    amendment = source_for(tmp_path, f"{ITEM_8}<p>New report.</p>")
    report = source_for(tmp_path, build_numbered_body(gap=21), form="10-K")

    routed_amendment, _ = parse(amendment)
    assert routed_amendment == parse_amendment(amendment)[0]
    assert routed_amendment.profile_used == "amendment"
    assert not (tmp_path / PROFILE).exists()

    routed_report, _ = parse(report)
    assert (routed_report.profile_used, routed_report.segment_type) == ("bootstrap", "number")
    assert (tmp_path / PROFILE).exists()


def test_amendment_neither_changes_the_report_profile_nor_the_report_parse(tmp_path: Path) -> None:
    """A report keeps its learned profile and its sections before and after an amendment."""
    parse = registry_for("sec").parse
    original = source_for(tmp_path, build_numbered_body(gap=21), form="10-K")
    before, _ = parse(original)
    assert before.parse_status == "parsed"
    profile_path = tmp_path / PROFILE
    saved = profile_path.read_bytes()

    amendment = source_for(tmp_path, f"{ITEM_8}<p>New report.</p>")
    partial, _ = parse(amendment)
    assert partial.parse_status == "parsed"
    assert profile_path.read_bytes() == saved

    after, _ = parse(original)
    assert (after.parse_status, after.profile_used) == ("parsed", "saved")
    assert after.sections == before.sections
    assert profile_path.read_bytes() == saved

    # The same partial bytes filed as a whole report still fail whole-report validation.
    incomplete_original = source_for(tmp_path, amendment.read(), form="10-K")
    rejected, _ = parse(incomplete_original)
    assert rejected.parse_status == "needs_profile_update"
    assert profile_path.read_bytes() == saved
