"""Answer figures certified only by a unit the real chunker linked to their table."""

from dataclasses import asdict

import pytest

from app.figures.answers import EvidenceText, check_figures
from app.figures.tables import read_table_cells
from app.ingestion.chunking import Chunk, chunk_filing
from app.ingestion.parsing.models import Block
from tests.ingestion.chunk.support import build_filing

# A 10-K style table whose own rows state no unit.
SEC_TABLE = (
    "<table><tr><td></td><td>December 28, 2024</td><td>December 30, 2023</td></tr>"
    "<tr><td>Net revenue</td><td>$ 25,785</td><td>$ 22,680</td></tr></table>"
)
# A DART style table; its year sits in the header and its unit in a caption paragraph.
DART_TABLE = (
    "<table><tr><td>과목</td><td>제56기(2024년)</td><td>제55기(2023년)</td></tr>"
    "<tr><td>매출액</td><td>300,870,903</td><td>258,935,494</td></tr></table>"
)


def table_chunks(*blocks: Block) -> list[Chunk]:
    """Chunk the blocks of one filing through the real chunker and keep its table chunks."""
    filing = build_filing(list(blocks))
    filing.source_length = max(block.end_pos or 0 for block in blocks)
    return [chunk for chunk in chunk_filing(filing) if chunk.kind == "table"]


def evidence(chunk: Chunk) -> EvidenceText:
    """Read one table chunk as cited evidence, exactly as it would be stored."""
    assert chunk.table_fragment is not None
    return EvidenceText(
        1, chunk.body, chunk.context_header, tuple(read_table_cells(asdict(chunk.table_fragment)))
    )


def caption_then_table(caption: str, table: str = SEC_TABLE) -> list[Block]:
    """Lay out one caption paragraph immediately before one table."""
    end = 20 + len(caption)
    return [
        Block("paragraph", caption, source_pos=20, end_pos=end),
        Block("table", "", html=table, source_pos=end, end_pos=end + len(table)),
    ]


@pytest.mark.parametrize(
    "caption",
    [
        "(In millions of U.S. dollars)",
        "(In millions of U.S. dollars, except per share data)",
        "(U.S. dollars in millions)",
    ],
)
def test_an_english_caption_paragraph_certifies_the_next_table(caption):
    """Link an English monetary note to the next table with its source span, then certify."""
    blocks = caption_then_table(caption)
    (chunk,) = table_chunks(*blocks)
    assert chunk.table_fragment is not None
    (source,) = chunk.table_fragment.caption_sources
    assert (source.start_char, source.end_char, source.text) == (20, blocks[0].end_pos, caption)
    assert (chunk.start_char, chunk.end_char) == (blocks[1].source_pos, blocks[1].end_pos)
    assert caption not in chunk.body
    filing = build_filing(blocks)
    filing.source_length = blocks[1].end_pos or 0
    (text,) = [chunk for chunk in chunk_filing(filing) if chunk.kind == "text"]
    assert text.body == caption and (text.start_char, text.end_char) == (20, blocks[0].end_pos)
    for answer, verdict in (
        ("2024 net revenue was $25,785 million.", "verified"),
        ("2024 net revenue was $25.8 billion.", "verified"),
        ("2024 net revenue was $25,785 billion.", "unverified"),
        ("2024 net revenue was $22,680 million.", "period_mismatch"),
        ("2024 net revenue was ₩25,785 million.", "unverified"),
    ):
        assert check_figures(answer, [evidence(chunk)], [2024]).verdict == verdict, answer


@pytest.mark.parametrize(
    "caption",
    ["(In millions)", "(In millions, except per share data)", "(Dollars in millions)"],
)
def test_a_linked_scale_caption_without_an_explicit_currency_is_withheld(caption):
    """Link a scale-only (or "$"-only) caption, but withhold the "$" answer it cannot fix."""
    (chunk,) = table_chunks(*caption_then_table(caption))
    assert chunk.table_fragment is not None
    assert [source.text for source in chunk.table_fragment.caption_sources] == [caption]
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [evidence(chunk)], [2024]).verdict == "unit_unverified"


def test_a_korean_caption_paragraph_certifies_the_next_table():
    """Link a Korean 단위 caption to the next DART table and convert its compound scale."""
    (chunk,) = table_chunks(*caption_then_table("(단위 : 백만원)", DART_TABLE))
    assert chunk.table_fragment is not None
    assert [source.text for source in chunk.table_fragment.caption_sources] == ["(단위 : 백만원)"]
    assert check_figures("매출액은 300.9조원이다.", [evidence(chunk)], [2024]).verdict == (
        "verified"
    )
    assert check_figures("매출액은 300.9억원이다.", [evidence(chunk)], [2024]).verdict == (
        "unverified"
    )


def test_a_table_without_any_linked_unit_is_withheld():
    """Withhold the same answer when nothing tied to the table states its unit."""
    (chunk,) = table_chunks(Block("table", "", html=SEC_TABLE, source_pos=0, end_pos=200))
    assert chunk.table_fragment is not None and chunk.table_fragment.caption_sources == ()
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [evidence(chunk)], [2024]).verdict == "unit_unverified"


@pytest.mark.parametrize("boundary", ["heading", "paragraph", "group"])
def test_a_caption_across_a_context_boundary_does_not_reach_the_table(boundary):
    """Clear the caption at a heading, unrelated prose or a new source group."""
    blocks = [Block("paragraph", "(In millions of U.S. dollars)", source_pos=0, end_pos=20)]
    if boundary != "group":
        blocks.append(Block(boundary, "Other context", source_pos=20, end_pos=60))
    blocks.append(
        Block(
            "table",
            "",
            html=SEC_TABLE,
            source_pos=60,
            end_pos=400,
            source_group=1 if boundary == "group" else 0,
        )
    )
    (chunk,) = table_chunks(*blocks)
    assert chunk.table_fragment is not None and chunk.table_fragment.caption_sources == ()
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [evidence(chunk)], [2024]).verdict == "unit_unverified"


def test_a_caption_annotates_only_the_table_right_after_it():
    """Never let a later table borrow the unit of the table before it."""
    first_end = 20 + len(SEC_TABLE)
    blocks = [
        Block("paragraph", "(In millions of U.S. dollars)", source_pos=0, end_pos=20),
        Block("table", "", html=SEC_TABLE, source_pos=20, end_pos=first_end),
        Block("table", "", html=SEC_TABLE, source_pos=first_end, end_pos=first_end + 400),
    ]
    first, second = table_chunks(*blocks)
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [evidence(first)], [2024]).verdict == "verified"
    assert check_figures(answer, [evidence(second)], [2024]).verdict == "unit_unverified"


def test_a_blank_paragraph_between_caption_and_table_keeps_the_link():
    """Ignore blank paragraphs, which neither carry nor break the caption relationship."""
    blocks = [
        Block("paragraph", "(In\xa0millions of U.S.\xa0dollars)", source_pos=0, end_pos=20),
        Block("paragraph", "  ", source_pos=20, end_pos=30),
        Block("table", "", html=SEC_TABLE, source_pos=30, end_pos=400),
    ]
    (chunk,) = table_chunks(*blocks)
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [evidence(chunk)], [2024]).verdict == "verified"


def caption_run_then_table(*captions: str, table: str = SEC_TABLE) -> list[Block]:
    """Lay out consecutive caption paragraphs immediately before one table."""
    blocks, position = [], 0
    for caption in captions:
        blocks.append(Block("paragraph", caption, source_pos=position, end_pos=position + 30))
        position += 30
    blocks.append(Block("table", "", html=table, source_pos=position, end_pos=position + 400))
    return blocks


@pytest.mark.parametrize(
    "captions",
    [
        ("(In millions)", "(In billions)"),
        ("(In billions)", "(In millions)"),
        ("(In thousands)", "(단위 : 백만원)"),
        ("(단위 : 백만원)", "(In thousands)"),
        ("(In millions)", "(Units: widgets)"),
        ("(in widgets)", "(In millions)"),
        ("(In millions)", "(단위 : 주)"),
        ("(In millions) (in widgets)",),
        ("(In millions)", "(단위 : %)"),
        ("(단위 : %)", "(In millions)"),
        ("(단위 : 백만원)", "(단위 : 백만달러)"),
        ("(In millions of U.S. dollars)", "(단위 : 백만원)"),
        ("(In millions)", "(Currency: USD)", "(Currency: KRW)"),
        ("(In millions)", "(Currency: CAD)", "(In millions of U.S. dollars)"),
    ],
)
def test_a_connected_caption_run_reaches_the_table_whole(captions):
    """Link every caption of a run with its span, so a conflict or unknown unit withholds."""
    blocks = caption_run_then_table(*captions)
    (chunk,) = table_chunks(*blocks)
    assert chunk.table_fragment is not None
    sources = chunk.table_fragment.caption_sources
    assert [source.text for source in sources] == list(captions)
    assert [(source.start_char, source.end_char) for source in sources] == [
        (block.source_pos, block.end_pos) for block in blocks[:-1]
    ]
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [evidence(chunk)], [2024]).verdict == "unit_unverified"


@pytest.mark.parametrize(
    "captions",
    [
        ("(In millions)", "(단위 : 백만미국달러)"),
        ("(In millions)", "(Currency: USD)"),
        ("(USD)", "(In millions)"),
        ("(In millions of U.S. dollars)", "(단위 : 백만달러)"),
    ],
)
def test_an_agreeing_caption_run_still_certifies(captions):
    """Certify a table whose caption run states one scale and one explicit currency."""
    (chunk,) = table_chunks(*caption_run_then_table(*captions))
    assert chunk.table_fragment is not None
    assert [source.text for source in chunk.table_fragment.caption_sources] == list(captions)
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [evidence(chunk)], [2024]).verdict == "verified"
    refused = check_figures("2024 net revenue was ₩25,785 million.", [evidence(chunk)], [2024])
    assert refused.verdict == "unverified"


def test_english_captions_of_a_run_keep_their_narrative_coverage():
    """Keep each English caption in a text chunk while also linking it to the table."""
    blocks = caption_run_then_table("(In millions)", "(단위 : 백만원)", "(In billions)")
    filing = build_filing(blocks)
    filing.source_length = blocks[-1].end_pos or 0
    texts = [chunk.body for chunk in chunk_filing(filing) if chunk.kind == "text"]
    assert "(In millions)" in " ".join(texts) and "(In billions)" in " ".join(texts)


def test_a_non_caption_paragraph_breaks_the_run():
    """Drop every earlier caption once unrelated prose intervenes."""
    last = "(In millions of U.S. dollars)"
    blocks = caption_run_then_table("(In billions of Korean won)", "Revenue discussion.", last)
    (chunk,) = table_chunks(*blocks)
    assert chunk.table_fragment is not None
    assert [source.text for source in chunk.table_fragment.caption_sources] == [last]
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [evidence(chunk)], [2024]).verdict == "verified"


def test_an_unreadable_linked_unit_is_withheld():
    """Withhold a figure whose linked note names a non-monetary unit."""
    (chunk,) = table_chunks(*caption_then_table("(단위 : 천주)", DART_TABLE))
    assert check_figures("매출액은 300.9조원이다.", [evidence(chunk)], [2024]).verdict == (
        "unit_unverified"
    )


def test_an_in_table_unit_header_still_certifies_without_a_caption():
    """Keep certifying a 10-K table whose own header row states its unit."""
    table = SEC_TABLE.replace("<td></td>", "<td>(In millions of U.S. dollars)</td>", 1)
    (chunk,) = table_chunks(Block("table", "", html=table, source_pos=0, end_pos=300))
    answer = "2024 net revenue was $25,785 million."
    assert check_figures(answer, [evidence(chunk)], [2024]).verdict == "verified"
