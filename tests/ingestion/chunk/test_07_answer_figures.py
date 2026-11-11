"""Answer figures checked against a real filing table's column periods."""

from dataclasses import asdict

from app.figures.answers import EvidenceText, check_figures
from app.figures.tables import read_table_cells
from app.ingestion.parsing.html import line_offsets, normalize, source_pos


def test_amd_2024_income_statement_withholds_figures_it_gives_no_currency_for(
    corpus, chunks_by_doc
):
    """Withhold AMD's FY2024 revenue claims: the filed table names no currency.

    Its only unit note is "(In millions, except per share amounts)", it has no linked
    caption, and its "$" signs sit in their own source cells apart from the amounts.
    Without an explicit currency neither the reported nor the comparative figure can be
    certified, so both are withheld rather than confirmed or called another period.
    """
    doc_id = "sec-0000002488-25-000012"
    _filing, raw = corpus[doc_id]
    start = source_pos(normalize(raw).find_all("table")[12], line_offsets(raw))
    chunk = next(
        c
        for c in chunks_by_doc[doc_id]
        if c.start_char == start and "25,785" in c.body and "22,680" in c.body
    )
    assert chunk.table_fragment is not None
    fragment = asdict(chunk.table_fragment)
    evidence = [
        EvidenceText(1, chunk.body, chunk.context_header, tuple(read_table_cells(fragment)))
    ]

    assert "(In millions, except per share amounts)" in [
        cell["text"] for cell in fragment["header_cells"]
    ]
    assert not fragment["caption_sources"]
    sources = [source["text"] for member in fragment["cells"] for source in member["sources"]]
    assert sources[:5] == ["Net revenue", "$", "25,785", "$", "22,680"]

    for answer in (
        "AMD's 2024 net revenue was $25,785 million.",
        "AMD's 2024 net revenue was US$25,785 million.",
        "AMD's 2024 net revenue was $22,680 million.",
    ):
        result = check_figures(answer, evidence, [2024])
        assert result.verdict == "withheld", answer
