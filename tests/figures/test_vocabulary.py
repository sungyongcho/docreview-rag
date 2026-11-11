"""The financial items a question names, read with the closed answer vocabulary."""

import pytest

from app.figures.vocabulary import items_named

AMD = ("AMD", "Advanced Micro Devices")


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("TestCo FY2024 revenue?", {"revenue"}),
        ("삼성전자의 2024년 매출액은?", {"revenue"}),
        ("2024년 영업이익과 순이익은?", {"operating income", "net income"}),
        ("What were revenue and net income for fiscal 2024?", {"revenue", "net income"}),
        ("How much revenue did TestCo report in 2024?", {"revenue"}),
        ("In 2024, what was the company's cost of sales?", {"cost of revenue"}),
        (
            "What were diluted EPS and total assets in 2023?",
            {"diluted earnings per share", "total assets"},
        ),
        ("Revenue (in millions) for 2024?", {"revenue"}),
        ("2024년 매출원가는 얼마였나요?", {"cost of revenue"}),
        ("2024년 당기순이익은 얼마인가?", {"net income"}),
        ("What was revenue for the fiscal year ended December 31, 2024?", {"revenue"}),
        ("What was net income (loss) in 2024?", {"net income"}),
        ("What was consolidated revenue in 2024?", {"revenue"}),
        ("What was total net revenue in 2024?", {"revenue"}),
        ("What was total operating income in 2024?", {"operating income"}),
        ("연결 기준 매출액은?", {"revenue"}),
        ("2024년 연결기준 매출액은?", {"revenue"}),
        ("2024년 연결매출액은?", {"revenue"}),
        ("2024년 전체 매출은?", {"revenue"}),
        ("2024년 총 매출액은?", {"revenue"}),
        ("당사의 2024년 영업이익은?", {"operating income"}),
        ("회사의 2024년 순이익은?", {"net income"}),
    ],
)
def test_a_plain_question_names_its_items(question, expected):
    """Read the items of a question whose item phrases stand among known words."""
    assert items_named(question) == expected


@pytest.mark.parametrize(
    ("question", "issuers", "expected"),
    [
        ("What was AMD's net revenue in 2024?", AMD, {"revenue"}),
        ("AMD revenue in 2024?", AMD, {"revenue"}),
        ("What were the revenues of AMD in 2024?", AMD, {"revenue"}),
        ("What were Advanced Micro Devices' revenues?", AMD, {"revenue"}),
        ("What was amd’s net income in 2024?", AMD, {"net income"}),
        ("What were Apple Inc.'s net sales in 2024?", ("Apple Inc.", "Apple"), {"revenue"}),
        ("What were the revenues of TestCo in 2024?", ("TestCo",), {"revenue"}),
        ("삼성전자의 2024년 매출액은?", ("삼성전자",), {"revenue"}),
        ("삼성전자 매출액은?", ("삼성전자",), {"revenue"}),
        ("삼성전자의 매출액은?", ("삼성전자",), {"revenue"}),
        ("삼성전자는 2024년 영업이익이 얼마인가?", ("삼성전자",), {"operating income"}),
    ],
)
def test_a_named_issuer_does_not_qualify_the_item(question, issuers, expected):
    """Blank the question's own company, as a whole name, before reading its items."""
    assert items_named(question, issuers=issuers) == expected


@pytest.mark.parametrize(
    ("question", "issuers"),
    [
        ("What was AMD's Data Center revenue in 2024?", AMD),
        ("What was Data Center revenue in 2024?", AMD),
        ("What was AMD Data Center revenue in 2024?", AMD),
        ("What was revenue at AMD's Data Center segment?", AMD),
        ("What was AMD's US revenue in 2024?", AMD),
        ("What was Data Center revenue in 2024?", ("Data",)),
        ("What was Data Center revenue in 2024?", ("Center",)),
        ("What was US revenue in 2024?", ("US",)),
        ("What was operating revenue in 2024?", ("Revenue",)),
        ("What was revenue growth in 2024?", ("Total",)),
        ("What was AMDX revenue in 2024?", AMD),
        ("삼성전자의 DS 부문 매출액은?", ("삼성전자",)),
        ("삼성전자의 별도 기준 매출액은?", ("삼성전자",)),
        ("삼성전자의 매출액은?", ("삼성",)),
        ("별도 매출액은?", ("매출액",)),
    ],
)
def test_an_issuer_list_never_unlocks_a_qualifier(question, issuers):
    """Blank only whole issuer names that are not vocabulary words; qualifiers stay."""
    assert items_named(question, issuers=issuers) == frozenset()


@pytest.mark.parametrize(
    "question",
    [
        "What was AMD's Data Center revenue in 2024?",
        "What was deferred revenue in 2024?",
        "별도 기준 매출액은?",
        "DS 부문 매출액은?",
        "2024년 영업이익률은?",
        "2024년 법인세비용차감전순이익은?",
        "What was operating revenue in 2024?",
        "What was revenue growth in 2024?",
        "What was the gross margin percentage in 2024?",
        "What was gross margin % in 2024?",
        "What was revenue in China in 2024?",
        "What was Data Center's revenue in 2024?",
        "DS 부문의 매출액은?",
        "What was revenue at AMD's Data Center segment?",
        "What were total revenue and segment operating income in 2024?",
        "What were operating and net income in 2024?",
        "매출액 증가율은?",
        "매출액의 증가율은?",
        "What was Q4 revenue?",
        "What was revenue in segment 31?",
        "What was R&D expense ratio in 2024?",
        "What was the segment's revenue in 2024?",
        "What was Data's revenue in 2024?",
        "What was Segment's revenue in 2024?",
        "사업부문의 매출액은?",
        "What was US revenue in 2024?",
        "What was AMD's net revenue in 2024?",
        "AMD revenue in 2024?",
        "삼성전자의 매출액은?",
        "삼성전자 매출액은?",
    ],
)
def test_a_phrase_touched_by_a_qualifier_or_unknown_word_names_no_item(question):
    """Name no item when any item phrase stands next to a word outside the vocabulary.

    Without an issuer list, a company name is such a word too.
    """
    assert items_named(question) == frozenset()


def test_a_question_without_an_item_phrase_names_no_item():
    """Infer nothing from other words."""
    assert items_named("What did TestCo earn in 2024?") == frozenset()
    assert items_named("What did TestCo earn in 2024?", issuers=("TestCo",)) == frozenset()
