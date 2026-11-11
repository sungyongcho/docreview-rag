"""The financial items a question names, read with the closed answer vocabulary."""

import pytest

from app.figures.vocabulary import items_named

AMD = ("AMD", "Advanced Micro Devices")


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("2024년 영업이익과 순이익은?", {"operating income", "net income"}),
        ("What were revenue and net income for fiscal 2024?", {"revenue", "net income"}),
        ("How much revenue was reported in FY2024?", {"revenue"}),
        ("What was revenue in fiscal year 2024 and fiscal year 2023?", {"revenue"}),
        ("2024년도 매출액은 얼마인가요?", {"revenue"}),
        ("What was revenue in 2024? Thanks!", {"revenue"}),
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
        ("TestCo FY2024 revenue?", ("TestCo",), {"revenue"}),
        ("How much revenue did TestCo report in 2024?", ("TestCo",), {"revenue"}),
        ("What was AMD's 2024 revenue?", AMD, {"revenue"}),
        ("What was AMD's revenue for fiscal 2024?", AMD, {"revenue"}),
        ("삼성전자의 2024년 연결 기준 매출액은?", ("삼성전자",), {"revenue"}),
        ("What was AMD's annual revenue in 2024?", AMD, {"revenue"}),
        ("What was AMD's full-year 2024 revenue?", AMD, {"revenue"}),
        ("What was AMD's revenue for the year ended December 28, 2024?", AMD, {"revenue"}),
        ("삼성전자의 2024년 연간 매출액은?", ("삼성전자",), {"revenue"}),
        ("2024년 삼성전자 매출액은?", ("삼성전자",), {"revenue"}),
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
        ("Data Center 2024 revenue?", AMD),
        ("non-GAAP 2024 revenue?", AMD),
        ("segment 2024 revenue?", AMD),
        ("Q4 2024 revenue?", AMD),
        ("Xilinx 2024 revenue?", AMD),
        ("revenue in 2024 for Xilinx?", AMD),
        ("pro forma 2024 net income?", AMD),
        ("DS부문 2024년 매출액은?", ("삼성전자",)),
        ("4분기 2024년 매출액은?", ("삼성전자",)),
        ("What was AMD's Q4 2024 revenue?", AMD),
        ("How much revenue did the Data Center segment report in 2024?", AMD),
        ("Data Center: what was AMD's revenue in 2024?", AMD),
        ("What was AMD's 2024 revenue, excluding Xilinx?", AMD),
        ("What was AMD's revenue in 2024 in the Data Center segment?", AMD),
        ("삼성전자의 2024년 DS 부문 매출액은?", ("삼성전자",)),
        ("삼성전자의 2024년 별도 기준 매출액은?", ("삼성전자",)),
        ("What was AMD's revenue in the December 2024 quarter?", AMD),
        ("What was AMD's fourth-quarter 2024 revenue?", AMD),
        ("What was AMD's revenue in 2H 2024?", AMD),
        ("What was AMD's revenue in FY24?", AMD),
        ("What is AMD's revenue guidance for 2025?", AMD),
        ("What was AMD's GAAP revenue in 2024?", AMD),
        ("What was AMD's revenue in 2024 in the US?", AMD),
        ("삼성전자의 2024년 4Q 매출액은?", ("삼성전자",)),
        ("삼성전자의 2024년 3개월 매출액은?", ("삼성전자",)),
        ("삼성전자의 2024년 누적 매출액은?", ("삼성전자",)),
        ("삼성전자의 2024년 예상 매출액은?", ("삼성전자",)),
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
        "TestCo FY2024 revenue?",
        "삼성전자의 2024년 매출액은?",
        "How much revenue did TestCo report in 2024?",
        "Answer briefly. What was revenue in 2024?",
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


@pytest.mark.parametrize(
    "period",
    [
        *("Q1", "Q4", "1Q", "4Q", "first quarter", "second quarter", "third quarter"),
        *("fourth quarter", "quarterly", "H1", "H2", "first half", "second half"),
        *("half-year", "three months", "six months", "nine months", "interim", "YTD"),
    ],
)
def test_a_period_shorter_than_a_year_qualifies_the_item_in_english(period):
    """Name no item for a quarter or half anywhere in the sentence, with the issuer passed."""
    assert items_named(f"What was AMD's {period} 2024 revenue?", issuers=AMD) == frozenset()
    assert items_named(f"What was AMD's 2024 revenue for the {period}?", issuers=AMD) == (
        frozenset()
    )


@pytest.mark.parametrize("period", ["1분기", "4분기", "분기", "상반기", "하반기", "반기"])
def test_a_period_shorter_than_a_year_qualifies_the_item_in_korean(period):
    """Name no item for a Korean quarter or half anywhere in the sentence."""
    assert items_named(f"삼성전자의 2024년 {period} 매출액은?", issuers=("삼성전자",)) == (
        frozenset()
    )
    assert items_named(
        f"삼성전자의 {period} 매출액은 2024년에 얼마였나?", issuers=("삼성전자",)
    ) == (frozenset())


def test_a_qualifier_in_another_question_sentence_is_not_read():
    """State the boundary: a sentence ending in "?" or "!" is read on its own."""
    assert items_named("Data Center grew! What was revenue in 2024?") == {"revenue"}
    assert items_named("What was revenue in 2024? And Data Center revenue?") == frozenset()


TESTCO = ("TEST", "TestCo")
NVIDIA = ("NVDA", "NVIDIA", "엔비디아")
HYNIX = ("000660", "SK hynix", "SK하이닉스")


@pytest.mark.parametrize(
    ("question", "issuers", "expected"),
    [
        ("TestCo (2024) 매출 근거를 찾아줘", TESTCO, {"revenue"}),
        ("TestCo 매출 근거를 찾아줘", TESTCO, {"revenue"}),
        ("2024년 AMD 순매출을 근거와 함께 알려줘", AMD, {"revenue"}),
        ("AMD 2024 net revenue는 몇 USD million인가?", AMD, {"revenue"}),
        ("TestCo의 FY2024 매출은?", TESTCO, {"revenue"}),
        (
            "AMD FY2023의 research and development expense는 얼마인가요?",
            AMD,
            {"research and development"},
        ),
        (
            "NVIDIA FY2024 revenue와 net income은 각각 얼마인가요?",
            NVIDIA,
            {
                "revenue",
                "net income",
            },
        ),
        (
            "2024 회계연도 엔비디아의 매출과 순이익은 각각 얼마였습니까?",
            NVIDIA,
            {
                "revenue",
                "net income",
            },
        ),
        ("What was NVIDIA's R&D expense in fiscal 2022?", NVIDIA, {"research and development"}),
        ("Find the evidence for TestCo's 2024 revenue.", TESTCO, {"revenue"}),
        ("Show me AMD's 2024 revenue with citations, please.", AMD, {"revenue"}),
        ("What was AMD's 2024 revenue in millions of dollars?", AMD, {"revenue"}),
        ("SK하이닉스의 2024년 매출액은 몇 백만원인가요?", HYNIX, {"revenue"}),
        ("SK하이닉스 2024년 영업이익을 출처와 함께 보여주세요.", HYNIX, {"operating income"}),
    ],
)
def test_a_question_asking_to_be_told_or_shown_in_a_unit_names_its_item(
    question, issuers, expected
):
    """Read request, citation and answer-unit words, glued particles and synonyms as plain."""
    assert items_named(question, issuers=issuers) == expected


@pytest.mark.parametrize(
    ("question", "issuers"),
    [
        ("How did AMD's gross margin percentage change from fiscal 2018 to fiscal 2019?", AMD),
        ("In fiscal 2022, how did AMD's Data Center net revenue compare with Client?", AMD),
        (
            "2022 회계연도에 AMD의 Data Center 부문 순매출은 "
            "Client 부문 순매출과 비교해 어떠했습니까?",
            AMD,
        ),
        (
            "엔비디아의 매출과 매출총이익률은 2019 회계연도에서 "
            "2020 회계연도까지 어떻게 변화했습니까?",
            NVIDIA,
        ),
        ("NVIDIA FY2022 R&D expense와 FY2021 대비 증가액을 알려주세요.", NVIDIA),
        ("What was SK hynix's consolidated revenue in 2024, and how does it compare?", HYNIX),
        ("SK하이닉스가 제시한 2025 회계연도 매출 가이던스는 얼마인가요?", HYNIX),
        ("Roughly what share of SK hynix's revenue arises in US dollars?", HYNIX),
        ("2024년 매출에서 DX 부문과 DS 부문 중 어느 쪽 비중이 더 크고, 각각 얼마였나요?", HYNIX),
        ("올해 매출은 전년 대비 얼마나 늘었나", ()),
        ("What drove NVIDIA data center revenue growth?", NVIDIA),
        ("What was AMD's USD revenue in 2024?", AMD),
        ("In millions, what was AMD's 2024 revenue?", AMD),
        ("SK하이닉스의 달러 매출액은?", HYNIX),
        ("2024년 AMD 순매출 증가율을 알려줘", AMD),
        ("AMD 2024 Data Center revenue는 몇 USD million인가?", AMD),
    ],
)
def test_a_real_question_with_a_qualifier_still_names_no_item(question, issuers):
    """Keep comparison, growth, ratio, segment, guidance and unit-first questions unread."""
    assert items_named(question, issuers=issuers) == frozenset()
