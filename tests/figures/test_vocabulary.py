"""The financial items a question names, read with the closed answer vocabulary."""

import pytest

from app.figures.vocabulary import items_named


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What was AMD's net revenue in 2024?", {"revenue"}),
        ("TestCo FY2024 revenue?", {"revenue"}),
        ("삼성전자의 2024년 매출액은?", {"revenue"}),
        ("2024년 영업이익과 순이익은?", {"operating income", "net income"}),
        ("What were revenue and net income for fiscal 2024?", {"revenue", "net income"}),
        ("How much revenue did TestCo report in 2024?", {"revenue"}),
        ("In 2024, what was the company's cost of sales?", {"cost of revenue"}),
        (
            "What were diluted EPS and total assets in 2023?",
            {
                "diluted earnings per share",
                "total assets",
            },
        ),
        ("Revenue (in millions) for 2024?", {"revenue"}),
        ("2024년 매출원가는 얼마였나요?", {"cost of revenue"}),
        ("2024년 당기순이익은 얼마인가?", {"net income"}),
        ("What was revenue for the fiscal year ended December 31, 2024?", {"revenue"}),
        ("What was net income (loss) in 2024?", {"net income"}),
    ],
)
def test_a_plain_question_names_its_items(question, expected):
    """Read the items of a question whose item phrases stand among known words."""
    assert items_named(question) == expected


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
    ],
)
def test_a_phrase_touched_by_a_qualifier_or_unknown_word_names_no_item(question):
    """Name no item at all when any item phrase stands next to a word outside the vocabulary."""
    assert items_named(question) == frozenset()


def test_a_question_without_an_item_phrase_names_no_item():
    """Infer nothing from other words."""
    assert items_named("What did TestCo earn in 2024?") == frozenset()
