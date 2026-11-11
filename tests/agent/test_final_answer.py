"""The written final-answer verdicts judge_written_answer returns."""

from app.agent.final_answer import judge_written_answer
from app.agent.types import AgentAnswer, AgentPeriodMismatch, AgentUnitUnverified
from app.contracts.evidence import EvidenceCitation
from app.figures.answers import UNIT_UNVERIFIED_ANSWER, EvidenceText
from app.figures.tables import read_table_cells
from tests.workflow.support import INCOME_TABLE, USD_INCOME_TABLE, income_table_hit

CHUNK = 7


def evidence(html: str = USD_INCOME_TABLE) -> dict[int, EvidenceText]:
    """Read one income table as the cited evidence of chunk ``CHUNK``."""
    table, fragment = income_table_hit(CHUNK, html=html)
    readings = tuple(read_table_cells(fragment))
    return {CHUNK: EvidenceText(CHUNK, table.body, table.context_header, readings)}


def supported(text: str) -> AgentAnswer:
    """A SUPPORTED answer citing chunk ``CHUNK``."""
    table, _ = income_table_hit(CHUNK)
    citation = EvidenceCitation(
        chunk_id=table.chunk_id,
        doc_id=table.doc_id,
        citation=table.citation,
        start_char=table.start_char,
        end_char=table.end_char,
        source_sha256=table.source_sha256,
    )
    return AgentAnswer(label="SUPPORTED", answer=text, citations=(citation,), rationale="cited")


def test_a_confirmed_answer_is_accepted_as_written():
    """Accept a confirmed answer unchanged, with no qualifying record."""
    answer = supported("2024 net revenue was $25,785 million.")
    judged = judge_written_answer(answer, evidence(), [2024])
    assert judged.report is not None
    assert judged.report.model_dump() == answer.model_dump()
    assert (judged.problem, judged.period_mismatch, judged.unit_unverified) == ("", None, None)


def test_an_unconfirmed_figure_goes_back_to_the_model():
    """Return a wrong figure to the model with the item it could not confirm."""
    judged = judge_written_answer(
        supported("2024 net revenue was $99,999 million."), evidence(), [2024]
    )
    assert judged.report is None
    assert "99,999 (revenue)" in judged.problem
    assert (judged.period_mismatch, judged.unit_unverified) == (None, None)


def test_an_uncertain_unit_withholds_the_answer():
    """Withhold a figure whose cited table states no currency, keeping no number."""
    answer = supported("2024 net revenue was $25,785 million.")
    judged = judge_written_answer(answer, evidence(INCOME_TABLE), [2024])
    assert judged.report is not None
    assert (judged.report.label, judged.report.answer) == ("UNVERIFIED", UNIT_UNVERIFIED_ANSWER)
    assert judged.unit_unverified == AgentUnitUnverified(figures=("25,785",))
    assert judged.period_mismatch is None


def test_another_period_is_reported_as_a_mismatch():
    """Report the period a figure belongs to when the question asks for another."""
    judged = judge_written_answer(supported("Net revenue was $25,785 million."), evidence(), [2023])
    assert judged.report is not None
    assert judged.report.label == "PERIOD_MISMATCH"
    assert judged.period_mismatch == AgentPeriodMismatch(
        requested_fiscal_years=(2023,), evidenced_fiscal_years=(2024,), figures=("25,785",)
    )
    assert judged.unit_unverified is None
