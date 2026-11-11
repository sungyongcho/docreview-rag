"""Filing fact tags: contexts, units, tagged numbers and the fiscal years they declare."""

from datetime import date

import pytest

from app.ingestion.parsing.facts import (
    FactUnit,
    FilingFacts,
    dart_facts,
    dart_period_terms,
    dart_statements,
    sec_facts,
)
from tests.ingestion.support import filing_document

# A 52/53-week issuer whose fiscal 2024 ends on 2024-12-28.
AMD = filing_document(fiscal_year=2024).model_copy(update={"report_period": date(2024, 12, 28)})
HEADER = """<ix:header><ix:resources>
<xbrli:context id="fy24"><xbrli:entity><xbrli:identifier scheme="cik">1</xbrli:identifier>
</xbrli:entity><xbrli:period><xbrli:startDate>2023-12-31</xbrli:startDate>
<xbrli:endDate>2024-12-28</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="open"><xbrli:entity><xbrli:identifier scheme="cik">1</xbrli:identifier>
</xbrli:entity><xbrli:period><xbrli:instant>2023-12-30</xbrli:instant></xbrli:period>
</xbrli:context>
<xbrli:context id="q4"><xbrli:entity><xbrli:identifier scheme="cik">1</xbrli:identifier>
</xbrli:entity><xbrli:period><xbrli:startDate>2024-09-29</xbrli:startDate>
<xbrli:endDate>2024-12-28</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="dc"><xbrli:entity><xbrli:identifier scheme="cik">1</xbrli:identifier>
<xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">
amd:DataCenterMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period>
<xbrli:startDate>2023-12-31</xbrli:startDate><xbrli:endDate>2024-12-28</xbrli:endDate>
</xbrli:period></xbrli:context>
<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator>
<xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator><xbrli:unitDenominator>
<xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>
</ix:resources></ix:header>"""


def _fact(context: str, unit: str, text: str, scale: str = ' scale="6"') -> str:
    """Render one inline XBRL number tag."""
    return (
        f'<ix:nonFraction name="us-gaap:Revenues" contextRef="{context}" unitRef="{unit}"'
        f'{scale} decimals="-6">{text}</ix:nonFraction>'
    )


def test_sec_facts_read_contexts_units_and_tag_spans() -> None:
    """Each tagged number keeps its tag's source span, context, unit and scale."""
    cell = f"<td>$ {_fact('fy24', 'usd', '25,785')}</td>"
    raw = f"<html>{HEADER}<table><tr>{cell}</tr></table></html>"

    facts = sec_facts(raw, AMD)

    assert facts.source == "ixbrl"
    (fact,) = facts.facts
    assert raw[fact.start_char : fact.end_char].startswith("<ix:nonFraction")
    assert (fact.concept, fact.context_id, fact.unit_id, fact.scale, fact.text) == (
        "us-gaap:Revenues",
        "fy24",
        "usd",
        6,
        "25,785",
    )
    assert FactUnit("usdPerShare", "iso4217:USD", "xbrli:shares") in facts.units
    start = raw.index("<td>")
    assert facts.within(start, start + len(cell)) == (fact,)
    assert facts.within(0, start) == ()


def test_sec_fiscal_years_cover_annual_periods_and_year_end_instants_only() -> None:
    """Annual durations and year-end instants get a fiscal year; a quarter does not."""
    contexts = {
        context.context_id: context
        for context in sec_facts(f"{HEADER}{_fact('fy24', 'usd', '1')}", AMD).contexts
    }

    assert contexts["fy24"].fiscal_year == 2024
    assert contexts["open"].fiscal_year == 2023
    assert contexts["q4"].fiscal_year is None
    assert contexts["dc"].dimensions == (
        ("us-gaap:StatementBusinessSegmentsAxis", "amd:DataCenterMember"),
    )
    assert contexts["fy24"].dimensions == ()


@pytest.mark.parametrize(
    ("report_period", "fiscal_year", "prior_end", "expected"),
    [
        (date(2024, 1, 28), 2024, date(2023, 1, 29), 2023),
        (date(2022, 1, 1), 2021, date(2021, 1, 2), 2020),
        (date(2024, 12, 31), 2024, date(2019, 12, 31), 2019),
    ],
)
def test_sec_fiscal_years_follow_the_document_naming(
    report_period: date, fiscal_year: int, prior_end: date, expected: int
) -> None:
    """Prior fiscal years are counted back from the document's own year and year end."""
    document = filing_document(fiscal_year=fiscal_year).model_copy(
        update={"report_period": report_period}
    )
    header = (
        '<xbrli:context id="p"><xbrli:period>'
        f"<xbrli:instant>{prior_end.isoformat()}</xbrli:instant></xbrli:period></xbrli:context>"
    )

    (context,) = sec_facts(f"{header}{_fact('p', 'usd', '1')}", document).contexts

    assert context.fiscal_year == expected


def test_sec_facts_skip_nil_and_enclosing_tags_and_default_the_scale() -> None:
    """A nil fact and a fact enclosing another carry no single number; scale defaults to 0."""
    nil = '<ix:nonFraction name="us-gaap:Revenues" contextRef="fy24" xsi:nil="true"/>'
    nested = (
        '<ix:nonFraction name="a" contextRef="fy24" unitRef="usd">'
        f"{_fact('fy24', 'usd', '2')}</ix:nonFraction>"
    )
    plain = _fact("fy24", "usdPerShare", "0.31", scale="")

    facts = sec_facts(f"{HEADER}{nil}{nested}<p>{plain}</p>", AMD)

    assert [(fact.text, fact.scale) for fact in facts.facts] == [("0.31", 0)]


def test_filings_without_tags_have_no_facts() -> None:
    """A plain HTML filing yields empty facts; an untagged DART report only its form."""
    assert sec_facts("<table><tr><td>1,234</td></tr></table>", AMD) == FilingFacts()
    dart = filing_document(registry="dart")
    assert dart_facts("<TABLE><TR><TE>1,234</TE></TR></TABLE>", dart) == FilingFacts(
        "dart", scope_declared=True
    )


def test_dart_facts_read_tagged_cells_and_their_contexts() -> None:
    """A DART cell's ACONTEXT names its fiscal year and consolidated or separate scope."""
    document = filing_document(registry="dart", fiscal_year=2024)
    consolidated = (
        "ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_ConsolidatedMember"
    )
    separate = "ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_SeparateMember"
    raw = (
        f'<TR><TE ACODE="ifrs-full_Revenue" ACONTEXT="CFY2024dFY_{consolidated}" ADECIMAL="-6">'
        "300,870,903</TE>"
        f'<TE ACODE="ifrs-full_Revenue" ACONTEXT="PFY2023dFY_{separate}">170,374,090</TE>'
        '<TE ACODE="ifrs-full_Revenue" ACONTEXT="PFY2022dFY">1</TE></TR>'
    )

    facts = dart_facts(raw, document)

    assert facts.source == "dart"
    assert [(fact.concept, fact.text, fact.decimals) for fact in facts.facts] == [
        ("ifrs-full_Revenue", "300,870,903", "-6"),
        ("ifrs-full_Revenue", "170,374,090", None),
        ("ifrs-full_Revenue", "1", None),
    ]
    assert raw[facts.facts[0].start_char :].startswith("<TE ")
    contexts = {context.context_id: context for context in facts.contexts}
    current = contexts[f"CFY2024dFY_{consolidated}"]
    assert (current.fiscal_year, current.dimensions) == (
        2024,
        (
            (
                "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis",
                "ifrs-full:ConsolidatedMember",
            ),
        ),
    )
    assert contexts[f"PFY2023dFY_{separate}"].fiscal_year == 2023
    # "Prior year 2022" contradicts the document's fiscal 2024, so no year is given.
    assert contexts["PFY2022dFY"].fiscal_year is None


def test_dart_unreadable_contexts_keep_an_opaque_scope() -> None:
    """A context id outside the known form keeps no year and cannot read as unscoped."""
    document = filing_document(registry="dart", fiscal_year=2024)

    (context,) = dart_facts('<TE ACODE="a" ACONTEXT="Q2024_x">1</TE>', document).contexts

    assert context.fiscal_year is None
    assert context.dimensions == (("unparsed", "Q2024_x"),)


# A DART report's cover and statement headings, split by markup as the reports are.
DART_DECLARATIONS = (
    "<TR><TD>사업연도</TD><TD>2024년 01월 01일</TD><TD>부터</TD></TR>"
    "<TR><TD></TD><TD>2024년 12월 31일</TD><TD>까지</TD></TR>"
    "<P>제 56 기 2024.01.01 부터 2024.12.31 까지</P>"
    "<P>제 55 기 2023.01.01 부터 2023.12.31 까지</P>"
)


def test_dart_period_terms_rest_on_the_reports_own_declarations():
    """당기 is the cover's year; 전기 and each 제N기 exist only when declared with dates."""
    document = filing_document(registry="dart", fiscal_year=2024)

    terms = {term.term: term for term in dart_period_terms(DART_DECLARATIONS, document)}

    assert {name: term.fiscal_year for name, term in terms.items()} == {
        "당기": 2024,
        "제56기": 2024,
        "제55기": 2023,
        "전기": 2023,
    }
    cover = terms["당기"]
    assert DART_DECLARATIONS[cover.start_char : cover.end_char].startswith("사업연도")
    assert (cover.period_start, cover.period_end) == (date(2024, 1, 1), date(2024, 12, 31))
    assert dart_facts(DART_DECLARATIONS, document).period_terms == tuple(
        dart_period_terms(DART_DECLARATIONS, document)
    )


@pytest.mark.parametrize(
    "declarations",
    [
        # No cover: nothing anchors 당기, so no term is defined.
        "<P>제 56 기 2024.01.01 부터 2024.12.31 까지</P>",
        # A cover year that does not end on the report period.
        "<P>사업연도 2023년 01월 01일 부터 2023년 12월 31일 까지</P>",
        # Two different covers.
        "<P>사업연도 2024년 01월 01일 부터 2024년 12월 31일 까지</P>"
        "<P>사업연도 2024년 04월 01일 부터 2025년 03월 31일 까지</P>",
    ],
)
def test_dart_period_terms_need_one_cover_ending_on_the_report_period(declarations):
    """Without one cover year ending on the document's report period no word is defined."""
    document = filing_document(registry="dart", fiscal_year=2024)
    assert dart_period_terms(declarations, document) == ()


def test_an_ordinal_declared_with_two_periods_is_left_out():
    """제55기 stated as two different years defines neither, nor the 전기 it would give."""
    document = filing_document(registry="dart", fiscal_year=2024)
    declarations = DART_DECLARATIONS + "<P>제 55 기 2022.01.01 부터 2022.12.31 까지</P>"

    terms = {term.term for term in dart_period_terms(declarations, document)}

    assert terms == {"당기", "제56기"}


# A DART report's financial sections, as the report form codes and classes them.
DART_STATEMENTS = (
    '<SECTION-2><TITLE AASSOCNOTE="D-0-3-1-0">1. 요약재무정보</TITLE>'
    "<P>가. 요약연결재무정보</P><TABLE><TR><TD>1</TD></TR></TABLE>"
    "<P>나. 요약별도재무정보</P><TABLE><TR><TD>2</TD></TR></TABLE></SECTION-2>"
    '<SECTION-2><TITLE AASSOCNOTE="D-0-3-2-0">2. 연결재무제표</TITLE>'
    '<TABLE-GROUP ACLASS="{XBRL}IS2"><TABLE><TR><TD>3</TD></TR></TABLE></TABLE-GROUP>'
    "</SECTION-2>"
    '<SECTION-2><TITLE AASSOCNOTE="D-0-3-4-0">4. 재무제표</TITLE>'
    '<TABLE-GROUP ACLASS="{XBRL}BS_S"><TABLE><TR><TD>4</TD></TR></TABLE></TABLE-GROUP>'
    "</SECTION-2>"
    '<SECTION-2><TITLE AASSOCNOTE="D-0-3-5-0">5. 재무제표 주석</TITLE>'
    '<TABLE-GROUP ACLASS="{XBRL}NT_S_D851105"><TABLE><TR><TD>5</TD></TR></TABLE>'
    "</TABLE-GROUP></SECTION-2>"
)


def test_dart_statements_follow_section_codes_classes_and_summary_headings():
    """Each table position gets the sections, groups and summary headings around it."""
    facts = dart_facts(DART_STATEMENTS, filing_document(registry="dart"))

    def declared(text: str) -> list[tuple[object, object, str]]:
        """Return the kind, scope and basis declared around one table's cell text."""
        position = DART_STATEMENTS.index(f"<TD>{text}</TD>")
        return [(d.kind, d.scope, d.basis) for d in facts.declarations_at(position)]

    assert facts.scope_declared
    assert facts.statements == dart_statements(DART_STATEMENTS)
    assert declared("1") == [
        ("summary", None, "section D-0-3-1-0"),
        ("summary", "consolidated", "heading 요약연결재무정보"),
    ]
    assert declared("2")[1] == ("summary", "separate", "heading 요약별도재무정보")
    assert declared("3") == [
        ("statement", "consolidated", "section D-0-3-2-0"),
        ("income", None, "class {XBRL}IS2"),
    ]
    assert declared("4")[1] == ("balance_sheet", "separate", "class {XBRL}BS_S")
    assert declared("5") == [
        ("notes", "separate", "section D-0-3-5-0"),
        ("notes", "separate", "class {XBRL}NT_S_D851105"),
    ]


def summary_declarations(paragraphs: str) -> dict[str, list[tuple[object, object, str]]]:
    """Read a summary section's headings and return what each table's cell sees."""
    raw = (
        f'<SECTION-2><TITLE AASSOCNOTE="D-0-3-1-0">1. 요약재무정보</TITLE>{paragraphs}</SECTION-2>'
    )
    facts = dart_facts(raw, filing_document(registry="dart"))
    return {
        text: [
            (d.kind, d.scope, d.basis) for d in facts.declarations_at(raw.index(f"<TD>{text}</TD>"))
        ]
        for text in ("1", "2")
    }


def test_a_summary_heading_counts_only_as_a_whole_paragraph():
    """A paragraph only mentioning a heading declares nothing and ends the one before."""
    found = summary_declarations(
        "<P>가. 요약연결재무정보</P><TABLE><TR><TD>1</TD></TR></TABLE>"
        "<P>나. 요약별도재무정보 (연결 기준은 가. 요약연결재무정보 참조)</P>"
        "<TABLE><TR><TD>2</TD></TR></TABLE>"
    )
    assert found["1"][1] == ("summary", "consolidated", "heading 요약연결재무정보")
    assert found["2"] == [("summary", None, "section D-0-3-1-0")]


def test_a_summary_heading_may_sit_in_spans_and_line_breaks():
    """The report form's markup around a heading ("&cr;", spans, spaces) keeps it whole."""
    found = summary_declarations(
        '<P>\n<SPAN USERMARK=" B">가. 요약연결재무정보&cr;</SPAN>\n</P>'
        "<TABLE><TR><TD>1</TD></TR></TABLE>"
        '<P USERMARK=" B">\n<SPAN>&cr;&cr;</SPAN>\n<SPAN>나. 요약 별도재무정보</SPAN>\n</P>'
        "<TABLE><TR><TD>2</TD></TR></TABLE>"
    )
    assert found["1"][1] == ("summary", "consolidated", "heading 요약연결재무정보")
    assert found["2"][1] == ("summary", "separate", "heading 요약 별도재무정보")
