from collections import Counter
from pathlib import Path
import re
from types import ModuleType

import pytest

from app.ingestion.manifest import Manifest
from tests.ingestion.golden import XREF_ITEM_SHAPE, XREF_TABLES

INTC_DOCS = sorted(XREF_TABLES)

_MANIFEST = Path(__file__).resolve().parents[2] / "data/corpus/manifest.json"
_CORPUS_IDS = (
    {document.document_id for document in Manifest.read(_MANIFEST).documents}
    if _MANIFEST.exists()
    else set()
)
pytestmark = pytest.mark.skipif(
    not set(INTC_DOCS) & _CORPUS_IDS,
    reason="xref-segmented Intel filings are not acquired in the corpus",
)


# xref table structure
@pytest.fixture(scope="session")
def corpus_xref_tables(
    xref_module: ModuleType,
    blocks_by_doc: dict[str, tuple],
) -> dict[str, tuple]:
    """Locate the xref and TOC tables once for each Intel corpus filing."""
    return {doc: xref_module.find_tables(blocks_by_doc[doc][0]) for doc in INTC_DOCS}


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_corpus_xref_table_counts_match_golden(
    doc: str,
    xref_module: ModuleType,
    corpus_xref_tables: dict[str, tuple],
) -> None:
    """Keep parsed index-entry and TOC-row counts stable for every Intel filing."""
    xref_table, toc_table = corpus_xref_tables[doc]
    actual = (
        len(xref_module.parse_xref(xref_table)),
        len(xref_module.parse_toc(toc_table)),
    )
    assert actual == XREF_TABLES[doc]


# Page-join results
@pytest.mark.parametrize("doc", INTC_DOCS)
def test_item7_joins_multiple_narrative_sections(doc: str, parsed: dict) -> None:
    """Preserve the measured Item 7 body assembled from several page ranges."""
    expected_chars, _expected_tables = XREF_ITEM_SHAPE[doc]
    section = next(section for section in parsed[doc].sections if section.item == "7")
    assert sum(len(block.text) for block in section.blocks) == expected_chars


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_financial_statements_join_to_item8(doc: str, parsed: dict) -> None:
    """Keep each Intel filing's measured financial-statement tables in Item 8."""
    _expected_chars, expected_tables = XREF_ITEM_SHAPE[doc]
    section = next(section for section in parsed[doc].sections if section.item == "8")
    assert sum(block.kind == "table" for block in section.blocks) == expected_tables


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_second_sweep_recovers_item3(doc: str, parsed: dict) -> None:
    """Recover Legal Proceedings when it exists in the body but not the company TOC."""
    section = next((section for section in parsed[doc].sections if section.item == "3"), None)
    assert section is not None, f"{doc}: Item 3 was not recovered"
    assert sum(len(block.text) for block in section.blocks) > 5_000


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_part_iii_is_incorporated_by_reference(doc: str, parsed: dict) -> None:
    """Preserve proxy-reference status for at least four Part III Items."""
    by_item = {section.item: section for section in parsed[doc].sections}
    referenced = [
        item
        for item in ("10", "11", "12", "13", "14")
        if item in by_item and by_item[item].status == "incorporated_by_reference"
    ]
    assert len(referenced) >= 4, f"{doc}: referenced Part III Items {referenced}"


# Noise removal and duplicate prevention
@pytest.mark.parametrize("doc", INTC_DOCS)
def test_page_footers_and_repeated_headers_are_removed(doc: str, parsed: dict) -> None:
    """Exclude page numbers and repeated page headers from emitted paragraph blocks."""
    texts = [
        block.text
        for section in parsed[doc].sections
        for block in section.blocks
        if block.kind == "paragraph"
    ]
    assert sum(text.strip() == "Table of Contents" for text in texts) == 0
    assert sum(text.strip().isdigit() and len(text.strip()) <= 3 for text in texts) == 0


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_no_eligible_corpus_block_is_emitted_twice(
    doc: str,
    xref_module: ModuleType,
    blocks_by_doc: dict[str, tuple],
    parsed: dict,
) -> None:
    """Ensure each source block belongs to at most one emitted SEC Item."""
    soup, blocks, _raw = blocks_by_doc[doc]
    xref_table, toc_table = xref_module.find_tables(soup)
    skip = xref_module.in_tables(blocks, [xref_table, toc_table])
    frequency = Counter(block.get_text(" ", strip=True) for block in blocks)
    eligible = sum(
        1
        for index, block in enumerate(blocks)
        if index not in skip
        and (text := block.get_text(" ", strip=True))
        and not re.fullmatch(r"\d{1,3}", text)
        and not (len(text) < 60 and frequency[text] >= 10)
    )
    emitted = sum(len(section.blocks) for section in parsed[doc].sections)
    assert emitted <= eligible, f"{doc}: {emitted - eligible} duplicate blocks"
