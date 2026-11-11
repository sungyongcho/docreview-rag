"""Shared tables, evidence builders and readings for the figures tests."""

from dataclasses import asdict, replace
from decimal import Decimal

from app.figures.answers import EvidenceText
from app.figures.tables import CellFact, TableCellReading, TableStatement, read_table_cells
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


# NVDA's layout: the percent sign of a margin sits in a source cell of its own.
SPLIT_PERCENT_TABLE = (
    '<table><tr><td>(In millions of U.S. dollars)</td><td colspan="2">2024</td></tr>'
    "<tr><td>Net revenue</td><td>25,785</td><td></td></tr>"
    "<tr><td>Gross margin</td><td>72.7</td><td>%</td></tr></table>"
)


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


EPS_TABLE = (
    "<table><tr><td>(In millions of U.S. dollars, except per share data)</td>"
    "<td>December 28, 2024</td><td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 25,785</td><td>$ 22,680</td></tr>"
    "<tr><td>Earnings per share - diluted</td><td>$ 1.00</td><td>$ 0.53</td></tr></table>"
)


ROWS_TABLE = (
    "<table><tr><td>(In millions of U.S. dollars)</td><td>December 28, 2024</td>"
    "<td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 25,785</td><td>$ 22,680</td></tr>"
    "<tr><td>Gross margin</td><td>$ 25,785</td><td>$ 1,111</td></tr>"
    "<tr><td>Sales and marketing</td><td>$ 9,999</td><td>$ 2,222</td></tr>"
    "<tr><td>Other items</td><td>$ 777</td><td>$ 666</td></tr></table>"
)


# Each amount appears in two rows, under different years.
CROSSED_TABLE = (
    "<table><tr><td>(In millions of U.S. dollars)</td><td>December 28, 2024</td>"
    "<td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 400</td><td>$ 300</td></tr>"
    "<tr><td>Net income</td><td>$ 50</td><td>$ 400</td></tr></table>"
)


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


def currency_table(note: str, cell: str = "25,785") -> EvidenceText:
    """Chunk a one-row 2024 revenue table whose note and data cell carry the given text."""
    html = (
        f"<table><tr><td>{note}</td><td>December 28, 2024</td></tr>"
        f"<tr><td>Net revenue</td><td>{cell}</td></tr></table>"
    )
    return table_evidence(html)


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


def fact(**changes) -> CellFact:
    """Build one inline XBRL USD million revenue fact for FY2024, changed where asked."""
    base = CellFact("us-gaap:Revenues", 2024, (), "iso4217:USD", None, 6, "25,785")
    return replace(base, **changes)


def tagged_revenue(*facts: CellFact, html: str = INCOME_TABLE) -> TableCellReading:
    """Read the FY2024 revenue cell of a table with the given facts tagged on it."""
    readings = read_table_cells(table_fragment(html), {(1, 1): facts})
    return next(cell for cell in readings if (cell.row, cell.column) == (1, 1))


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


SEPARATE = "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis=ifrs-full:SeparateMember"


def stated_revenue(statement: TableStatement | None, *facts: CellFact) -> TableCellReading:
    """Read the DART revenue cell of a table its report declares as ``statement``."""
    readings = read_table_cells(DART_FRAGMENT, {(1, 1): facts} if facts else None, None, statement)
    return next(cell for cell in readings if cell.column == 1)


def tagged_evidence(html: str, facts: dict) -> EvidenceText:
    """Read one chunked table as cited evidence with the given facts tagged on its cells."""
    chunk = table_chunk(html)
    return EvidenceText(
        1, chunk.body, chunk.context_header, tuple(read_table_cells(table_fragment(html), facts))
    )
