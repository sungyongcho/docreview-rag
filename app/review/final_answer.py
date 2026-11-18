"""What reviewing a proposed ``final_answer`` returns, in either answer mode.

Both agent paths hand the model's ``final_answer`` to one review sequence:
:func:`~app.review.written_answer.review_written_answer` for a written answer and
:func:`~app.review.cell_answer.review_cell_answer` for a cell selection. Each returns a
:class:`FinalReview`: a report to end the run on, with the records that qualify it, or
a problem to send back to the model. How a rejection reaches the model and where the
records are stored stays with the caller.
"""

from dataclasses import dataclass
from typing import Any

from app.contracts.answers import AgentAnswer, AgentReportAnswer
from app.contracts.figures import FiguresWithheld, PeriodMismatch

# The rejection both agent paths send for a turn that pairs final_answer with other calls.
FINAL_NOT_ALONE = "final_answer must be the only tool call in its provider turn"


@dataclass(frozen=True, slots=True)
class FinalReview:
    """The decision on one proposed final answer: a report, or a problem for the model.

    ``report`` is None exactly when ``problem`` is set. ``period_mismatch`` and
    ``withheld`` are the typed records of a report the review qualified; a plain
    accepted answer has neither. ``cell_checks`` are the private per-cell records of a
    cell selection, kept in graph state and never shown to the model or the public.
    """

    report: AgentReportAnswer | None = None
    problem: str | None = None
    period_mismatch: PeriodMismatch | None = None
    withheld: FiguresWithheld | None = None
    cell_checks: tuple[dict[str, Any], ...] = ()


class EvidenceReadError(RuntimeError):
    """The evidence a final answer is judged by could not be read.

    The review raises it instead of judging the answer without its evidence; the
    caller ends the run on ``failure``, which is already redacted.
    """

    def __init__(self, failure: str) -> None:
        """Keep the redacted failure the run ends on."""
        super().__init__(failure)
        self.failure = failure


def as_report(answer: AgentAnswer) -> AgentReportAnswer:
    """Widen an accepted model answer to the report type."""
    return AgentReportAnswer.model_validate(answer.model_dump())
