from bs4 import BeautifulSoup, Tag
import pytest

from app.ingestion.tables import drop_empty, merge_unit_columns, table_to_markdown, to_grid
from tests.ingestion.golden import NVDA_FY2024_INCOME_MD, TABLES

type BlocksByDoc = dict[str, tuple[BeautifulSoup, list[Tag], str]]

# Only the consolidated income statement carries both phrases; the MD&A
# percentage-of-revenue table shares every other obvious marker with it.
INCOME_STATEMENT_PHRASES = ("Gross profit", "Net income per share")


def _tables(blocks: list[Tag]) -> list[Tag]:
    return [block for block in blocks if block.name == "table"]


@pytest.mark.parametrize("doc", sorted(TABLES))
def test_corpus_table_collapse_matches_golden(
    doc: str,
    blocks_by_doc: BlocksByDoc,
) -> None:
    """Match measured empty, expanded, and collapsed cell totals for each document."""
    _soup, blocks, _raw = blocks_by_doc[doc]
    empty = expanded = collapsed = 0

    for table in _tables(blocks):
        grid = to_grid(table)
        expanded += sum(len(row) for row in grid)
        collapsed += sum(len(row) for row in merge_unit_columns(drop_empty(grid)))
        if not table_to_markdown(table):
            empty += 1

    assert (empty, expanded, collapsed) == TABLES[doc]


def test_representative_income_statement_matches_golden(
    blocks_by_doc: BlocksByDoc,
) -> None:
    """Match the NVDA consolidated income statement markdown exactly."""
    _soup, blocks, _raw = blocks_by_doc["sec-0001045810-24-000029"]
    matched = [
        table
        for table in _tables(blocks)
        if all(phrase in table.get_text(" ", strip=True) for phrase in INCOME_STATEMENT_PHRASES)
    ]

    assert len(matched) == 1, "the income statement phrases must select exactly one table"
    assert table_to_markdown(matched[0]) == NVDA_FY2024_INCOME_MD
