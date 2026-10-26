"""Answer figures checked against the period of the cited evidence."""

from dataclasses import asdict, replace
from decimal import Decimal

import pytest

from app.contracts.figures import (
    CellFact,
    EvidenceText,
    TableCellReading,
    check_figures,
    figures,
    interpret_table_cell,
    read_table_cells,
    read_table_unit,
)
from app.ingestion.chunking import Chunk, chunk_filing
from app.ingestion.parsing.models import Block
from tests.ingestion.chunk.support import build_filing

# AMD FY2024 consolidated statement of operations, as the filing lays it out: its note
# states a scale but no currency, and its cells carry only the ambiguous "$".
INCOME_TABLE = (
    "<table><tr><td>(In millions)</td><td>December 28, 2024</td>"
    "<td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 25,785</td><td>$ 22,680</td></tr>"
    "<tr><td>Net income</td><td>1,641</td><td>854</td></tr></table>"
)
# The same table with an explicit currency added to its note, for checks of other behavior.
USD_INCOME_TABLE = INCOME_TABLE.replace("(In millions)", "(In millions of U.S. dollars)")


def table_chunk(html: str = USD_INCOME_TABLE) -> Chunk:
    """Chunk one table through the real chunker."""
    block = Block("table", "", html=html, source_pos=0, end_pos=len(html))
    filing = build_filing([block])
    filing.source_length = len(html)
    (chunk,) = chunk_filing(filing)
    assert chunk.table_fragment is not None
    return chunk


def table_fragment(html: str = USD_INCOME_TABLE) -> dict:
    """Return one chunked table's fragment as the JSON a stored table rebuilds."""
    fragment = table_chunk(html).table_fragment
    assert fragment is not None
    return asdict(fragment)


def table_evidence(html: str = USD_INCOME_TABLE) -> EvidenceText:
    """Read one chunked table as cited evidence with its figure readings."""
    chunk = table_chunk(html)
    return EvidenceText(
        1, chunk.body, chunk.context_header, tuple(read_table_cells(table_fragment(html)))
    )


def prose_evidence(body: str) -> EvidenceText:
    """Read one narrative chunk as cited evidence."""
    return EvidenceText(2, body, "AMD FY2024 · Item 7")


@pytest.mark.parametrize(
    "answer",
    [
        "AMD's FY2024 total net revenue was **$25.8 billion**.",
        "AMD's FY2024 **total net revenue was $25,785 million** (approximately **$25.8 billion**).",
        "For the year ended December 28, 2024, AMD reported "
        "**Total net revenue of $25,785 million**.",
        "**AMD** reported **total net revenue** of **$25,785 million** in 2024.",
    ],
)
@pytest.mark.parametrize(
    ("html", "verdict"), [(INCOME_TABLE, "unit_unverified"), (USD_INCOME_TABLE, "verified")]
)
def test_bold_and_cited_issuer_subjects_preserve_financial_checks(answer, html, verdict):
    """Read the live-run wording while preserving the filed table's currency uncertainty."""
    evidence = replace(table_evidence(html), context_header="AMD FY2024 · Item 7")
    result = check_figures(answer, [evidence], [2024])
    assert result.verdict == verdict
    assert all(check.item == "revenue" for check in result.checks)


@pytest.mark.parametrize("issuer", ["NVDA", "Acme Holdings, Inc."])
def test_issuer_subject_is_taken_from_cited_context_not_a_company_allowlist(issuer):
    """Accept a complete multiword issuer subject, including its internal punctuation."""
    evidence = replace(table_evidence(), context_header=f"{issuer} FY2024 · Item 8")
    answer = f"In 2024, {issuer} reported **net revenue of $25,785 million**."
    assert check_figures(answer, [evidence], [2024]).verdict == "verified"


@pytest.mark.parametrize(
    ("answer", "verdict"),
    [
        ("AMD reported **net revenue of $99,999 million** in 2024.", "unverified"),
        ("AMD reported **net income of $25,785 million** in 2024.", "unverified"),
        ("AMD reported **adjusted net revenue of $25,785 million** in 2024.", "unverified"),
        ("AMD reported **segment revenue of $25,785 million** in 2024.", "unverified"),
        ("AMD reported **net revenue of 25,785 million EUR** in 2024.", "unverified"),
        ("AMD reported **net revenue of $22,680 million** in 2024.", "period_mismatch"),
        ("NVDA reported **net revenue of $25,785 million** in 2024.", "unverified"),
        ("XAMD reported **net revenue of $25,785 million** in 2024.", "unverified"),
        ("NVDA's AMD reported **net revenue of $25,785 million** in 2024.", "unverified"),
        ("2024 adjusted AMD net revenue was $25,785 million.", "unverified"),
        ("2024 net revenue attributable to AMD was $25,785 million.", "unverified"),
        ("2024 net revenue was **$25,785 million.", "unverified"),
        ("2024 net revenue was $25,785 million**.", "unverified"),
    ],
)
def test_presentation_normalization_keeps_wrong_or_qualified_claims_closed(answer, verdict):
    """Do not erase financial qualifiers, unknown subjects, bad values or unmatched markers."""
    evidence = replace(table_evidence(), context_header="AMD FY2024 · Item 7")
    assert check_figures(answer, [evidence], [2024]).verdict == verdict


def test_a_company_subject_cannot_borrow_values_across_mixed_issuer_evidence():
    """Mixed issuer contexts do not authorize stripping a company from a claim."""
    amd = replace(table_evidence(), context_header="AMD FY2024 · Item 7")
    nvda = replace(table_evidence(), chunk_id=2, context_header="NVDA FY2024 · Item 7")
    answer = "AMD reported **net revenue of $25,785 million** in 2024."
    assert check_figures(answer, [amd, nvda], [2024]).verdict == "unverified"
    assert (
        check_figures(answer, [replace(amd, context_header="unstructured")], [2024]).verdict
        == "unverified"
    )


def test_a_figure_from_the_requested_period_column_is_verified():
    """Accept 2024 revenue read from the December 28, 2024 column."""
    result = check_figures("2024 revenue was $25,785 million.", [table_evidence()], [2024])
    assert result.verdict == "verified"
    assert result.checks[0].evidenced_years == (2024,)


def test_a_figure_from_a_comparative_column_is_a_period_mismatch():
    """Reject 22,680 as 2024 revenue: the 10-K reports it in the 2023 column."""
    result = check_figures("2024 revenue was $22,680 million.", [table_evidence()], [2024])
    assert result.verdict == "period_mismatch"
    assert (result.checks[0].figure, result.checks[0].evidenced_years) == ("22,680", (2023,))


def test_a_figure_missing_from_the_evidence_is_unverified():
    """Reject a figure no cited cell or text states."""
    result = check_figures("2024 revenue was $26,000 million.", [table_evidence()], [2024])
    assert result.verdict == "unverified"


def test_without_a_requested_period_any_cited_figure_is_verified():
    """Check only presence when the question names no period."""
    result = check_figures("Revenue was $22,680 million.", [table_evidence()], [])
    assert result.verdict == "verified"


def test_a_prose_figure_cannot_prove_a_requested_period():
    """Refuse a running-text figure when the question asks for a period."""
    prose = prose_evidence("Net revenue increased 14% compared with the prior year.")
    assert check_figures("Revenue grew 14%.", [prose], [2024]).verdict == "unverified"
    assert check_figures("Revenue grew 14%.", [prose], []).verdict == "verified"


def test_losses_match_by_magnitude():
    """Match "a loss of 33" to a filing's parenthesized (33)."""
    html = USD_INCOME_TABLE.replace("854", "(33)")
    result = check_figures("The 2023 net loss was $33 million.", [table_evidence(html)], [2023])
    assert result.verdict == "verified"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Revenue was $25,785 million in fiscal 2024.", ("25,785",)),
        ("FY2024 Item 7 of the 10-K, Q4 results.", ()),
        ("As of December 28, 2024 and 2024.12.31, revenue was 1,641.", ("1,641",)),
        ("2024년 12월 31일 기준 매출은 25,785백만원, 1분기 제56기", ("25,785",)),
        ("영업이익률 14.5%", ("14.5",)),
        ("$25.8B and 25.8bn", ("25.8", "25.8")),
        ("3M and 10K filers, Series B, 5G", ()),
        ("Revenue was $25,785bil or 25.8x.", ("25,785", "25.8")),
        ("In 2024, revenue was 25,785, then 1,641.", ("25,785", "1,641")),
        ("Revenue was $99999xyz, $2024mn, $2024 million and 2024%.", ("99999",) + ("2024",) * 3),
        ("USD25,785, 25,785USD, ₩300, 300원 and 25 usd", ("25,785", "25,785", "300", "300", "25")),
    ],
)
def test_identifiers_dates_and_years_are_not_figures(text, expected):
    """Leave years, dates and identifiers out, but keep figures glued to unknown units."""
    assert figures(text) == expected


# A DART-style fragment: the unit is a caption, the year sits in the column header.
# 300,870,903 백만원 = 300.870903조원.
DART_FRAGMENT = {
    "caption_sources": [{"start_char": 0, "end_char": 20, "text": "(단위 : 백만원)"}],
    "header_cells": [
        {"row": 0, "column": 0, "text": "과목"},
        {"row": 0, "column": 1, "text": "제56기(2024년)"},
        {"row": 0, "column": 2, "text": "제55기(2023년)"},
    ],
    "cells": [
        {"sources": [{"row": 1, "column": 0, "text": "매출액"}]},
        {"sources": [{"row": 1, "column": 1, "text": "300,870,903"}]},
        {"sources": [{"row": 1, "column": 2, "text": "258,935,494"}]},
    ],
}


def dart_evidence(caption: str = "(단위 : 백만원)") -> EvidenceText:
    """Read the DART-style revenue fragment under one caption linked by its source span."""
    linked = {"start_char": 0, "end_char": 20, "text": caption}
    fragment = {**DART_FRAGMENT, "caption_sources": [linked]}
    return EvidenceText(
        9, "| 과목 | 2024 | 2023 |", "연결 손익계산서", tuple(read_table_cells(fragment))
    )


@pytest.mark.parametrize(
    "answer",
    [
        "매출액은 3,008,709억원이다.",
        "매출액은 300.9조원이다.",
        "매출액은 3,009천억원이다.",
        "매출액은 30,087,090천만원이다.",
        "매출액은 30,087백억원이다.",
        "매출액은 30,087,090,300만원이다.",
        "2024년 매출액은 300,870,903백만원이다.",
    ],
)
def test_korean_compound_scales_convert_to_the_table_unit(answer):
    """Compose 십/백/천 with 만/억/조 before comparing with the caption's 백만원."""
    assert check_figures(answer, [dart_evidence()], [2024]).verdict == "verified"


def test_a_wrong_korean_compound_scale_is_unverified():
    """Reject a 100x scale error in the same currency."""
    assert check_figures("매출액은 300,871천억원이다.", [dart_evidence()], [2024]).verdict == (
        "unverified"
    )


def test_an_amount_split_across_two_figures_is_withheld():
    """Withhold "300조 8,709억원": its first half states no currency of its own."""
    result = check_figures("매출액은 300조 8,709억원이다.", [dart_evidence()], [2024])
    assert [check.verdict for check in result.checks] == ["unit_unverified", "unverified"]
    assert result.verdict == "unit_unverified"


@pytest.mark.parametrize(
    ("answer", "verdict"),
    [
        ("2024 net revenue was $25.8bn.", "verified"),
        ("2024 net revenue was $25.8B.", "verified"),
        ("2024 net revenue was $25,785mn.", "verified"),
        ("2024 net revenue was $25,785M.", "verified"),
        ("2024 net revenue was $25,785bn.", "unverified"),
        ("2024 net revenue was $99,999mn.", "unverified"),
        ("2024 net revenue was $99.9B.", "unverified"),
        ("2024 net revenue was 25,785M.", "unverified"),
        ("2024 net revenue was $25,785bil.", "unverified"),
    ],
)
def test_a_unit_glued_to_a_figure_is_still_checked(answer, verdict):
    """Read glued scales; a glued unit that cannot be read never drops the figure."""
    assert check_figures(answer, [table_evidence()], [2024]).verdict == verdict


@pytest.mark.parametrize(
    ("figure", "verdict"),
    [
        ("$25,785 million", "verified"),
        ("$25.8 billion", "verified"),
        ("$25.785 billion", "verified"),
        ("$25,790 million", "unverified"),
        ("$25.77 billion", "unverified"),
        ("$25,785 billion", "unverified"),
        ("$25,785 thousand", "unverified"),
        ("$26 billion", "unverified"),
        ("$25.4 billion", "unverified"),
    ],
)
def test_rounding_allows_half_the_last_place_from_three_significant_digits(figure, verdict):
    """Accept a converted figure within half its last digit, but only with 3+ digits."""
    answer = f"2024 net revenue was {figure}."
    assert check_figures(answer, [table_evidence()], [2024]).verdict == verdict


@pytest.mark.parametrize(
    ("answer", "verdicts"),
    [
        (
            "Revenue was $25,785 million in 2024. Revenue was $25,785 billion in 2024.",
            ["verified", "unverified"],
        ),
        (
            "Revenue was $25,785 billion in 2024. Revenue was $25,785 million in 2024.",
            ["unverified", "verified"],
        ),
        (
            "Revenue was $25,785 million in 2024. Revenue was $25,785 million in 2024.",
            ["verified", "verified"],
        ),
        ("Revenue was not $25,785 billion but $25,785 million.", ["unverified", "unverified"]),
    ],
)
def test_each_occurrence_of_a_figure_keeps_its_own_unit(answer, verdicts):
    """Judge and report every occurrence on its own unit, even when the magnitude repeats."""
    result = check_figures(answer, [table_evidence()], [2024])
    assert [check.verdict for check in result.checks] == verdicts


def test_a_missing_unit_withholds_the_figure_instead_of_comparing_magnitudes():
    """Withhold a unitless answer or a unit-less table; digits that never agree still fail."""
    unitless = check_figures("2024 revenue was 25,785.", [table_evidence()], [2024])
    assert unitless.verdict == "unit_unverified"
    assert unitless.checks[0].evidenced_years == (2024,)
    bare = table_evidence(INCOME_TABLE.replace("(In millions)", "Line item"))
    for figure in ("$25,785 billion", "$25.8 billion", "$25,785", "$26,000 million", "$99,999mn"):
        answer = f"2024 net revenue was {figure}."
        assert check_figures(answer, [bare], [2024]).verdict == "unit_unverified", figure
    # With both units established a wrong value is still an ordinary rejection.
    wrong = check_figures("2024 net revenue was $99,999 million.", [table_evidence()], [2024])
    assert wrong.verdict == "unverified"


def test_the_same_answer_passes_once_the_evidence_states_its_unit():
    """Certify the withheld answer when the same table carries a matching unit note."""
    bare = table_evidence(INCOME_TABLE.replace("(In millions)", "Line item"))
    billions = table_evidence(
        INCOME_TABLE.replace("(In millions)", "(In billions of U.S. dollars)")
    )
    answer = "2024 net revenue was $25,785 billion."
    assert check_figures(answer, [bare], [2024]).verdict == "unit_unverified"
    assert check_figures(answer, [billions], [2024]).verdict == "verified"
    assert check_figures(answer, [table_evidence()], [2024]).verdict == "unverified"


def unit_fragment(*captions: dict, label: str = "Net revenue", value: str = "25,785"):
    """Read one 2024 row whose unit can only come from the given caption entries."""
    fragment = {
        "header_cells": [{"column": 1, "text": "2024"}],
        "caption_sources": list(captions),
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": label}]},
            {"sources": [{"row": 1, "column": 1, "text": value}]},
        ],
    }
    return EvidenceText(7, "", "", tuple(read_table_cells(fragment)))


def linked(text: str, start: int = 0) -> dict:
    """Build one caption the chunker linked to its table with a source span."""
    return {"start_char": start, "end_char": start + len(text), "text": text}


@pytest.mark.parametrize(
    ("captions", "verdict"),
    [
        ((linked("(In millions of U.S. dollars)"),), "verified"),
        ((linked("(단위 : 백만미국달러)"),), "verified"),
        ((linked("(In millions)"), linked("(Currency: USD)", 40)), "verified"),
        ((linked("(In millions)"), linked("(in millions of USD)", 40)), "verified"),
        ((linked("(In millions of U.S. dollars, except per share data)"),), "verified"),
        ((linked("(In thousands of U.S. dollars)"),), "unverified"),
        ((), "unit_unverified"),
        (({"text": "(In millions of U.S. dollars)"},), "unit_unverified"),
        ((linked("(단위 : 주)"),), "unit_unverified"),
        ((linked("(단위 : 천주)"),), "unit_unverified"),
        ((linked("(In millions)"), linked("(In thousands)", 40)), "unit_unverified"),
        ((linked("(Dollars in thousands, shares in millions)"),), "unit_unverified"),
        ((linked("(In millions, except net revenue in dollars)"),), "unit_unverified"),
        ((linked("(In millions) (Units: widgets)"),), "unit_unverified"),
        ((linked("(In millions) (in widgets)"),), "unit_unverified"),
        ((linked("(In millions)"), linked("(Units: widgets)", 40)), "unit_unverified"),
        ((linked("(Shares in millions)"),), "unit_unverified"),
        ((linked("(단위 : 백만달러, 천주, %)"),), "unit_unverified"),
        ((linked("(Currency: USD)"),), "unit_unverified"),
    ],
)
def test_the_table_unit_comes_only_from_agreeing_linked_notes(captions, verdict):
    """Certify only a readable, agreeing note tied to the table; withhold anything else."""
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [unit_fragment(*captions)], [2024]).verdict == verdict


@pytest.mark.parametrize(
    "captions",
    [
        (linked("(In millions)"),),
        (linked("(단위 : 백만달러)"),),
        (linked("(In millions)"), linked("(in millions)", 40)),
        (linked("(In millions, except per share data)"),),
        (linked("(Dollars in millions)"),),
    ],
)
def test_a_scale_note_without_an_explicit_currency_is_withheld(captions):
    """Withhold a "$" answer when the table states a scale but no unambiguous currency."""
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [unit_fragment(*captions)], [2024]).verdict == ("unit_unverified")


def test_a_context_header_unit_without_provenance_is_not_the_table_unit():
    """Ignore a unit written in the context header of a legacy fragment without captions."""
    legacy = unit_fragment()
    header = EvidenceText(7, "", "AMD FY2024 · (In millions of U.S. dollars)", legacy.table_cells)
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [header], [2024]).verdict == "unit_unverified"


def test_uncertain_units_never_become_a_period_mismatch_or_absence():
    """Withhold a figure whose only matching cell is unit-less, whatever its column year."""
    fragment = {
        "header_cells": [{"column": 1, "text": "2024"}, {"column": 2, "text": "2023"}],
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": "Net revenue"}]},
            {"sources": [{"row": 1, "column": 1, "text": "25,785"}]},
            {"sources": [{"row": 1, "column": 2, "text": "22,680"}]},
        ],
    }
    evidence = [EvidenceText(7, "", "", tuple(read_table_cells(fragment)))]
    for answer in ("2024 net revenue was $22,680 million.", "2024 net revenue was $1 million."):
        result = check_figures(answer, evidence, [2024])
        assert (result.verdict, result.checks[0].evidenced_years) == ("unit_unverified", (2024,))
    dated = check_figures("2023 net revenue was $22,680 million.", evidence, [2024])
    assert (dated.verdict, dated.checks[0].evidenced_years) == ("unit_unverified", (2023,))


def test_a_withheld_figure_holds_the_whole_answer_beside_a_wrong_one():
    """Withhold the whole answer instead of calling it absent while a unit is unresolved."""
    answer = "2024 net revenue was 25,785 and net revenue was $99,999 million."
    result = check_figures(answer, [table_evidence()], [2024])
    assert [check.verdict for check in result.checks] == ["unit_unverified", "unverified"]
    assert result.verdict == "unit_unverified"


def noted(
    note: str,
    label: str = "Net revenue",
    value: str = "25,785",
    currency: str | None = "(Currency: USD)",
) -> EvidenceText:
    """Read one 2024 row under a table whose own first header cell is ``note``.

    A separate header cell declares the currency, so the note under test decides only
    the scale; ``currency=None`` leaves the table without one.
    """
    headers = [
        {"row": 0, "column": 0, "text": note},
        {"row": 0, "column": 1, "text": "2024"},
    ]
    if currency is not None:
        headers.append({"row": 0, "column": 2, "text": currency})
    fragment = {
        "header_cells": headers,
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": label}]},
            {"sources": [{"row": 1, "column": 1, "text": value}]},
        ],
    }
    return EvidenceText(7, "", "", tuple(read_table_cells(fragment)))


@pytest.mark.parametrize(
    ("note", "verdict"),
    [
        ("(In millions)", "verified"),
        ("In millions", "verified"),
        ("(In millions, except per share data)", "verified"),
        ("(Dollars in millions, except per share amounts)", "verified"),
        ("(In millions, except net revenue in dollars)", "unit_unverified"),
        ("(In millions, except where noted)", "unit_unverified"),
        ("(In millions) (Units: widgets)", "unit_unverified"),
        ("(In millions) (in widgets)", "unit_unverified"),
        ("(Units: millions)", "verified"),
        ("(in widgets)", "unit_unverified"),
        ("Change in revenue", "unit_unverified"),
        ("(In millions) (단위 : %)", "unit_unverified"),
        ("(In millions) Units: widgets", "unit_unverified"),
        ("Units: widgets", "unit_unverified"),
        ("in widgets", "unit_unverified"),
        ("(단위 : 백만원) (단위 : 백만달러)", "unit_unverified"),
        ("(In millions of U.S. dollars) (단위 : 백만원)", "unit_unverified"),
        ("(Dollars in millions) (단위 : 백만달러)", "verified"),
        ("(In millions) (단위 : 백만달러)", "verified"),
        ("(In millions) (단위 : 백만원)", "unit_unverified"),
        ("Units: millions", "verified"),
    ],
)
def test_a_header_note_counts_only_with_its_whole_applicability(note, verdict):
    """Never let a recognized scale hide an exception or unit declaration it cannot read.

    A header that declares nothing ("Change in revenue") leaves the unit absent. A
    percentage note beside a monetary one, or notes declaring different currencies (the
    table's USD against 원), conflict; "$"/달러 notes agree with the table's USD.
    """
    result = check_figures("2024 net revenue was $25,785 million.", [noted(note)], [2024])
    assert result.verdict == verdict


def test_declarations_in_separate_header_cells_are_all_read():
    """Read an unparenthesized declaration in another header cell beside a known one."""
    for extra, verdict in (
        ("Units: widgets", "unit_unverified"),
        ("in widgets", "unit_unverified"),
        ("Change in revenue", "verified"),
        ("(단위 : %)", "unit_unverified"),
    ):
        fragment = {
            "header_cells": [
                {"row": 0, "column": 0, "text": "In millions"},
                {"row": 0, "column": 1, "text": "2024"},
                {"row": 0, "column": 2, "text": extra},
                {"row": 0, "column": 3, "text": "(USD)"},
            ],
            "cells": [
                {"sources": [{"row": 1, "column": 0, "text": "Net revenue"}]},
                {"sources": [{"row": 1, "column": 1, "text": "25,785"}]},
            ],
        }
        evidence = [EvidenceText(7, "", "", tuple(read_table_cells(fragment)))]
        answer = "2024 net revenue was $25,785 million."
        assert check_figures(answer, evidence, [2024]).verdict == verdict, extra


@pytest.mark.parametrize(
    ("note", "label", "value", "answer", "verdict"),
    [
        ("(In millions, except per share data)", "Earnings per share", "1.00", "$1.00", "verified"),
        (
            "(In millions, except per-share amounts)",
            "Earnings per share",
            "1.00",
            "$1.00",
            "verified",
        ),
        ("(In millions)", "Earnings per share", "1.00", "$1.00", "unit_unverified"),
        ("(In millions)", "Diluted earnings per share", "1.00", "$1.00 million", "unit_unverified"),
        ("(In dollars)", "Earnings per share", "1.00", "$1.00", "verified"),
        ("(In thousands)", "Earnings per share", "1.00", "$1.00", "unit_unverified"),
        ("", "Earnings per share", "1.00", "$1.00", "unit_unverified"),
        (
            "(In millions, except per share data)",
            "Earnings per share",
            "1.00",
            "₩1.00",
            "unverified",
        ),
    ],
)
def test_per_share_rows_use_plain_currency_only_when_the_note_says_so(
    note, label, value, answer, verdict
):
    """Read a per-share row as plain currency only under an explicit per-share exception.

    Otherwise a table in plain units certifies plain amounts, and a scaled table without
    the exception withholds every per-share claim, since its row unit is ambiguous. A
    per-share amount still needs the table's currency.
    """
    evidence = noted(note, label, value)
    claim = f"2024 {label.casefold()} was {answer}."
    assert check_figures(claim, [evidence], [2024]).verdict == verdict


@pytest.mark.parametrize(
    ("caption", "answer", "verdict"),
    [
        (
            "(In millions of U.S. dollars, except per share data)",
            "2024 diluted EPS was $1.00.",
            "verified",
        ),
        ("(In millions, except per share data)", "2024 diluted EPS was $1.00.", "unit_unverified"),
        (None, "2024 diluted EPS was $1.00.", "unit_unverified"),
        ("(단위 : 주)", "2024 diluted EPS was $1.00.", "unit_unverified"),
        ("(단위 : %)", "2024 diluted EPS was $1.00.", "unverified"),
        ("(단위 : 원)", "2024 diluted EPS was 1.00원.", "verified"),
    ],
)
def test_per_share_rows_need_a_monetary_table_note(caption, answer, verdict):
    """Read per-share rows as plain currency only under a readable monetary note.

    A percent-only note makes every cell a percentage, which a currency claim contradicts.
    """
    captions = (linked(caption),) if caption else ()
    evidence = unit_fragment(*captions, label="Diluted earnings per share", value="1.00")
    assert check_figures(answer, [evidence], [2024]).verdict == verdict


@pytest.mark.parametrize(
    ("caption", "value", "answer", "verdict"),
    [
        ("(단위 : %)", "14.5", "2024년 매출액은 14.5%이다.", "verified"),
        ("(단위 : %)", "14.5", "2024년 매출액은 14.5백만원이다.", "unverified"),
        ("(단위 : 백만원)", "14.5%", "2024년 매출액은 14.5%이다.", "verified"),
        (None, "14.5", "2024년 매출액은 14.5%이다.", "unit_unverified"),
        (None, "14.5%", "2024년 매출액은 14.5%이다.", "verified"),
        (None, "14.5%", "2024년 매출액은 14.6%이다.", "unverified"),
    ],
)
def test_percentages_compare_only_with_percentages(caption, value, answer, verdict):
    """Match a percent figure only with a percent cell or a percent-only table.

    Without any note, a bare cell may or may not be a percentage, so a percent claim
    against it is withheld rather than refuted. A percentage needs no currency.
    """
    captions = (linked(caption),) if caption else ()
    evidence = unit_fragment(*captions, label="매출액", value=value)
    assert check_figures(answer, [evidence], [2024]).verdict == verdict


def test_only_an_explicit_unit_note_sets_the_table_scale():
    """Read the scale from the 단위 note, never from other caption words such as 조정."""
    adjusted = dart_evidence("(조정 후, 단위 : 백만원)")
    assert check_figures("매출액은 300.9조원이다.", [adjusted], [2024]).verdict == "verified"
    unannotated = dart_evidence("(조정후)")
    for answer in ("매출액은 300.9조원이다.", "매출액은 300,870,903백만원이다."):
        assert check_figures(answer, [unannotated], [2024]).verdict == "unit_unverified"
    # No unit is guessed: even digits that agree with nothing are withheld, not refuted.
    assert check_figures("매출액은 999조원이다.", [unannotated], [2024]).verdict == (
        "unit_unverified"
    )


EPS_TABLE = (
    "<table><tr><td>(In millions of U.S. dollars, except per share data)</td>"
    "<td>December 28, 2024</td><td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 25,785</td><td>$ 22,680</td></tr>"
    "<tr><td>Earnings per share - diluted</td><td>$ 1.00</td><td>$ 0.53</td></tr></table>"
)


@pytest.mark.parametrize(
    ("answer", "verdict"),
    [
        ("2024 diluted earnings per share were $1.00.", "verified"),
        ("2024 diluted earnings per share were $1.00 million.", "unverified"),
        ("2024 basic earnings per share were $1.00.", "unverified"),
        ("2024 net revenue was $25.8 billion.", "verified"),
    ],
)
def test_per_share_rows_are_not_scaled_by_the_table_unit(answer, verdict):
    """Keep per-share rows in plain currency while other rows use the million note."""
    assert check_figures(answer, [table_evidence(EPS_TABLE)], [2024]).verdict == verdict


ROWS_TABLE = (
    "<table><tr><td>(In millions of U.S. dollars)</td><td>December 28, 2024</td>"
    "<td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 25,785</td><td>$ 22,680</td></tr>"
    "<tr><td>Gross margin</td><td>$ 25,785</td><td>$ 1,111</td></tr>"
    "<tr><td>Sales and marketing</td><td>$ 9,999</td><td>$ 2,222</td></tr>"
    "<tr><td>Other items</td><td>$ 777</td><td>$ 666</td></tr></table>"
)


@pytest.mark.parametrize(
    ("answer", "verdict"),
    [
        ("2024 gross margin was $25,785 million.", "verified"),
        ("2024 net revenues were $25,785 million.", "verified"),
        ("2024 sales and marketing expenses were $9,999 million.", "verified"),
        ("2024 net income was $25,785 million.", "unverified"),
        ("2024 sales were $9,999 million.", "unverified"),
        ("2024 wholesales were $9,999 million.", "unverified"),
        ("2024 other items were $777 million.", "unverified"),
        ("In 2024 it was $25,785 million.", "unverified"),
        ("2024 net revenue/gross margin was $25,785 million.", "unverified"),
    ],
)
def test_a_figure_must_match_a_cell_of_the_item_it_names(answer, verdict):
    """Verify only through the named item's row; unknown or ambiguous items fail."""
    assert check_figures(answer, [table_evidence(ROWS_TABLE)], [2024]).verdict == verdict


@pytest.mark.parametrize(
    "answer",
    [
        "AMD's 2024 net revenue was $25,785 million.",
        "2024 revenues were $25,785 million.",
        "In 2024, AMD's revenue was $25,785 million.",
        "2024 total revenue was $25.8 billion.",
        "2024 net sales were $25,785 million.",
        "2024년 매출은 25,785백만 달러다.",
        "2024년 매출액은 257.85억 달러다.",
    ],
)
def test_explicit_aliases_and_translations_name_the_revenue_row(answer):
    """Accept the listed English and Korean names for the Net revenue row."""
    assert check_figures(answer, [table_evidence()], [2024]).verdict == "verified"


def test_korean_items_never_equate_different_rows():
    """Reject DART revenue stated as operating income, or as an operating margin."""
    for answer in ("2024년 영업이익은 300,870,903백만원이다.", "2024년 매출액률은 300.9조원이다."):
        assert check_figures(answer, [dart_evidence()], [2024]).verdict == "unverified"


@pytest.mark.parametrize(
    ("answer", "verdicts"),
    [
        (
            "In 2024, net revenue was $25,785 million and net income was $1,641 million.",
            ["verified", "verified"],
        ),
        (
            "Net income was $1,641 million on net revenue of $25,785 million in 2024.",
            ["verified", "verified"],
        ),
        (
            "In 2024, net revenue was $1,641 million and net income was $25,785 million.",
            ["unverified", "unverified"],
        ),
        (
            "In 2024, net revenue was $25,785 million and net income was $25,785 million.",
            ["verified", "unverified"],
        ),
    ],
)
def test_every_figure_is_associated_with_its_own_item(answer, verdicts):
    """Bind each figure to the item of its own clause instead of any item in the answer."""
    result = check_figures(answer, [table_evidence()], [2024])
    assert [check.verdict for check in result.checks] == verdicts


# Each amount appears in two rows, under different years.
CROSSED_TABLE = (
    "<table><tr><td>(In millions of U.S. dollars)</td><td>December 28, 2024</td>"
    "<td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 400</td><td>$ 300</td></tr>"
    "<tr><td>Net income</td><td>$ 50</td><td>$ 400</td></tr></table>"
)


@pytest.mark.parametrize(
    ("answer", "verdict", "years"),
    [
        ("2024 net revenue was $400 million.", "verified", (2024,)),
        ("2024 net income was $400 million.", "period_mismatch", (2023,)),
        ("2024 net income was $300 million.", "unverified", ()),
        ("2024 net revenue was $50 million.", "unverified", ()),
    ],
)
def test_the_same_amount_in_other_rows_is_neither_proof_nor_a_period_mismatch(
    answer, verdict, years
):
    """Judge value and period inside the named item's row, never across rows."""
    (check,) = check_figures(answer, [table_evidence(CROSSED_TABLE)], [2024]).checks
    assert (check.verdict, check.evidenced_years) == (verdict, years)


def test_a_comparative_figure_dated_by_the_answer_is_verified_beside_the_requested_one():
    """Accept a correctly dated prior-year figure when the requested year is also confirmed."""
    answer = "2024 net revenue was $25,785 million, up from $22,680 million in 2023."
    result = check_figures(answer, [table_evidence()], [2024])
    assert [check.verdict for check in result.checks] == ["verified", "verified"]
    assert result.checks[1].evidenced_years == (2023,)


def test_a_parenthesized_comparative_year_dates_only_its_own_figure():
    """Read "(2023: $22,680 million)" as the 2023 figure, leaving 2024 revenue verified."""
    answer = "2024 net revenue was $25,785 million (2023: $22,680 million)."
    result = check_figures(answer, [table_evidence()], [2024])
    assert [(check.verdict, check.evidenced_years) for check in result.checks] == [
        ("verified", (2024,)),
        ("verified", (2023,)),
    ]


def test_an_answer_dated_only_outside_the_requested_period_is_a_period_mismatch():
    """Report a correct 2023 figure as another period when 2024 was asked."""
    result = check_figures("2023 net revenue was $22,680 million.", [table_evidence()], [2024])
    assert result.verdict == "period_mismatch"
    assert result.checks[0].evidenced_years == (2023,)


def test_a_figure_dated_by_the_answer_must_sit_in_that_year_column():
    """Refuse 2024 revenue stated as the 2023 figure even without a requested period."""
    result = check_figures("2023 net revenue was $25,785 million.", [table_evidence()], [])
    assert result.verdict == "period_mismatch"
    assert result.checks[0].evidenced_years == (2024,)


def test_prose_and_labels_must_name_the_same_item():
    """Refuse a running-text figure stated for a different item than the answer names."""
    prose = prose_evidence("Net income increased 14% compared with the prior year.")
    assert check_figures("Revenue grew 14%.", [prose], []).verdict == "unverified"
    labelled = EvidenceText(3, "Body text.", "Net revenue of US$25,785 million · Item 8", None)
    assert check_figures("Net revenue was $25.8 billion.", [labelled], []).verdict == "verified"
    assert check_figures("Net income was $25,785 million.", [labelled], []).verdict == (
        "unverified"
    )
    unitless = EvidenceText(3, "Body text.", "Net revenue of 25,785 · Item 8", None)
    assert check_figures("Net revenue was 25,785.", [unitless], []).verdict == "unit_unverified"


@pytest.mark.parametrize(
    ("answer", "requested"),
    [
        ("2024 net income was 25,785.", [2024]),
        ("Net income was 25,785.", [2024]),
        ("Net income was 25,785 in 2024.", []),
    ],
)
def test_labels_and_running_text_cannot_confirm_a_period(answer, requested):
    """Refuse non-cell evidence whenever a period is asked or stated, even for the same item."""
    labelled = EvidenceText(7, "Net income was 25,785.", "Net income of 25,785 in 2023")
    assert check_figures(answer, [labelled], requested).verdict == "unverified"


# A hand-written fragment: one 2024 column, a caption unit note and one labelled row.
def fragment_evidence(label: str = "Net revenue", value: str = "25,785") -> EvidenceText:
    """Read a minimal stored fragment whose single row carries ``label`` and ``value``."""
    fragment = {
        "header_cells": [{"column": 1, "text": "2024"}],
        "caption_sources": [linked("(in millions of U.S. dollars)")],
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": label}]},
            {"sources": [{"row": 1, "column": 1, "text": value}]},
        ],
    }
    return EvidenceText(7, "", "", tuple(read_table_cells(fragment)))


@pytest.mark.parametrize(
    "answer",
    [
        "2024 net revenue was $25,785 million and adjusted EBITDA was $25,785 million.",
        "2024 net revenue was $25,785 million and something else was $25,785 million.",
        "2024 net revenue was $25,785 million; adjusted EBITDA was $25,785 million.",
        "2024 net revenue was $25,785 million, while segment margin came to $25,785 million.",
    ],
)
def test_an_unknown_subject_never_borrows_an_item_named_earlier(answer):
    """Fail the second figure of an unknown subject instead of reading it as revenue."""
    result = check_figures(answer, [fragment_evidence()], [2024])
    assert result.verdict == "unverified"
    assert len(result.checks) == 2
    assert (result.checks[1].verdict, result.checks[1].item) == ("unverified", None)


def test_a_korean_unknown_subject_never_borrows_an_item_named_earlier():
    """Fail a Korean figure whose own subject is an unlisted metric."""
    answer = "2024년 매출액은 300,870,903백만원이고 조정 EBITDA는 300,870,903백만원이다."
    result = check_figures(answer, [dart_evidence()], [2024])
    assert [(check.verdict, check.item) for check in result.checks] == [
        ("verified", "revenue"),
        ("unverified", None),
    ]


@pytest.mark.parametrize(
    "answer",
    [
        "2024 operating revenue was $25,785 million.",
        "2024 revenue growth was $25,785 million.",
        "2024 adjusted net revenue was $25,785 million.",
        "2024 non-GAAP net revenue was $25,785 million.",
        "2024 data center segment revenue was $25,785 million.",
        "2024 net revenue was $25,785 million from the data center segment.",
        "2024 net revenue was 25,785%.",
        "2024 net revenue grew $25,785 million.",
        "2024 net revenue increased by $25,785 million.",
        "2024년 조정매출액은 25,785백만 달러다.",
        "2024년 매출액의 25,785백만 달러다.",
        "2024년 매출액은 25,785백만 달러 증가했다.",
    ],
)
def test_a_qualified_changed_or_ratio_claim_is_not_the_plain_item(answer):
    """Refuse an item phrase inside a wider qualified item, a change or a percentage."""
    assert check_figures(answer, [fragment_evidence()], [2024]).verdict == "unverified"


@pytest.mark.parametrize(
    ("label", "verdict"),
    [
        ("Net income", "verified"),
        ("Net income (loss)", "verified"),
        ("Net income (Note 7)", "verified"),
        ("Net income (attributable to noncontrolling interests)", "unverified"),
        ("Adjusted net income", "unverified"),
        ("Adjusted EBITDA (net income)", "unverified"),
        ("Net income attributable to AMD", "unverified"),
    ],
)
def test_a_row_label_keeps_its_qualifiers(label, verdict):
    """Normalize only explicit same-item qualifiers; any other qualifier is another row."""
    result = check_figures("2024 net income was $25,785 million.", [fragment_evidence(label)], [])
    assert result.verdict == verdict


@pytest.mark.parametrize(
    "answer",
    [
        "2024 net revenue was $99999xyz.",
        "2024 net revenue was $2024mn.",
        "2024 net revenue was $2024 million.",
        "2024 net revenue was $99999mn.",
        "2024 net revenue was $99999.",
    ],
)
def test_currency_and_unit_amounts_are_never_dropped(answer):
    """Keep invented currency or unit amounts as checks that fail, even when year-like."""
    result = check_figures(answer, [fragment_evidence()], [2024])
    assert len(result.checks) == 1
    assert result.verdict == "unverified"


@pytest.mark.parametrize(
    "answer",
    [
        "2024 net revenue was 99999xyz.",
        "2024 net revenue was 25785M.",
        "2024 net revenue was USD99999xyz.",
        "2024 net revenue was v25785.",
        "2024 net revenue was 25785mio.",
    ],
)
def test_digits_glued_to_unknown_letters_stay_a_failing_check(answer):
    """Keep any non-identifier digits touching letters as an unverified check."""
    result = check_figures(answer, [fragment_evidence()], [2024])
    assert len(result.checks) == 1
    assert (result.checks[0].verdict, result.verdict) == ("unverified", "unverified")


@pytest.mark.parametrize(
    "answer",
    [
        "2024 net revenue was $25,785 million and net revenue was 99999xyz.",
        "2024 net revenue was $25,785 million; net revenue was 25785M.",
        "2024 net revenue was USD25,785mn and net revenue was USD99999xyz.",
    ],
)
def test_a_valid_amount_does_not_cover_a_glued_bad_amount(answer):
    """Verify the readable clause and still fail the answer on the unreadable one."""
    result = check_figures(answer, [fragment_evidence()], [2024])
    assert [check.verdict for check in result.checks] == ["verified", "unverified"]
    assert result.verdict == "unverified"


def test_explicit_identifier_shapes_stay_out_of_the_check():
    """Leave 3M, 10K, 5G, Series B, ordinals and FY/Q/date/Item references out."""
    answer = (
        "In the 3rd year, 3M and 10K filers with 5G and Series B, per FY2024 Q4 "
        "Item 7 as of December 28, 2024, reported net revenue of $25,785 million."
    )
    assert figures(answer) == ("25,785",)


def test_an_ambiguously_dated_figure_is_unverified():
    """Refuse a figure its own words date to two years instead of using the requested one."""
    for answer in (
        "Net revenue was $25,785 million in 2024 and 2023.",
        "Net revenue for 2023 was $25,785 million in 2024.",
    ):
        result = check_figures(answer, [table_evidence()], [2024])
        assert result.verdict == "unverified", answer


def test_net_income_and_net_loss_name_a_net_income_loss_row():
    """Read "net income (loss)" in an answer as net income."""
    result = check_figures(
        "2024 net income (loss) was $25,785 million.", [fragment_evidence("Net loss")], [2024]
    )
    assert result.verdict == "verified"


def test_unverified_checks_name_the_item_they_were_read_for():
    """Expose the item each figure was associated with, or None when none was named."""
    result = check_figures(
        "2024 net income was $25,785 million; it was $7 million.", [table_evidence()], [2024]
    )
    assert [(check.figure, check.item) for check in result.checks] == [
        ("25,785", "net income"),
        ("7", None),
    ]


# Currency: every monetary claim must agree with an explicit currency of its own evidence.


def currency_table(note: str, cell: str = "25,785") -> EvidenceText:
    """Chunk a one-row 2024 revenue table whose note and data cell carry the given text."""
    html = (
        f"<table><tr><td>{note}</td><td>December 28, 2024</td></tr>"
        f"<tr><td>Net revenue</td><td>{cell}</td></tr></table>"
    )
    return table_evidence(html)


@pytest.mark.parametrize(
    ("note", "answer", "verdict"),
    [
        ("(In millions of U.S. dollars)", "US$25,785 million", "verified"),
        ("(In millions of U.S. dollars)", "25,785 million USD", "verified"),
        ("(In millions of U.S. dollars)", "25,785 million usd", "verified"),
        ("(In millions of U.S. dollars)", "USD 25.8 billion", "verified"),
        ("(In millions of U.S. dollars)", "25,785 million U.S. dollars", "verified"),
        ("(In millions of U.S. dollars)", "₩25,785 million", "unverified"),
        ("(In millions of U.S. dollars)", "25,785 million KRW", "unverified"),
        ("(In millions of U.S. dollars)", "₩25.8 billion", "unverified"),
        ("(In millions of U.S. dollars)", "€25,785 million", "unverified"),
        ("(In millions of U.S. dollars)", "£25,785 million", "unverified"),
        ("(In millions of U.S. dollars)", "C$25,785 million", "unverified"),
        ("(In millions of U.S. dollars)", "25,785 million Canadian dollars", "unverified"),
        ("(In millions of U.S. dollars)", "A$25,785 million", "unverified"),
        ("(In millions of U.S. dollars)", "25,785 million yen", "unverified"),
        ("(In millions of U.S. dollars)", "25,785 million", "unit_unverified"),
        ("(In millions of Korean won)", "25,785 million won", "verified"),
        ("(In millions of Korean won)", "₩25,785 million", "verified"),
        ("(In millions of Korean won)", "$25,785 million", "unverified"),
        ("(In millions of Korean won)", "US$25,785 million", "unverified"),
        ("(In millions of Canadian dollars)", "$25,785 million", "verified"),
        ("(In millions of Canadian dollars)", "US$25,785 million", "unverified"),
        ("(In millions of yen)", "¥25,785 million", "verified"),
        ("(In millions of yen)", "JPY 25,785 million", "verified"),
        ("(In millions of yen)", "CNY 25,785 million", "unverified"),
        ("(In millions of yuan)", "¥25,785 million", "verified"),
        ("(In millions of yuan)", "$25,785 million", "unverified"),
    ],
)
def test_a_claim_currency_must_match_its_explicit_source_currency(note, answer, verdict):
    """Certify only matching currencies; a different known currency is never converted."""
    claim = f"2024 net revenue was {answer}."
    assert check_figures(claim, [currency_table(note)], [2024]).verdict == verdict


@pytest.mark.parametrize(
    ("note", "cell", "answer", "verdict"),
    [
        ("(In millions)", "$ 25,785", "$25,785 million", "unit_unverified"),
        ("(In millions)", "$ 25,785", "US$25,785 million", "unit_unverified"),
        ("(In millions)", "$ 25,785", "€25,785 million", "unverified"),
        ("(In millions)", "¥ 25,785", "¥25,785 million", "unit_unverified"),
        ("(In millions)", "¥ 25,785", "JPY 25,785 million", "unit_unverified"),
        ("(In millions)", "¥ 25,785", "$25,785 million", "unverified"),
        ("(In millions)", "US$ 25,785", "$25,785 million", "verified"),
        ("(In millions)", "25,785 USD", "US$25,785 million", "verified"),
        ("(In millions of U.S. dollars)", "$ 25,785", "$25,785 million", "verified"),
        ("(In millions of U.S. dollars)", "₩ 25,785", "$25,785 million", "unit_unverified"),
        ("(In millions) (USD)", "25,785", "$25,785 million", "verified"),
        ("(USD)", "25,785", "$25,785 million", "unit_unverified"),
        ("(In millions) (In U.S. dollars)", "25,785", "$25,785 million", "verified"),
        ("(In U.S. dollars)", "25,785", "$25,785", "verified"),
        ("(In U.S. dollars)", "25,785", "$25,785 million", "unverified"),
    ],
)
def test_ambiguous_symbols_resolve_only_through_their_own_evidence(note, cell, answer, verdict):
    """Read "$"/"¥" as a currency only when the same cell or table names one explicitly.

    A currency-only note gives no scale, and "In U.S. dollars" states plain units only
    when no other note states a scale; conflicting explicit markers are withheld.
    """
    claim = f"2024 net revenue was {answer}."
    assert check_figures(claim, [currency_table(note, cell)], [2024]).verdict == verdict


@pytest.mark.parametrize(
    "answer",
    ["USD 25,785백만원", "US$25,785 million won", "₩25,785 million USD"],
)
def test_conflicting_currency_markers_on_one_claim_are_withheld(answer):
    """Never pick one of two currencies written with the same figure."""
    claim = f"2024 net revenue was {answer}."
    result = check_figures(claim, [currency_table("(In millions of U.S. dollars)")], [2024])
    assert result.checks[0].verdict in {"unit_unverified", "unverified"}
    assert result.verdict != "verified"


def test_cells_and_tables_never_lend_each_other_a_currency():
    """Withhold a "$" row even when another row or another cited table names USD."""
    rows = table_evidence(
        "<table><tr><td>(In millions)</td><td>December 28, 2024</td></tr>"
        "<tr><td>Net revenue</td><td>$ 25,785</td></tr>"
        "<tr><td>Net income</td><td>US$ 1,641</td></tr></table>"
    )
    assert check_figures("2024 net income was $1,641 million.", [rows], [2024]).verdict == (
        "verified"
    )
    assert check_figures("2024 net revenue was $25,785 million.", [rows], [2024]).verdict == (
        "unit_unverified"
    )
    other = currency_table("(In millions of U.S. dollars)", "$ 1")
    revenue_only_in_rows = check_figures(
        "2024 net revenue was $25,785 million.", [rows, other], [2024]
    )
    assert revenue_only_in_rows.verdict == "unit_unverified"


def test_prose_fallback_needs_the_same_currency():
    """Hold or refuse running-text figures whose currency is ambiguous or different."""
    dollars = EvidenceText(3, "Body text.", "Net revenue of $25,785 million · Item 8", None)
    assert check_figures("Net revenue was $25.8 billion.", [dollars], []).verdict == (
        "unit_unverified"
    )
    assert check_figures("Net revenue was €25.8 billion.", [dollars], []).verdict == "unverified"
    won = EvidenceText(3, "Body text.", "Net revenue of 25,785 million won · Item 8", None)
    assert check_figures("Net revenue was US$25,785 million.", [won], []).verdict == "unverified"
    assert check_figures("Net revenue was ₩25,785 million.", [won], []).verdict == "verified"


def test_the_amd_table_as_filed_is_withheld_until_its_currency_is_explicit():
    """Withhold AMD's "$"-only table; the same answer passes once the note names USD."""
    answer = "2024 net revenue was $25,785 million."
    as_filed = check_figures(answer, [table_evidence(INCOME_TABLE)], [2024])
    assert (as_filed.verdict, as_filed.checks[0].evidenced_years) == ("unit_unverified", (2024,))
    assert check_figures(answer, [table_evidence(USD_INCOME_TABLE)], [2024]).verdict == "verified"


def note_cell(note: str, cell: str) -> EvidenceText:
    """Read one 2024 "Net revenue" row under a header note, with the data cell as written."""
    fragment = {
        "header_cells": [
            {"row": 0, "column": 0, "text": note},
            {"row": 0, "column": 1, "text": "2024"},
        ],
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": "Net revenue"}]},
            {"sources": [{"row": 1, "column": 1, "text": cell}]},
        ],
    }
    return EvidenceText(7, "", "", tuple(read_table_cells(fragment)))


@pytest.mark.parametrize(
    ("note", "cell", "answer", "verdict"),
    [
        ("(단위 : 원)", "99", "USD 2024", "unverified"),
        ("(단위 : 원)", "99", "2024 USD", "unverified"),
        ("(단위 : 원)", "99", "2024원", "unverified"),
        ("(단위 : 원)", "99", "₹2024", "unit_unverified"),
        ("(단위 : 원)", "99", "INR 2024", "unit_unverified"),
        ("(단위 : 원)", "2,024", "2024원", "verified"),
        ("(단위 : 원)", "2,024", "2025원", "unverified"),
        ("(In millions of U.S. dollars)", "2,024", "USD 2024 million", "verified"),
    ],
)
def test_a_currency_bearing_year_like_amount_is_a_claim(note, cell, answer, verdict):
    """Keep "USD 2024", "2024원" or "₹2024" as an amount instead of reading it as a year."""
    claim = f"2024 net revenue was {answer}."
    result = check_figures(claim, [note_cell(note, cell)], [2024])
    assert len(result.checks) == 1
    assert result.verdict == verdict


@pytest.mark.parametrize(
    ("note", "cell", "answer"),
    [
        ("(In U.S. dollars)", "25", "BHD 2024"),
        ("(In U.S. dollars)", "25", "2024 OMR"),
        ("(In U.S. dollars)", "25", "bhd 2024"),
        ("(In U.S. dollars)", "25", "BHD 25"),
        ("(In U.S. dollars)", "25", "25 omr"),
        ("(In millions of U.S. dollars)", "25", "XQZ 25 million"),
        ("(In millions of U.S. dollars)", "BHD 25", "USD 25 million"),
        ("(In millions of U.S. dollars)", "25 omr", "USD 25 million"),
    ],
)
def test_an_unsupported_code_shaped_currency_is_held_not_dropped(note, cell, answer):
    """Keep an amount written with any unsupported three-letter code and withhold it."""
    claim = f"2024 net revenue was {answer}."
    result = check_figures(claim, [note_cell(note, cell)], [2024])
    assert len(result.checks) == 1
    assert result.verdict == "unit_unverified"


@pytest.mark.parametrize(
    ("note", "cell", "answer"),
    [
        ("(In U.S. dollars)", "25", "2024 net revenue was USD 25."),
        ("(In U.S. dollars)", "25", "In fiscal 2024 the net revenue was USD 25."),
        ("(In U.S. dollars)", "25", "As of Dec 31, 2024 the net revenue was USD 25."),
        ("(In U.S. dollars)", "25", "2024 and the net revenue was USD 25."),
        ("(단위 : 원)", "25", "2024 net revenue was 25원."),
    ],
)
def test_a_year_beside_ordinary_words_stays_period_context(note, cell, answer):
    """Read "2024 net", "2024 the" or a date as the period, not as an extra amount."""
    result = check_figures(answer, [note_cell(note, cell)], [2024])
    assert [(check.figure, check.verdict) for check in result.checks] == [("25", "verified")]
    assert result.checks[0].evidenced_years == (2024,)


def test_distinct_claims_keep_their_own_currency_codes():
    """Verify the USD claim and withhold the one written with an unsupported code."""
    evidence = [two_year_table("(In millions of U.S. dollars)")]
    answer = "2024 net revenue was USD 25 million and 2023 net revenue was BHD 22 million."
    result = check_figures(answer, evidence, [2024])
    assert [check.verdict for check in result.checks] == ["verified", "unit_unverified"]


def test_real_dates_and_period_references_stay_out_of_the_check():
    """Leave FY, quarter, Item and calendar dates out even beside currency words."""
    assert figures("FY2024 Q4 results in USD, Item 7, as of December 28, 2024 and 2024.") == ()


@pytest.mark.parametrize(
    ("note", "cell", "answer", "verdict"),
    [
        ("(In millions) (EUR)", "25", "USD EUR 25 million", "unit_unverified"),
        ("(In millions of U.S. dollars)", "25", "25 million USD KRW", "unit_unverified"),
        ("(In millions of U.S. dollars)", "25", "USD 25 million KRW", "unit_unverified"),
        ("(In millions of U.S. dollars)", "25", "US$25 million USD", "verified"),
        ("(In millions of U.S. dollars)", "25", "USD 25 million U.S. dollars", "verified"),
    ],
)
def test_every_currency_marker_attached_to_a_figure_is_read(note, cell, answer, verdict):
    """Read the whole run of markers before and after a figure; disagreeing ones withhold."""
    claim = f"2024 net revenue was {answer}."
    assert check_figures(claim, [note_cell(note, cell)], [2024]).verdict == verdict


def two_year_table(note: str = "(In millions)") -> EvidenceText:
    """Read a 2024/2023 revenue table under one note."""
    fragment = {
        "header_cells": [
            {"row": 0, "column": 0, "text": note},
            {"row": 0, "column": 1, "text": "2024"},
            {"row": 0, "column": 2, "text": "2023"},
        ],
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": "Net revenue"}]},
            {"sources": [{"row": 1, "column": 1, "text": "25"}]},
            {"sources": [{"row": 1, "column": 2, "text": "22"}]},
        ],
    }
    return EvidenceText(7, "", "", tuple(read_table_cells(fragment)))


def test_a_marker_between_two_figures_certifies_neither():
    """Withhold both figures when one currency marker could belong to either of them."""
    evidence = [two_year_table("(In millions of U.S. dollars)")]
    shared = check_figures(
        "2024 net revenue was 25 million USD 22 million in 2023.", evidence, [2024]
    )
    assert [check.verdict for check in shared.checks] == ["unit_unverified", "unit_unverified"]
    separate = check_figures(
        "2024 net revenue was 25 million USD, up from USD 22 million in 2023.", evidence, [2024]
    )
    assert [check.verdict for check in separate.checks] == ["verified", "verified"]


@pytest.mark.parametrize(
    ("cell", "answer", "verdict"),
    [
        ("25%", "USD 25%", "unit_unverified"),
        ("25%", "25% USD", "unit_unverified"),
        ("25%", "USD 25% KRW", "unit_unverified"),
        ("USD 25%", "25%", "unit_unverified"),
        ("25%", "25%", "verified"),
        ("25%", "26%", "unverified"),
    ],
)
def test_a_figure_stating_both_a_currency_and_a_percentage_is_withheld(cell, answer, verdict):
    """Never certify a percentage that also carries a currency, on either side."""
    claim = f"2024 net revenue was {answer}."
    assert check_figures(claim, [note_cell("(단위 : %)", cell)], [2024]).verdict == verdict


@pytest.mark.parametrize(
    ("cell", "verdict"),
    [
        ("NZ$25", "unit_unverified"),
        ("ZZ$25", "unit_unverified"),
        ("₹25", "unit_unverified"),
        ("INR 25", "unit_unverified"),
        ("25 NZD", "unit_unverified"),
        ("US$25", "verified"),
        ("$25", "verified"),
        ("25", "verified"),
        ("원가 25", "verified"),
    ],
)
def test_an_unsupported_cell_currency_is_never_replaced_by_the_table_currency(cell, verdict):
    """Hold a cell whose own currency is unknown; words beside the number name none."""
    answer = "2024 net revenue was USD 25 million."
    evidence = note_cell("(In millions of U.S. dollars)", cell)
    assert check_figures(answer, [evidence], [2024]).verdict == verdict


def test_table_readings_expose_each_figure_cell_with_its_resolved_unit():
    """Read the USD income table's figure cells with their coordinates, years and unit."""
    fragment = table_fragment()
    readings = {(cell.row, cell.column): cell for cell in read_table_cells(fragment)}
    revenue = next(
        cell for cell in readings.values() if cell.values == frozenset({Decimal("25785")})
    )
    assert revenue.years == frozenset({2024})
    assert revenue.scale == Decimal(1_000_000)
    assert revenue.item == "revenue"
    assert revenue.currency == "USD"
    assert revenue.percent is False
    assert read_table_unit(fragment).status == "known"


def test_table_readings_keep_an_ambiguous_dollar_unresolved():
    """Leave the "$" family unresolved when the note states a scale but no currency."""
    fragment = table_fragment(INCOME_TABLE)
    currencies = {cell.currency for cell in read_table_cells(fragment) if cell.item == "revenue"}
    assert currencies == {"$"}


def reading(**changes) -> TableCellReading:
    """Build one USD million revenue reading for FY2024, changed where a test says."""
    base = TableCellReading(
        1,
        1,
        frozenset({Decimal(1234)}),
        frozenset({2024}),
        Decimal(1_000_000),
        "revenue",
        False,
        "USD",
        False,
        "Net revenue",
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    ("text", "changes", "status", "value"),
    [
        ("1,234", {}, "known", Decimal(1234)),
        ("(1,234)", {}, "known", Decimal(-1234)),
        ("△1,234.50", {}, "known", Decimal("-1234.50")),
        ("▲1,234", {}, "conflicting", None),
        ("1,234", {"scale": None}, "scale_unknown", Decimal(1234)),
        ("1,234", {"percent": None}, "scale_unknown", Decimal(1234)),
        ("1,234", {"currency": "$"}, "currency_unconfirmed", Decimal(1234)),
        ("1,234", {"currency": None}, "currency_unconfirmed", Decimal(1234)),
        ("1,234", {"currency": "!"}, "conflicting", Decimal(1234)),
        ("1,234", {"years": frozenset()}, "period_unknown", Decimal(1234)),
        ("1,234", {"years": frozenset({2023, 2024})}, "period_unknown", Decimal(1234)),
        ("1,234", {"item": None}, "item_unknown", Decimal(1234)),
        ("1,234", {"measure": "other"}, "not_monetary", Decimal(1234)),
        ("1,234", {"scope": "axis=member"}, "scope_qualified", Decimal(1234)),
        ("1,234", {"scope": "axis=member", "years": frozenset()}, "period_unknown", Decimal(1234)),
        ("12.5%", {"percent": True, "scale": None, "currency": None}, "known", Decimal("12.5")),
    ],
)
def test_a_cell_is_known_only_when_every_fact_is_established(text, changes, status, value):
    """Keep sign and decimals, and name the first missing fact instead of guessing."""
    result = interpret_table_cell(text, [reading(**changes)])
    assert (result.status, result.value) == (status, value)


@pytest.mark.parametrize("text", ["", "  ", "—", "-", "– –"])
def test_a_blank_or_dash_cell_is_blank_not_zero(text):
    """Report an empty or dash-only cell as blank with no value."""
    result = interpret_table_cell(text, [])
    assert (result.status, result.value) == ("blank", None)


def test_a_cell_without_one_figure_is_not_selectable():
    """Keep labels unselectable and refuse a cell that states two figures."""
    assert interpret_table_cell("Net revenue", []).status == "not_numeric"
    assert interpret_table_cell("1,234 / 5,678", [reading()]).status == "conflicting"


def fact(**changes) -> CellFact:
    """Build one inline XBRL USD million revenue fact for FY2024, changed where asked."""
    base = CellFact("us-gaap:Revenues", 2024, (), "iso4217:USD", None, 6, "25,785")
    return replace(base, **changes)


def tagged_revenue(*facts: CellFact, html: str = INCOME_TABLE) -> TableCellReading:
    """Read the FY2024 revenue cell of a table with the given facts tagged on it."""
    readings = read_table_cells(table_fragment(html), {(1, 1): facts})
    return next(cell for cell in readings if (cell.row, cell.column) == (1, 1))


def test_an_inline_xbrl_amount_fixes_currency_scale_and_year():
    """The tag resolves the "$" the text leaves ambiguous, and the cell becomes known."""
    cell = tagged_revenue(fact())
    assert (cell.currency, cell.scale, cell.years, cell.percent) == (
        "USD",
        Decimal(1_000_000),
        frozenset({2024}),
        False,
    )
    assert (cell.basis, cell.measure, cell.scope, cell.overrides) == ("fact", "amount", None, ())
    assert interpret_table_cell("$ 25,785", [cell]).status == "known"


def test_a_tag_that_contradicts_the_text_overrides_it_and_says_so():
    """A tagged year or scale wins over the header and note, and the override is kept."""
    cell = tagged_revenue(fact(fiscal_year=2023, scale=3))
    assert (cell.years, cell.scale, cell.overrides) == (
        frozenset({2023}),
        Decimal(1000),
        ("year", "scale"),
    )


def test_a_per_share_tag_states_plain_currency_units():
    """USD per share at scale 0 is plain dollars even under an "(In millions)" note."""
    cell = tagged_revenue(fact(denominator="xbrli:shares", scale=0))
    assert (cell.measure, cell.scale, cell.currency, cell.overrides) == (
        "per_share",
        Decimal(1),
        "USD",
        ("scale",),
    )


def test_tagged_values_that_are_not_amounts_keep_the_text_unit():
    """Shares and ratios are not amounts; their text unit stays and they are not selectable."""
    text_cell = tagged_revenue()
    cell = tagged_revenue(fact(numerator="xbrli:shares"))
    assert (cell.measure, cell.scale, cell.currency) == ("other", text_cell.scale, "$")
    assert interpret_table_cell("$ 25,785", [cell]).status == "not_monetary"


def test_a_tagged_currency_still_conflicts_with_a_different_written_one():
    """A euro tag on a cell the note declares in U.S. dollars is a conflict, not a choice."""
    cell = tagged_revenue(fact(numerator="iso4217:EUR"), html=USD_INCOME_TABLE)
    assert interpret_table_cell("$ 25,785", [cell]).status == "conflicting"


@pytest.mark.parametrize(
    ("dimensions", "scope"),
    [
        ((), None),
        (
            (
                (
                    "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis",
                    "ifrs-full:ConsolidatedMember",
                ),
            ),
            None,
        ),
        (
            (
                (
                    "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis",
                    "ifrs-full:SeparateMember",
                ),
            ),
            "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis=ifrs-full:SeparateMember",
        ),
        (
            (("us-gaap:StatementBusinessSegmentsAxis", "amd:DataCenterMember"),),
            "us-gaap:StatementBusinessSegmentsAxis=amd:DataCenterMember",
        ),
    ],
)
def test_only_the_whole_entity_is_unscoped(dimensions, scope):
    """No dimension, or DART's consolidated statement, is the entity; anything else is a part."""
    assert tagged_revenue(fact(dimensions=dimensions)).scope == scope


def test_a_dart_tag_fixes_the_year_and_keeps_the_text_unit():
    """DART tags state no unit, so the note's currency and scale stay as read."""
    text_cell = tagged_revenue(html=USD_INCOME_TABLE)
    cell = tagged_revenue(fact(numerator=None, scale=None, fiscal_year=2024), html=USD_INCOME_TABLE)
    assert (cell.basis, cell.measure, cell.years) == ("fact", None, frozenset({2024}))
    assert (cell.scale, cell.currency) == (text_cell.scale, text_cell.currency)


def test_a_fact_applies_only_alone_and_on_the_same_number():
    """Two tags, or a tag showing another number, leave the cell to its text reading."""
    text_cell = tagged_revenue()
    assert tagged_revenue(fact(), fact()) == text_cell
    assert tagged_revenue(fact(text="22,680")) == text_cell


def test_a_dimensioned_cell_never_confirms_the_entity_item():
    """A segment's revenue under a "Net revenue" label is not the company's revenue."""
    html = USD_INCOME_TABLE
    chunk = table_chunk(html)
    readings = read_table_cells(
        table_fragment(html),
        {(1, 1): (fact(dimensions=(("us-gaap:StatementBusinessSegmentsAxis", "x:Member"),)),)},
    )
    evidence = EvidenceText(1, chunk.body, chunk.context_header, tuple(readings))
    answer = "AMD's FY2024 net revenue was $25,785 million."
    assert check_figures(answer, [evidence], [2024]).verdict != "verified"
    assert check_figures(answer, [table_evidence(html)], [2024]).verdict == "verified"


def term_years(header: str, terms: dict[str, int] | None = None) -> frozenset[int]:
    """Read the DART revenue cell's years under one header and the defined terms."""
    fragment = {
        **DART_FRAGMENT,
        "header_cells": [
            {"row": 0, "column": 0, "text": "과목"},
            {"row": 0, "column": 1, "text": header},
            {"row": 0, "column": 2, "text": "전기"},
        ],
    }
    terms = {"당기": 2024, "전기": 2023, "제56기": 2024} if terms is None else terms
    cell = next(c for c in read_table_cells(fragment, None, terms) if c.column == 1)
    return cell.years


@pytest.mark.parametrize(
    ("header", "years"),
    [
        ("당기", {2024}),
        ("당 기", {2024}),
        ("당기말", {2024}),
        ("제 56 기", {2024}),
        ("제56기말", {2024}),
        ("전기", {2023}),
        ("당기 금액", set()),
        ("제57기", set()),
        ("제56기(2024년)", {2024}),
    ],
)
def test_a_header_that_is_a_defined_period_word_dates_its_column(header, years):
    """Only a header that is the word alone names its year; a written year still wins."""
    assert term_years(header) == years


def test_period_words_mean_nothing_without_the_reports_definitions():
    """Without the document's declarations 당기 and 전기 date nothing."""
    assert term_years("당기", {}) == frozenset()
