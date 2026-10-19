"""Answer figures checked against a real filing table's column periods."""

from dataclasses import asdict

from app.contracts.figures import EvidenceText, check_figures
from app.ingestion.parsing.html import line_offsets, normalize, source_pos


def test_amd_2024_income_statement_separates_reported_and_comparative_revenue(
    corpus, chunks_by_doc
):
    """Accept FY2024 revenue and flag the FY2023 comparative value stated as 2024."""
    doc_id = "sec-0000002488-25-000012"
    _filing, raw = corpus[doc_id]
    start = source_pos(normalize(raw).find_all("table")[12], line_offsets(raw))
    chunk = next(
        c
        for c in chunks_by_doc[doc_id]
        if c.start_char == start and "25,785" in c.body and "22,680" in c.body
    )
    assert chunk.table_fragment is not None
    evidence = [EvidenceText(1, chunk.body, chunk.context_header, asdict(chunk.table_fragment))]

    reported = check_figures("AMD's 2024 net revenue was $25,785 million.", evidence, [2024])
    comparative = check_figures("AMD's 2024 net revenue was $22,680 million.", evidence, [2024])

    assert reported.verdict == "verified"
    assert comparative.verdict == "period_mismatch"
    assert comparative.checks[0].evidenced_years == (2023,)
