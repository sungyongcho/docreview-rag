"""Define financial item identity, phrases, accepted concepts and output labels once."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FinancialItem:
    """One canonical item shared by questions, row labels, answers and assembly."""

    key: str
    phrases: tuple[str, ...]
    concepts: frozenset[str]
    label_en: str
    label_ko: str


ITEMS: dict[str, FinancialItem] = {
    "revenue": FinancialItem(
        "revenue",
        (
            "revenue",
            "revenues",
            "net revenue",
            "net revenues",
            "total revenue",
            "total revenues",
            "total net revenue",
            "net sales",
            "sales",
            "매출액",
            "매출",
            "영업수익",
            "순매출",
            "순매출액",
        ),
        frozenset(
            [
                "Revenue",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "RevenueFromContractsWithCustomers",
                "Revenues",
                "SalesRevenueNet",
            ]
        ),
        "Net revenue",
        "매출",
    ),
    "cost of revenue": FinancialItem(
        "cost of revenue",
        ("cost of revenue", "cost of revenues", "cost of sales", "cost of goods sold", "매출원가"),
        frozenset(
            [
                "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
                "CostOfGoodsAndServicesSold",
                "CostOfGoodsSold",
                "CostOfRevenue",
                "CostOfSales",
            ]
        ),
        "cost of revenue",
        "매출원가",
    ),
    "gross profit": FinancialItem(
        "gross profit",
        ("gross profit", "gross margin", "매출총이익"),
        frozenset(["GrossProfit"]),
        "gross profit",
        "매출총이익",
    ),
    "operating income": FinancialItem(
        "operating income",
        (
            "operating income",
            "operating profit",
            "operating loss",
            "income from operations",
            "loss from operations",
            "영업이익",
            "영업손실",
        ),
        frozenset(["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"]),
        "operating income",
        "영업이익",
    ),
    "net income": FinancialItem(
        "net income",
        (
            "net income",
            "net earnings",
            "net profit",
            "net loss",
            "당기순이익",
            "순이익",
            "당기순손실",
            "순손실",
        ),
        frozenset(["NetIncomeLoss", "ProfitLoss"]),
        "Net income",
        "순이익",
    ),
    "earnings per share": FinancialItem(
        "earnings per share",
        ("earnings per share", "eps", "net income per share", "주당순이익"),
        frozenset(
            [
                "BasicAndDilutedEarningsLossPerShare",
                "BasicEarningsLossPerShare",
                "DilutedEarningsLossPerShare",
                "EarningsPerShareBasic",
                "EarningsPerShareBasicAndDiluted",
                "EarningsPerShareDiluted",
            ]
        ),
        "earnings per share",
        "주당순이익",
    ),
    "basic earnings per share": FinancialItem(
        "basic earnings per share",
        (
            "basic earnings per share",
            "basic eps",
            "basic net income per share",
            "earnings per share - basic",
            "net income per share - basic",
            "기본주당순이익",
        ),
        frozenset(
            [
                "BasicAndDilutedEarningsLossPerShare",
                "BasicEarningsLossPerShare",
                "EarningsPerShareBasic",
                "EarningsPerShareBasicAndDiluted",
            ]
        ),
        "basic earnings per share",
        "기본주당순이익",
    ),
    "diluted earnings per share": FinancialItem(
        "diluted earnings per share",
        (
            "diluted earnings per share",
            "diluted eps",
            "diluted net income per share",
            "earnings per share - diluted",
            "net income per share - diluted",
            "희석주당순이익",
        ),
        frozenset(
            [
                "BasicAndDilutedEarningsLossPerShare",
                "DilutedEarningsLossPerShare",
                "EarningsPerShareBasicAndDiluted",
                "EarningsPerShareDiluted",
            ]
        ),
        "diluted earnings per share",
        "희석주당순이익",
    ),
    "research and development": FinancialItem(
        "research and development",
        (
            "research and development",
            "research and development expense",
            "research and development expenses",
            "r&d",
            "연구개발비",
            "r&d expense",
            "r&d expenses",
        ),
        frozenset(
            [
                "ResearchAndDevelopmentExpense",
                "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
            ]
        ),
        "research and development",
        "연구개발비",
    ),
    "sales and marketing": FinancialItem(
        "sales and marketing",
        (
            "sales and marketing",
            "sales and marketing expense",
            "sales and marketing expenses",
            "selling and marketing",
            "판매마케팅비",
        ),
        frozenset(["SellingAndMarketingExpense"]),
        "sales and marketing",
        "판매마케팅비",
    ),
    "selling, general and administrative": FinancialItem(
        "selling, general and administrative",
        (
            "selling, general and administrative",
            "selling, general and administrative expense",
            "selling, general and administrative expenses",
            "sg&a",
            "판매비와관리비",
            "판관비",
        ),
        frozenset(["SellingGeneralAndAdministrativeExpense"]),
        "selling, general and administrative",
        "판매비와관리비",
    ),
    "income tax": FinancialItem(
        "income tax",
        ("income tax expense", "income taxes", "provision for income taxes", "법인세비용"),
        frozenset(["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"]),
        "income tax expense",
        "법인세비용",
    ),
    "accounts receivable": FinancialItem(
        "accounts receivable",
        ("accounts receivable", "trade receivables", "매출채권"),
        frozenset(
            [
                "AccountsReceivableNet",
                "AccountsReceivableNetCurrent",
                "CurrentTradeReceivables",
                "TradeReceivables",
            ]
        ),
        "accounts receivable",
        "매출채권",
    ),
    "total assets": FinancialItem(
        "total assets",
        ("total assets", "자산총계"),
        frozenset(["Assets"]),
        "total assets",
        "자산총계",
    ),
    "total liabilities": FinancialItem(
        "total liabilities",
        ("total liabilities", "부채총계"),
        frozenset(["Liabilities"]),
        "total liabilities",
        "부채총계",
    ),
    "total equity": FinancialItem(
        "total equity",
        ("total equity", "total stockholders' equity", "total shareholders' equity", "자본총계"),
        frozenset(
            [
                "Equity",
                "StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ]
        ),
        "total equity",
        "자본총계",
    ),
    "cash and cash equivalents": FinancialItem(
        "cash and cash equivalents",
        ("cash and cash equivalents", "현금및현금성자산"),
        frozenset(["CashAndCashEquivalents", "CashAndCashEquivalentsAtCarryingValue"]),
        "cash and cash equivalents",
        "현금및현금성자산",
    ),
}
