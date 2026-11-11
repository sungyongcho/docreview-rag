"""Answer figures checked against the period of the cited table and text evidence."""

from dataclasses import replace

import pytest

from app.figures.answers import EvidenceText, check_figures
from app.figures.tables import read_table_cells
from app.figures.text import figures
from tests.figures.support import (
    CROSSED_TABLE,
    DART_FRAGMENT,
    EPS_TABLE,
    INCOME_TABLE,
    ROWS_TABLE,
    SPLIT_PERCENT_TABLE,
    USD_INCOME_TABLE,
    currency_table,
    dart_evidence,
    fact,
    fragment_evidence,
    linked,
    note_cell,
    noted,
    table_chunk,
    table_evidence,
    table_fragment,
    tagged_evidence,
    two_year_table,
    unit_fragment,
)


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


@pytest.mark.parametrize(
    ("answer", "verdict"),
    [
        ("The 2023 net loss was $33 million.", "verified"),
        ("The 2023 net income was -$33 million.", "verified"),
        ("The 2023 net income was $(33) million.", "verified"),
        ("The 2023 net income was $33 million.", "unverified"),
        ("The 2023 net income (loss) was $33 million.", "unverified"),
    ],
)
def test_losses_match_by_magnitude_and_direction(answer, verdict):
    """A loss phrase or a negative figure matches a filing's (33); a plain 33 does not."""
    html = USD_INCOME_TABLE.replace("854", "(33)")
    assert check_figures(answer, [table_evidence(html)], [2023]).verdict == verdict


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


def test_an_ambiguously_dated_figure_is_unverified():
    """Refuse a figure its own words date to two years instead of using the requested one."""
    for answer in (
        "Net revenue was $25,785 million in 2024 and 2023.",
        "Net revenue for 2023 was $25,785 million in 2024.",
    ):
        result = check_figures(answer, [table_evidence()], [2024])
        assert result.verdict == "unverified", answer


def test_net_income_and_net_loss_name_a_net_income_loss_row():
    """Read "net income (loss)" in an answer as net income, compared in its direction."""
    evidence = fragment_evidence("Net loss", "(25,785)")
    result = check_figures("2024 net income (loss) was $(25,785) million.", [evidence], [2024])
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


def test_the_amd_table_as_filed_is_withheld_until_its_currency_is_explicit():
    """Withhold AMD's "$"-only table; the same answer passes once the note names USD."""
    answer = "2024 net revenue was $25,785 million."
    as_filed = check_figures(answer, [table_evidence(INCOME_TABLE)], [2024])
    assert (as_filed.verdict, as_filed.checks[0].evidenced_years) == ("unit_unverified", (2024,))
    assert check_figures(answer, [table_evidence(USD_INCOME_TABLE)], [2024]).verdict == "verified"


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


@pytest.mark.parametrize(
    "answer",
    [
        "In Note 5, net revenue was $25,785 million in 2024.",
        "Net revenue (Note 5) was $25,785 million in 2024.",
        "Net revenue (Note 5) $25,785 million.",
        "Net revenue (Note 5) USD 25,785 million.",
        "Net revenue (Item 8) US$25,785 million.",
        "Net revenue Q4 $25,785 million.",
        "FY2024 net revenue (Note 12a): 25,785 million USD.",
        "매출액 (주 5) US$25,785 million.",
    ],
)
def test_a_single_note_reference_before_a_matching_amount_stays_verified(answer):
    """Read a reference or period as an identifier and check the amount written after it.

    A currency written before the amount belongs to the amount, not to the identifier.
    """
    result = check_figures(answer, [table_evidence()], [2024])
    assert [check.figure for check in result.checks] == ["25,785"]
    assert result.verdict == "verified"


@pytest.mark.parametrize(
    "label", ["매출액 (주29)", "매출액(주 5, 30)", "매출액 (주석 12)", "Revenue (Notes 2 and 3)"]
)
def test_a_note_reference_is_part_of_the_row_label_not_a_figure(label):
    """A label citing its notes still names its item, and its note numbers read as nothing."""
    fragment = {
        **DART_FRAGMENT,
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": label}]},
            *DART_FRAGMENT["cells"][1:],
        ],
    }
    readings = read_table_cells(fragment)
    assert {(cell.column, cell.item) for cell in readings} == {(1, "revenue"), (2, "revenue")}
    assert figures(label) == ()


@pytest.mark.parametrize(
    ("label", "item"),
    [
        *((shape, None) for shape in ("FY2024", "FY 24", "fy24", "Q4", "H1", "4Q", "1H")),
        *((shape, None) for shape in ("10-K", "20-F", "Item 7", "Item 1A", "Items 7 and 8")),
        *((shape, None) for shape in ("Note 5", "Notes 2 and 3", "Notes 4, 5 & 6")),
        *((shape, None) for shape in ("Section 13.1", "Exhibit 99.1", "Part 2")),
        *((shape, None) for shape in ("(주29)", "(주 5, 30)", "(주석 12)", "(주3~5)", "（주 7）")),
        *((shape, None) for shape in ("December 28, 2024", "Dec. 31 2024", "Jan 1, 2023")),
        *((shape, None) for shape in ("2024.12.31", "2024-12-31", "2024/12/31", "12/31/2024")),
        *((shape, None) for shape in ("2024년", "2024년 12월", "2024년 12월 31일", "12월 31일")),
        *((shape, None) for shape in ("1분기", "제56기", "제 56 기", "Net revenue FY2024")),
        ("Revenue (Note 5)", "revenue"),
        ("Revenue (Notes 2 and 3)", "revenue"),
        ("매출액 (주29)", "revenue"),
    ],
)
def test_every_identifier_shape_states_no_figure_and_stays_a_row_label(label, item):
    """An identifier or date is no figure, so a cell holding one is the row's label."""
    fragment = {
        **DART_FRAGMENT,
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": label}]},
            {"sources": [{"row": 1, "column": 1, "text": "300,870,903"}]},
        ],
    }
    readings = read_table_cells(fragment)
    assert figures(label) == ()
    assert [(cell.column, cell.row_label, cell.item) for cell in readings] == [(1, label, item)]


def checked(answer: str, evidence: EvidenceText, years: tuple[int, ...] = (2024,)) -> list[str]:
    """Return the verdict of each figure the answer states against one evidence chunk."""
    return [check.verdict for check in check_figures(answer, [evidence], list(years)).checks]


GLUED_FOOTNOTE_TABLE = USD_INCOME_TABLE.replace(
    "<td>$ 25,785</td>", "<td>$ 25,785<sup>1</sup></td>"
)


@pytest.mark.parametrize(
    ("answer", "verdicts"),
    [
        ("Gross margin was $72.7 million in 2024.", ["unit_unverified"]),
        ("Gross margin was 72.7 million U.S. dollars in 2024.", ["unit_unverified"]),
        ("Gross margin was 72.7% in 2024.", ["unit_unverified"]),
        ("Net revenue was $25,785 million in 2024.", ["verified"]),
    ],
)
def test_a_figure_beside_a_lone_percent_cell_confirms_no_claim(answer, verdicts):
    """NVDA's "72.7 | %" margin is withheld, never confirmed as an amount."""
    assert checked(answer, table_evidence(SPLIT_PERCENT_TABLE)) == verdicts


@pytest.mark.parametrize(
    ("answer", "years", "verdicts"),
    [
        ("Net revenue was $257,851 million in 2024.", (2024,), ["unverified"]),
        ("Net revenue was $25,785 million in 2024.", (2024,), ["unverified"]),
        ("Net revenue was $257,851 million.", (), ["unverified"]),
        ("Net income was $1,641 million in 2024.", (2024,), ["verified"]),
    ],
)
def test_a_figure_with_malformed_grouping_confirms_no_claim(answer, years, verdicts):
    """A glued footnote's "25,7851" states no amount, so nothing is verified against it."""
    assert checked(answer, table_evidence(GLUED_FOOTNOTE_TABLE), years) == verdicts


@pytest.mark.parametrize(
    ("answer", "verdicts"),
    [
        ("Net revenue was $25,785 million in 2024.", ["unverified"]),
        ("Net revenue was $99,999 million in 2024.", ["unverified"]),
        ("Net income was $1,641 million in 2024.", ["verified"]),
    ],
)
def test_a_cell_whose_tag_shows_another_number_confirms_no_claim(answer, verdicts):
    """Text and tag dispute the number, so neither reading verifies a claim."""
    evidence = tagged_evidence(USD_INCOME_TABLE, {(1, 1): (fact(text="99,999"),)})
    assert checked(answer, evidence) == verdicts


@pytest.mark.parametrize(
    ("html", "facts", "answer", "verdicts"),
    [
        (
            "<table><tr><td>(In millions of U.S. dollars)</td><td>2024</td></tr>"
            "<tr><td>Net revenue</td><td>25.8 billion</td></tr>"
            "<tr><td>Net income</td><td>1,641</td></tr></table>",
            None,
            "Net revenue was $25.8 million in 2024.",
            ["unit_unverified"],
        ),
        (
            "<table><tr><td>(In U.S. dollars)</td><td>2024</td></tr>"
            "<tr><td>Net revenue</td><td>25.8 billion</td></tr>"
            "<tr><td>Net income</td><td>1,641</td></tr></table>",
            {(1, 1): (fact(text="25.8", scale=6),)},
            "Net revenue was $25.8 million in 2024.",
            ["unit_unverified"],
        ),
        (
            "<table><tr><td>(In U.S. dollars)</td><td>2024</td></tr>"
            "<tr><td>Net revenue</td><td>25.8 billion</td></tr>"
            "<tr><td>Net income</td><td>1,641</td></tr></table>",
            None,
            "Net revenue was $25.8 billion in 2024.",
            ["verified"],
        ),
        (
            "<table><tr><td>(In millions of U.S. dollars)</td><td>2024</td></tr>"
            "<tr><td>Net revenue</td><td>25.8 billion</td></tr>"
            "<tr><td>Net income</td><td>1,641</td></tr></table>",
            None,
            "Net income was $1,641 million in 2024.",
            ["verified"],
        ),
    ],
)
def test_a_scale_word_against_the_cells_unit_confirms_no_claim(html, facts, answer, verdicts):
    """A billion written beside a millions unit, tagged or not, leaves the unit unknown."""
    evidence = table_evidence(html) if facts is None else tagged_evidence(html, facts)
    assert checked(answer, evidence) == verdicts


@pytest.mark.parametrize(
    "answer",
    [
        "Net loss was $1,641 million in 2024.",
        "Net income was $1,641 million in 2024.",
        "Net income was -$1,641 million in 2024.",
    ],
)
def test_a_cell_whose_direction_is_not_established_withholds_the_claim(answer):
    """ "Net loss | 1,641" states no sign, so no direction of 1,641 is confirmed."""
    html = USD_INCOME_TABLE.replace("Net income", "Net loss")
    assert checked(answer, table_evidence(html)) == ["unit_unverified"]
    triangle = USD_INCOME_TABLE.replace("<td>1,641</td>", "<td>▲1,641</td>")
    assert checked(answer, table_evidence(triangle)) == ["unit_unverified"]


@pytest.mark.parametrize(
    ("concept", "verdicts"),
    [
        ("us-gaap:BusinessAcquisitionsProFormaRevenue", ["unverified"]),
        ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", ["verified"]),
    ],
)
def test_a_tag_of_another_concept_confirms_no_claim_for_the_labels_item(concept, verdicts):
    """A pro forma revenue tag under "Net revenue" is not the entity's revenue."""
    evidence = tagged_evidence(USD_INCOME_TABLE, {(1, 1): (fact(concept=concept),)})
    assert checked("Net revenue was $25,785 million in 2024.", evidence) == verdicts


@pytest.mark.parametrize(
    "header",
    [
        "Twelve Weeks Ended December 28, 2024",
        "12 Weeks 2024",
        "16 Weeks Ended December 28, 2024",
        "H1 2024",
        "Half Year Ended June 30, 2024",
        "Half-year 2024",
        "YTD 2024",
        "Year-to-date December 28, 2024",
        "Interim period ended June 30, 2024",
        "Pro-forma 2024",
        "Proforma 2024",
        "Constant currency 2024",
        "Excluding Xilinx 2024",
        "Organic 2024",
        "Guidance 2024",
        "Outlook 2024",
        "Budget 2024",
        "Growth 2024",
        "Difference 2024",
        "2024 계획",
        "2024 목표",
    ],
)
def test_a_column_header_with_any_unknown_word_confirms_no_annual_amount(header):
    """Only a header wholly read as a full fiscal year dates and scopes untagged cells."""
    html = (
        "<table><tr><td>(In millions of U.S. dollars)</td><td>December 28, 2024</td>"
        f"<td>{header}</td></tr>"
        "<tr><td>Net revenue</td><td>25,785</td><td>27,000</td></tr></table>"
    )
    evidence = table_evidence(html)
    assert checked("FY2024 net revenue was $27,000 million.", evidence) == ["unverified"]
    assert checked("FY2024 net revenue was $25,785 million.", evidence) == ["verified"]


@pytest.mark.parametrize(
    ("answer", "gain", "loss"),
    [
        ("FY2024 net income was $1,641 million.", "verified", "unverified"),
        ("FY2024 net income was -$1,641 million.", "unverified", "verified"),
        ("FY2024 net income was $-1,641 million.", "unverified", "verified"),
        ("FY2024 net income was $(1,641) million.", "unverified", "verified"),
        ("FY2024 net income was ($1,641) million.", "unverified", "verified"),
        ("FY2024 net loss was $1,641 million.", "unverified", "verified"),
        ("FY2024 net loss was $(1,641) million.", "unverified", "verified"),
        ("FY2024 net income was ▲$1,641 million.", "unverified", "unverified"),
    ],
)
def test_a_claim_and_a_cell_must_agree_in_direction(answer, gain, loss):
    """Equal magnitudes in opposite directions never verify; a loss phrase states a loss."""
    loss_table = USD_INCOME_TABLE.replace("<td>1,641</td>", "<td>(1,641)</td>")
    assert checked(answer, table_evidence()) == [gain]
    assert checked(answer, table_evidence(loss_table)) == [loss]


@pytest.mark.parametrize(
    ("answer", "gain", "loss"),
    [
        ("2024년 영업이익은 1,234백만원이다.", "verified", "unverified"),
        ("2024년 영업손실은 1,234백만원이다.", "unverified", "verified"),
        ("2024년 영업이익은 △1,234백만원이다.", "unverified", "verified"),
        ("2024년 영업이익은 -1,234백만원이다.", "unverified", "verified"),
        ("2024년 영업이익은 1,234백만원 적자이다.", "unverified", "unverified"),
    ],
)
def test_korean_losses_agree_in_direction(answer, gain, loss):
    """영업손실 and △ state a loss; 적자 is not read, so its figure names no item."""
    for cell, expected in (("1,234", gain), ("△1,234", loss)):
        fragment = {
            **DART_FRAGMENT,
            "cells": [
                {"sources": [{"row": 1, "column": 0, "text": "영업이익(손실)"}]},
                {"sources": [{"row": 1, "column": 1, "text": cell}]},
            ],
        }
        evidence = EvidenceText(9, "", "연결 손익계산서", tuple(read_table_cells(fragment)))
        assert checked(answer, evidence) == [expected]


# A spanning header naming both years over leaf headers naming one each.
STACKED_YEARS_TABLE = (
    "<table><tr><td>(In millions of U.S. dollars)</td>"
    '<td colspan="2">Years Ended December 28, 2024 and December 30, 2023</td></tr>'
    "<tr><td></td><td>2024</td><td>2023</td></tr>"
    "<tr><td>Net revenue</td><td>25,785</td><td>22,680</td></tr></table>"
)


@pytest.mark.parametrize(
    ("answer", "verdicts"),
    [
        ("FY2024 net revenue was $22,680 million.", ["period_mismatch"]),
        ("FY2024 net revenue was $25,785 million.", ["verified"]),
        ("FY2023 net revenue was $22,680 million.", ["verified"]),
    ],
)
def test_a_leaf_year_header_narrows_a_spanning_two_year_header(answer, verdicts):
    """Each column of "Years Ended 2024 and 2023 | 2024, 2023" holds its own year."""
    assert checked(answer, table_evidence(STACKED_YEARS_TABLE), (2023, 2024)) == verdicts


@pytest.mark.parametrize(
    ("answer", "years", "verdicts"),
    [
        ("FY2024 net revenue was $48,465 million.", (2024,), ["unverified"]),
        ("FY2023 net revenue was $48,465 million.", (2023,), ["unverified"]),
        ("Net revenue was $48,465 million.", (2024,), ["unverified"]),
        ("FY2024 net revenue was $25,785 million.", (2024,), ["verified"]),
    ],
)
def test_a_column_of_several_years_confirms_no_one_year(answer, years, verdicts):
    """A cumulative "2023-2024" column is neither year's value, nor another period's."""
    fragment = {
        "header_cells": [
            {"row": 0, "column": 0, "text": "(In millions of U.S. dollars)"},
            {"row": 0, "column": 1, "text": "2024"},
            {"row": 0, "column": 2, "text": "2023-2024"},
        ],
        "cells": [
            {"sources": [{"row": 1, "column": 0, "text": "Net revenue"}]},
            {"sources": [{"row": 1, "column": 1, "text": "25,785"}]},
            {"sources": [{"row": 1, "column": 2, "text": "48,465"}]},
        ],
    }
    evidence = EvidenceText(7, "", "", tuple(read_table_cells(fragment)))
    assert {cell.years for cell in evidence.table_cells or ()} == {
        frozenset({2024}),
        frozenset({2023, 2024}),
    }
    assert checked(answer, evidence, years) == verdicts


def test_a_loss_stated_twice_is_still_a_loss():
    """A loss phrase with a negative figure ("net loss was -$1,641") states one loss.

    "net income was -$1,641" and "net loss was $(1,641)" read the same way.
    """
    loss_table = USD_INCOME_TABLE.replace("<td>1,641</td>", "<td>(1,641)</td>")
    for answer in (
        "Net loss was -$1,641 million in 2024.",
        "Net income was -$1,641 million in 2024.",
        "Net loss was $(1,641) million in 2024.",
        "Net loss was $1,641 million in 2024.",
    ):
        assert checked(answer, table_evidence(loss_table)) == ["verified"]
        assert checked(answer, table_evidence()) == ["unverified"]
