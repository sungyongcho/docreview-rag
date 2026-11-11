"""Canonical table records built once from the chunker's table pieces."""

from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
import re

import pytest

from app.figures.tables import read_table_cells
from app.ingestion import table_records as table_records_module
from app.ingestion.chunking import CellFragment, TableFragment, chunk_filing
from app.ingestion.parsing.facts import (
    FilingFacts,
    PeriodTerm,
    SourceFact,
    StatementDeclaration,
)
from app.ingestion.parsing.models import Block
from app.ingestion.table_records import (
    RESOLVER_FILES,
    _joined,
    builder_identity,
    resolver_identity,
    table_records,
)
from app.ingestion.tokens import InputBudget
from tests.ingestion.chunk.support import build_filing
from tests.ingestion.seed.support import TAGGED_TABLE_HTML, table_batch, tagged_table_batch

USD_TABLE = (
    "<table><tr><td>(In millions of U.S. dollars)</td><td>December 28, 2024</td>"
    "<td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 25,785</td><td>$ 22,680</td></tr>"
    "<tr><td>Net income (loss)</td><td>(1,641)</td><td>—</td></tr></table>"
)


def table_chunks(html: str, budget: InputBudget | None = None):
    """Chunk one table through the real chunker."""
    block = Block("table", "", html=html, source_pos=0, end_pos=len(html))
    filing = build_filing([block])
    filing.source_length = len(html)
    return chunk_filing(filing, budget)


def only_record(chunks):
    """Build the records of the single table the chunks come from."""
    (record,) = table_records(chunks, {chunk.doc_id: "s" * 64 for chunk in chunks})
    return record


def test_a_table_is_stored_once_with_each_cell_interpreted():
    """Store the USD table's cells with signed values and the facts that make them known."""
    chunks = table_chunks(USD_TABLE)
    record = only_record(chunks)
    cells = {cell.text: cell.interpretation for cell in record.cells}
    assert (cells["$ 25,785"].status, cells["$ 25,785"].value) == ("known", Decimal(25785))
    assert (cells["(1,641)"].status, cells["(1,641)"].value) == ("known", Decimal(-1641))
    assert cells["—"].status == "blank"
    assert cells["Net revenue"].status == "not_numeric"
    revenue = cells["$ 25,785"].reading
    assert revenue is not None
    assert (revenue.item, revenue.years, revenue.currency) == ("revenue", {2024}, "USD")
    assert record.unit.status == "known"
    by_coordinates = {(cell.row, cell.column): cell for cell in record.cells}
    assert by_coordinates[(1, 1)].column_header == "December 28, 2024"


def test_memberships_follow_each_chunk_fragment_in_order():
    """Record every fragment cell of every piece, in fragment order, by stable key."""
    chunks = table_chunks(USD_TABLE)
    record = only_record(chunks)
    expected = [
        (chunk.stable_key, ordinal, member.row, member.column, member.text_start, member.text_end)
        for chunk in chunks
        if chunk.table_fragment is not None
        for ordinal, member in enumerate(chunk.table_fragment.cells)
    ]
    assert [
        (m.chunk_stable_key, m.ordinal, m.row, m.column, m.text_start, m.text_end)
        for m in record.memberships
    ] == expected


def test_a_dollar_only_table_keeps_its_currency_unconfirmed():
    """Store the "$" family unresolved instead of assuming U.S. dollars."""
    record = only_record(table_chunks(USD_TABLE.replace(" of U.S. dollars", "")))
    revenue = next(cell for cell in record.cells if cell.text == "$ 25,785")
    assert revenue.interpretation.status == "currency_unconfirmed"


def test_split_pieces_share_one_table_and_keep_partial_cells():
    """Join the pieces of a wide row into one table and mark sentence intervals as partial."""
    long = ". ".join(f"Sentence {index} describes the segment in detail" for index in range(40))
    html = (
        f"<table><tr><td>Item</td><td>Note</td></tr><tr><td>Risk</td><td>{long}.</td></tr></table>"
    )
    chunks = table_chunks(html, InputBudget(target_tokens=60, max_tokens=60))
    pieces = [chunk for chunk in chunks if chunk.table_fragment is not None]
    assert len(pieces) > 1
    record = only_record(chunks)
    note = next(cell for cell in record.cells if cell.text.startswith("Sentence 0"))
    intervals = [
        (m.text_start, m.text_end)
        for m in record.memberships
        if (m.row, m.column) == (note.row, note.column)
    ]
    assert len(intervals) > 1
    assert all(end - start < len(note.text) for start, end in intervals)


def test_stored_readings_match_what_each_fragment_reads():
    """Give every chunk the same readings its own fragment gives, so checks do not change."""
    chunks = table_chunks(USD_TABLE)
    record = only_record(chunks)
    stored = {(cell.cell.row, cell.cell.column): cell.reading for cell in record.source_cells}
    for chunk in chunks:
        assert chunk.table_fragment is not None
        for reading in read_table_cells(asdict(chunk.table_fragment)):
            assert stored[(reading.row, reading.column)] == reading


def test_pieces_that_disagree_on_their_table_are_refused():
    """Refuse to store two different tables under one source span."""
    (chunk,) = [chunk for chunk in table_chunks(USD_TABLE) if chunk.table_fragment is not None]
    assert chunk.table is not None and chunk.table_fragment is not None
    other = replace(chunk, table=replace(chunk.table, captions=("other",)))
    with pytest.raises(ValueError, match="disagree"):
        table_records([chunk, other], {chunk.doc_id: "s" * 64})
    stray = replace(
        chunk,
        table_fragment=TableFragment(
            chunk.table_fragment.header_rows,
            (CellFragment(99, 0, 0, 1, ()),),
            chunk.table_fragment.header_cells,
            chunk.table_fragment.caption_sources,
        ),
    )
    with pytest.raises(ValueError, match="unknown"):
        table_records([stray], {chunk.doc_id: "s" * 64})


def test_the_table_stays_out_of_the_chunk_identity():
    """Keep stable_key fixed by the fragment alone, so stored chunks keep their ids."""
    (chunk,) = [chunk for chunk in table_chunks(USD_TABLE) if chunk.table_fragment is not None]
    assert replace(chunk, table=None).stable_key == chunk.stable_key


def test_column_split_pieces_keep_their_own_header_cells():
    """Store one table whose column pieces each render only their own column headers."""
    names = [f"Subsidiary {i} with a sufficiently descriptive company name" for i in range(12)]
    html = (
        '<table><tr><td colspan="13">(단위 : 백만원)</td></tr><tr><td>Metric</td>'
        + "".join(f"<td>{name}</td>" for name in names)
        + "</tr><tr><td>Revenue</td>"
        + "".join(f"<td>{100 + i}</td>" for i in range(12))
        + "</tr></table>"
    )
    chunks = table_chunks(html, InputBudget(target_tokens=200, max_tokens=500, max_chars=400))
    pieces = [chunk for chunk in chunks if chunk.table_fragment is not None]
    assert len({piece.table_fragment.header_cells for piece in pieces if piece.table_fragment}) > 1
    record = only_record(chunks)
    for piece in pieces:
        assert piece.table_fragment is not None
        stored = [
            (header.row, header.column)
            for header in record.headers
            if header.chunk_stable_key == piece.stable_key
        ]
        assert stored == [(cell.row, cell.column) for cell in piece.table_fragment.header_cells]


def test_source_cells_carry_the_tagged_facts_inside_their_spans():
    """Each figure cell keeps the one tag inside its source span; label cells keep none."""
    batch = tagged_table_batch()
    (filing,) = batch.filings
    (record,) = table_records(
        batch.chunks,
        {chunk.doc_id: chunk.structure_id for chunk in batch.chunks},
        {filing.source.document.document_id: filing.facts},
    )
    tagged = {
        (cell.cell.row, cell.cell.column): [(fact.concept, fact.context_id) for fact in cell.facts]
        for cell in record.source_cells
        if cell.facts
    }
    assert tagged == {
        (1, 1): [("us-gaap:Revenues", "fy24")],
        (1, 2): [("us-gaap:Revenues", "fy23")],
        (2, 1): [("us-gaap:EarningsPerShareDiluted", "fy24")],
        (2, 2): [("us-gaap:EarningsPerShareDiluted", "fy23")],
        (3, 1): [("us-gaap:Revenues", "dc24")],
    }
    (untagged,) = table_records(batch.chunks, {chunk.doc_id: "s" * 64 for chunk in batch.chunks})
    assert [cell.facts for cell in untagged.source_cells] == [()] * len(untagged.source_cells)
    assert [cell.cell for cell in untagged.source_cells] == [
        cell.cell for cell in record.source_cells
    ]


def test_tagged_cells_are_read_from_their_facts():
    """Tags make the revenue known, a per-share cell plain dollars and a segment a part."""
    batch = tagged_table_batch()
    (filing,) = batch.filings
    (record,) = table_records(
        batch.chunks,
        {chunk.doc_id: chunk.structure_id for chunk in batch.chunks},
        {filing.source.document.document_id: filing.facts},
    )
    cells = {(cell.row, cell.column): cell.interpretation for cell in record.cells}
    revenue = cells[(1, 1)]
    assert revenue.status == "known" and revenue.reading is not None
    assert (revenue.reading.currency, revenue.reading.years) == ("USD", {2024})
    diluted = cells[(2, 1)].reading
    assert diluted is not None
    assert (diluted.measure, diluted.scale, diluted.overrides) == ("per_share", 1, ("scale",))
    assert cells[(2, 1)].status == "item_unknown"
    assert cells[(3, 1)].status == "scope_qualified"


# A DART-style note table whose columns are named only by period words.
TERM_TABLE = (
    "<table><tr><td>(단위 : 백만원)</td><td>당기</td><td>전기말</td></tr>"
    "<tr><td>매출액</td><td>300,870,903</td><td>258,935,494</td></tr></table>"
)
TERMS = FilingFacts(
    "dart",
    period_terms=(
        PeriodTerm("당기", 2024, date(2024, 1, 1), date(2024, 12, 31), 0, 10),
        PeriodTerm("전기", 2023, date(2023, 1, 1), date(2023, 12, 31), 0, 10),
    ),
)


def test_period_words_the_document_defines_date_its_columns():
    """당기 and 전기말 columns take the years the report's declarations give them."""
    batch = table_batch(TERM_TABLE, facts=TERMS)
    (filing,) = batch.filings
    (record,) = table_records(
        batch.chunks,
        {chunk.doc_id: chunk.structure_id for chunk in batch.chunks},
        {filing.source.document.document_id: filing.facts},
    )
    years = {
        cell.text: cell.interpretation.reading.years
        for cell in record.cells
        if cell.interpretation.reading is not None
    }
    assert years == {"300,870,903": {2024}, "258,935,494": {2023}}
    (untagged,) = table_records(batch.chunks, {chunk.doc_id: "s" * 64 for chunk in batch.chunks})
    assert {cell.interpretation.status for cell in untagged.cells if cell.column} == {
        "period_unknown"
    }


def test_a_tables_statement_combines_every_declaration_around_it():
    """The most specific kind wins; scopes that disagree make the table's scope conflicting."""
    span = len(TERM_TABLE)
    section = StatementDeclaration(0, span, "statement", "consolidated", "section D-0-3-2-0")
    group = StatementDeclaration(0, span, "income", None, "class {XBRL}IS2")
    facts = replace(TERMS, statements=(section, group), scope_declared=True)
    batch = table_batch(TERM_TABLE, facts=facts)
    (filing,) = batch.filings
    structure = {chunk.doc_id: chunk.structure_id for chunk in batch.chunks}
    (record,) = table_records(batch.chunks, structure, {filing.source.document.document_id: facts})
    assert record.statement is not None
    assert (record.statement.kind, record.statement.scope) == ("income", "consolidated")
    assert record.statement_basis == "section D-0-3-2-0; class {XBRL}IS2"
    assert {cell.interpretation.status for cell in record.cells if cell.column} == {"known"}

    separate = StatementDeclaration(0, span, "income", "separate", "class {XBRL}IS_S2")
    clash = replace(facts, statements=(section, separate))
    (record,) = table_records(batch.chunks, structure, {filing.source.document.document_id: clash})
    assert record.statement is not None and record.statement.scope == "conflicting"
    assert {cell.interpretation.status for cell in record.cells if cell.column} == {"scope_unknown"}


def test_a_filing_of_one_scope_declares_no_statement():
    """SEC tables carry no statement, so their cells keep the entity scope."""
    record = only_record(table_chunks(USD_TABLE))
    assert record.statement is None and record.statement_basis is None


def test_code_identities_are_sha256_hex_digests():
    """Fingerprint the builder and resolver code as 64 lowercase hex characters."""
    for identity in (builder_identity(), resolver_identity()):
        assert re.fullmatch(r"[0-9a-f]{64}", identity)


def test_an_inline_xbrl_sign_reaches_the_cells_value():
    """A negating tag on an unsigned figure makes the stored value negative, recorded."""
    html = TAGGED_TABLE_HTML.replace(
        'contextRef="fy24" unitRef="usd" scale="6"',
        'contextRef="fy24" unitRef="usd" scale="6" sign="-"',
    )
    batch = tagged_table_batch(html=html)
    (filing,) = batch.filings
    (record,) = table_records(
        batch.chunks,
        {chunk.doc_id: chunk.structure_id for chunk in batch.chunks},
        {filing.source.document.document_id: filing.facts},
    )
    cells = {(cell.row, cell.column): cell.interpretation for cell in record.cells}
    negated, plain = cells[(1, 1)], cells[(1, 2)]
    assert negated.reading is not None and plain.reading is not None
    assert (negated.status, negated.value, negated.reading.overrides) == (
        "known",
        Decimal(-60922),
        ("sign",),
    )
    assert (plain.value, plain.reading.overrides) == (Decimal(26974), ())


def test_only_an_inline_xbrl_tag_states_a_sign():
    """An unsigned inline XBRL tag is positive; a DART tag states no sign at all."""
    fact = SourceFact(0, 1, "x", "CFY2024dFY", None, None, None, None, "1,234")
    assert _joined(fact, FilingFacts("dart", facts=(fact,))).sign is None
    assert _joined(fact, FilingFacts("ixbrl", facts=(fact,))).sign == "+"
    negated = replace(fact, sign="-")
    assert _joined(negated, FilingFacts("ixbrl", facts=(negated,))).sign == "-"


def test_the_resolver_identity_covers_the_fact_reader(tmp_path, monkeypatch):
    """Readings change with the figure rules and with facts.py, so both are hashed."""
    assert RESOLVER_FILES == (
        "figures/currency.py",
        "figures/vocabulary.py",
        "figures/text.py",
        "figures/tables.py",
        "ingestion/parsing/facts.py",
    )
    app = Path(table_records_module.__file__).resolve().parents[1]
    for name in RESOLVER_FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes((app / name).read_bytes())
    monkeypatch.setattr(table_records_module, "_APP", tmp_path)
    resolver_identity.cache_clear()
    try:
        copied = resolver_identity()
        (tmp_path / "ingestion/parsing/facts.py").write_bytes(b"# changed\n")
        resolver_identity.cache_clear()
        assert resolver_identity() != copied
    finally:
        resolver_identity.cache_clear()
