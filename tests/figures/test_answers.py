"""Answer figures checked against cited evidence."""

import pytest

from app.figures.answers import EvidenceText, check_figures
from tests.figures.support import prose_evidence


def test_a_prose_figure_cannot_prove_a_requested_period():
    """Refuse a running-text figure when the question asks for a period."""
    prose = prose_evidence("Net revenue increased 14% compared with the prior year.")
    assert check_figures("Revenue grew 14%.", [prose], [2024]).verdict == "unverified"
    assert check_figures("Revenue grew 14%.", [prose], []).verdict == "verified"


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
    assert check_figures("Net revenue was 25,785.", [unitless], []).verdict == "withheld"


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


def test_prose_fallback_needs_the_same_currency():
    """Hold or refuse running-text figures whose currency is ambiguous or different."""
    dollars = EvidenceText(3, "Body text.", "Net revenue of $25,785 million · Item 8", None)
    assert check_figures("Net revenue was $25.8 billion.", [dollars], []).verdict == ("withheld")
    assert check_figures("Net revenue was €25.8 billion.", [dollars], []).verdict == "unverified"
    won = EvidenceText(3, "Body text.", "Net revenue of 25,785 million won · Item 8", None)
    assert check_figures("Net revenue was US$25,785 million.", [won], []).verdict == "unverified"
    assert check_figures("Net revenue was ₩25,785 million.", [won], []).verdict == "verified"


@pytest.mark.parametrize(
    ("answer", "amount"),
    [
        ("As disclosed in Note 5, 99,999 million USD of revenue was recorded.", "99,999"),
        ("Revenue in Notes 2 and 99,999 million USD.", "99,999"),
        ("매출액 (주 5, 99999)백만원", "99999"),
    ],
)
def test_an_amount_after_a_note_reference_is_still_a_claim(answer, amount):
    """Check an amount written right after a note reference instead of dropping it."""
    result = check_figures(answer, [EvidenceText(1, "body", "ctx")], [2024])
    assert amount in {check.figure for check in result.checks}
    assert result.verdict != "verified"


@pytest.mark.parametrize(
    "lead",
    [
        "Net revenue was ",
        "Net revenue was Note ",
        "Net revenue was Item ",
        "Net revenue was Section ",
        "Net revenue was Exhibit ",
        "Net revenue was FY ",
        "Net revenue was Q",
        "Net revenue was H",
        "Net revenue (Note ",
        "Net revenue (Note 2: ",
        "Net revenue (consolidated ",
        "매출액은 ",
        "매출액 (주석 ",
        "매출액 (주 ",
        "매출액은 제 ",
        "매출액 (연결 ",
    ],
)
@pytest.mark.parametrize("amount", ["99,999", "99999", "25,785.5"])
@pytest.mark.parametrize("tail", ["", ")", " million.", "백만원", " 기", "-K", "th", "H"])
def test_an_amount_is_a_claim_wherever_an_identifier_number_could_stand(lead, amount, tail):
    """Never drop an amount-shaped number as an identifier, whatever is written around it."""
    result = check_figures(lead + amount + tail, [EvidenceText(1, "body", "ctx")], [2024])
    assert amount in {check.figure for check in result.checks}
    assert result.verdict != "verified"


@pytest.mark.parametrize(
    ("answer", "amount"),
    [
        ("Net revenue was Note 500 million.", "500"),
        ("Net revenue was Note 500 USD.", "500"),
        ("Net revenue was Note 5%.", "5"),
        ("Net revenue (Note 500) million was high.", "500"),
        ("Net revenue was Item 7 billion USD.", "7"),
        ("Net revenue was FY 24 million.", "24"),
        ("Net revenue was Q4 billion.", "4"),
        ("매출액 (주석 300)억원", "300"),
        ("매출액 (주석 300) 억 원이다", "300"),
        ("매출액은 Note 5 조원이다.", "5"),
        ("Net revenue was Note 26B.", "26"),
        ("Net revenue was Note 500M.", "500"),
        ("Net revenue was Note 500k.", "500"),
        ("Net revenue was 5Q million.", "5"),
        ("Net revenue was 3H billion.", "3"),
        ("Net revenue was 10-K million.", "10"),
    ],
)
def test_a_short_number_with_a_unit_is_an_amount_not_an_identifier(answer, amount):
    """Check a number of an identifier's shape once a unit is written after it."""
    result = check_figures(answer, [EvidenceText(1, "body", "ctx")], [2024])
    assert amount in {check.figure for check in result.checks}
    assert result.verdict != "verified"


@pytest.mark.parametrize(
    "answer",
    [
        "FY2024 원가율은 상승했다.",
        "Q4 조정 영업이익은 증가했다.",
        "FY24 만기 도래 차입금이 있다.",
        "Q4 불확실성이 커졌다 (주 29).",
        "Note 5 엔진 사업부 참조.",
        "FY2024 천천히 회복했다.",
    ],
)
def test_a_korean_word_after_an_identifier_is_not_its_unit(answer):
    """Keep an identifier when the next word only begins like a scale or a currency."""
    assert check_figures(answer, [EvidenceText(1, "body", "ctx")], [2024]).checks == ()


@pytest.mark.parametrize(
    "answer",
    ["Net revenue was Note 500.", "Net revenue was Note 5B.", "Net revenue was Note 500 mil."],
)
def test_a_short_reference_number_without_a_known_unit_stays_a_reference(answer):
    """Pin the boundary: a short number after a reference word, with no unit the reader
    knows, has the shape of a reference ("Item 9B"), not of an amount.
    """
    assert check_figures(answer, [EvidenceText(1, "body", "ctx")], [2024]).checks == ()


def test_cited_text_keeps_the_filing_rules_for_its_references():
    """Read a passage's note list as identifiers, so no note number becomes a fact."""
    listed = EvidenceText(3, "매출액 (주 5, 30) 300억원", "TestCo", None)
    assert check_figures("매출액은 300억원이다.", [listed], []).verdict == "verified"
    notes = EvidenceText(3, "Revenue (Notes 2 and 3).", "TestCo", None)
    assert check_figures("Revenue was 3.", [notes], []).verdict == "unverified"


@pytest.mark.parametrize(
    "answer", ["Net revenue was 26B in 2024.", "Net revenue was 99M.", "Net revenue was 3T."]
)
def test_a_bare_scale_letter_amount_fails_instead_of_dropping_out(answer):
    """Fail a number with a glued scale letter and no currency sign as unreadable."""
    result = check_figures(answer, [EvidenceText(1, "body", "ctx")], [2024])
    assert len(result.checks) == 1
    assert result.verdict == "unverified"


@pytest.mark.parametrize(
    "answer",
    [
        "As disclosed in Note 5 and Item 7A of the 10-K, net revenue grew.",
        "See Exhibit 99.1 and Section 13 of the FY2024 10K for the Q4 and 1H results.",
        "Net revenue grew in the 3rd quarter ended March 31, 2024 (2024-03-31, 3/31/2024).",
        "매출액은 제56기 3분기(2024년 9월 30일)에 증가했다 (주 29).",
        "5G revenue grew in FY24.",
        "See Item 9B and Item 1B of the 10-K; Item 7A and Note 12a describe risk.",
        "In 4Q and 1H, see Exhibit 10.25.",
    ],
)
def test_bounded_identifiers_and_dates_state_no_claim(answer):
    """Leave references, periods, form names, ordinals and dates out of the check."""
    assert check_figures(answer, [EvidenceText(1, "body", "ctx")], [2024]).checks == ()


def test_a_bare_calendar_year_is_a_date_until_something_marks_it_an_amount():
    """Pin the boundary: an unmarked 1900-2099 integer cannot be told from a year."""
    evidence = [EvidenceText(1, "body", "ctx")]
    assert check_figures("Net revenue was 2024.", evidence, [2024]).checks == ()
    for answer in ("Net revenue was 2,024.", "Net revenue was 2024 million.", "USD 2024."):
        assert check_figures(answer, evidence, [2024]).verdict != "verified"


def test_a_reported_figure_keeps_only_its_own_parentheses():
    """Report "(1,234)" as written and drop a parenthesis that belongs to the sentence."""
    evidence = [EvidenceText(1, "body", "ctx")]

    def reported(answer):
        return [check.figure for check in check_figures(answer, evidence, [2024]).checks]

    assert reported("Net loss was (1,234) million.") == ["(1,234)"]
    assert reported("Net revenue (99,999 million) was high.") == ["99,999"]
    assert reported("Net revenue (Note 2: 99,999) was reported.") == ["99,999"]


@pytest.mark.parametrize(
    ("body", "answer", "causes"),
    [
        ("Net revenue was $25,785 million.", "Net revenue was USD 25,785 million.", ("currency",)),
        ("Net revenue was 25,785.", "Net revenue was 25,785.", ("scale", "currency")),
        ("Net income was ▲1,641 million USD.", "Net income was USD 1,641 million.", ("direction",)),
        ("Net revenue was USD 25,785 million.", "Net revenue was USD 25,785 million.", ()),
        ("Net revenue was EUR 25,785 million.", "Net revenue was USD 25,785 million.", ()),
    ],
)
def test_narrative_comparisons_carry_only_the_uncertainty_they_detect(body, answer, causes):
    """Undated prose shares typed unit/direction causes without changing pass/refusal rules."""
    result = check_figures(answer, [prose_evidence(body)], [])
    assert result.causes == causes
    assert result.checks[0].causes == causes
    assert result.verdict == (
        "withheld" if causes else "verified" if "EUR" not in body else "unverified"
    )


def test_period_filtering_and_a_confirmed_match_do_not_inherit_other_cells_causes():
    """Only relevant uncertain comparisons contribute; a real match still wins."""
    from dataclasses import replace

    from tests.figures.support import table_evidence

    original = table_evidence()
    revenue = next(
        cell for cell in original.table_cells if cell.item == "revenue" and 2024 in cell.years
    )
    scale = replace(revenue, scale=None)
    other_currency = replace(revenue, years=frozenset({2023}), currency=None)
    evidence = replace(original, table_cells=(other_currency, scale))
    answer = "FY2024 net revenue was USD 25,785 million."
    held = check_figures(answer, [evidence], [2024])
    assert held.verdict == "withheld" and held.causes == ("scale",)
    confirmed = check_figures(
        answer, [replace(evidence, table_cells=(*evidence.table_cells, revenue))], [2024]
    )
    assert confirmed.verdict == "verified" and confirmed.causes == ()
