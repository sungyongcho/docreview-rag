"""Answer figures checked against the period of the cited evidence."""

from dataclasses import asdict

import pytest

from app.contracts.figures import EvidenceText, check_figures, figures
from app.ingestion.chunking import chunk_filing
from app.ingestion.parsing.models import Block
from tests.ingestion.chunk.support import build_filing

# AMD FY2024 consolidated statement of operations, as the filing lays it out.
INCOME_TABLE = (
    "<table><tr><td>(In millions)</td><td>December 28, 2024</td>"
    "<td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 25,785</td><td>$ 22,680</td></tr>"
    "<tr><td>Net income</td><td>1,641</td><td>854</td></tr></table>"
)


def table_evidence(html: str = INCOME_TABLE) -> EvidenceText:
    """Chunk one table through the real chunker and read it as cited evidence."""
    block = Block("table", "", html=html, source_pos=0, end_pos=len(html))
    filing = build_filing([block])
    filing.source_length = len(html)
    (chunk,) = chunk_filing(filing)
    assert chunk.table_fragment is not None
    return EvidenceText(1, chunk.body, chunk.context_header, asdict(chunk.table_fragment))


def prose_evidence(body: str) -> EvidenceText:
    """Read one narrative chunk as cited evidence."""
    return EvidenceText(2, body, "AMD FY2024 · Item 7")


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
    html = INCOME_TABLE.replace("854", "(33)")
    result = check_figures("The 2023 net loss was 33 million.", [table_evidence(html)], [2023])
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
    ],
)
def test_identifiers_dates_and_years_are_not_figures(text, expected):
    """Leave years, dates and identifiers out, but keep figures glued to unknown units."""
    assert figures(text) == expected


# A DART-style fragment: the unit is a caption, the year sits in the column header.
# 300,870,903 백만원 = 300.870903조원.
DART_FRAGMENT = {
    "caption_sources": [{"text": "(단위 : 백만원)"}],
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
    """Read the DART-style revenue fragment under one caption."""
    fragment = {**DART_FRAGMENT, "caption_sources": [{"text": caption}]}
    return EvidenceText(9, "| 과목 | 2024 | 2023 |", "연결 손익계산서", fragment)


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


@pytest.mark.parametrize(
    "answer",
    ["매출액은 300,871천억원이다.", "매출액은 300조 8,709억원이다."],
)
def test_a_wrong_or_split_korean_amount_is_unverified(answer):
    """Reject a 100x scale error and an amount split across two figures."""
    assert check_figures(answer, [dart_evidence()], [2024]).verdict == "unverified"


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
            "Revenue was 25,785 million in 2024. Revenue was 25,785 billion in 2024.",
            ["verified", "unverified"],
        ),
        (
            "Revenue was 25,785 billion in 2024. Revenue was 25,785 million in 2024.",
            ["unverified", "verified"],
        ),
        (
            "Revenue was 25,785 million in 2024. Revenue was 25,785 million in 2024.",
            ["verified", "verified"],
        ),
        ("Revenue was not 25,785 billion but 25,785 million.", ["unverified", "unverified"]),
    ],
)
def test_each_occurrence_of_a_figure_keeps_its_own_unit(answer, verdicts):
    """Judge and report every occurrence on its own unit, even when the magnitude repeats."""
    result = check_figures(answer, [table_evidence()], [2024])
    assert [check.verdict for check in result.checks] == verdicts


def test_without_both_units_the_magnitude_is_compared():
    """Compare magnitudes when the answer or the table states no unit."""
    bare = INCOME_TABLE.replace("(In millions)", "Line item")
    assert check_figures("2024 revenue was 25,785.", [table_evidence()], [2024]).verdict == (
        "verified"
    )
    for figure, verdict in (("$25,785 billion", "verified"), ("$25.8 billion", "unverified")):
        answer = f"2024 net revenue was {figure}."
        assert check_figures(answer, [table_evidence(bare)], [2024]).verdict == verdict


def test_only_an_explicit_unit_note_sets_the_table_scale():
    """Read the scale from the 단위 note, never from other caption words such as 조정."""
    adjusted = dart_evidence("(조정 후, 단위 : 백만원)")
    assert check_figures("매출액은 300.9조원이다.", [adjusted], [2024]).verdict == "verified"
    unannotated = dart_evidence("(조정후)")
    assert check_figures("매출액은 300.9조원이다.", [unannotated], [2024]).verdict == "unverified"
    plain = check_figures("매출액은 300,870,903백만원이다.", [unannotated], [2024])
    assert plain.verdict == "verified"


EPS_TABLE = (
    "<table><tr><td>(In millions, except per share data)</td><td>December 28, 2024</td>"
    "<td>December 30, 2023</td></tr>"
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
    "<table><tr><td>(In millions)</td><td>December 28, 2024</td><td>December 30, 2023</td></tr>"
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
    "<table><tr><td>(In millions)</td><td>December 28, 2024</td><td>December 30, 2023</td></tr>"
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
    labelled = EvidenceText(3, "Body text.", "Net revenue of 25,785 · Item 8", None)
    assert check_figures("Net revenue was 25,785.", [labelled], []).verdict == "verified"
    assert check_figures("Net income was 25,785.", [labelled], []).verdict == "unverified"


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
        "caption_sources": [{"text": "in millions"}],
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": label}]},
            {"sources": [{"row": 1, "column": 1, "text": value}]},
        ],
    }
    return EvidenceText(7, "", "", fragment)


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
