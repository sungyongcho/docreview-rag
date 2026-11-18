"""Where the three answer paths differ on purpose, declared in one table.

DocReview answers a question on three paths: the fixed pipeline ``run_workflow``
(:mod:`app.workflow`, the deployed service), the hand-written tool loop ``run_agent``
(:mod:`app.agent.loop`) and LangChain's ``create_agent`` with ``ReviewGate``
(:mod:`app.agent.prebuilt`). They share the rules of :mod:`app.review`; every way in
which those rules intentionally end differently is a field of :class:`AnswerPolicy`,
and :data:`POLICIES` gives each path's value. ``tests/review/test_policy.py`` runs
every path and checks each cell of the table against what the path actually does.

Some fields choose between branches of the shared code; others record what a path's
structure decides, and each field's docstring says which. Rules that are the same on
every path are not in the table, even where they look different from the outside:

- A written ``NOT_IN_DOCS`` is accepted before any search on every path that can
  receive one. The workflow always retrieves before its check, so it never reports
  one without a search, while the agents may; refusing ``not_found`` until a search
  returned is a rule of the cell-selecting mode (:mod:`app.review.cell_answer`).
- A final answer that cannot be judged because its evidence could not be read ends
  the run without an answer on both agent paths; only how the failure is stored
  differs (``AgentResult.failure`` or the agent state's ``failure``).
- ``final_answer`` must be the only call of its turn on both agent paths
  (:data:`~app.review.final_answer.FINAL_NOT_ALONE`); the workflow makes no tool calls.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

type AnswerPath = Literal["workflow", "loop", "prebuilt"]


@dataclass(frozen=True, slots=True, kw_only=True)
class AnswerPolicy:
    """One path's choice wherever the paths intentionally decide differently."""

    unverified_figures: Literal["report_not_in_docs", "return_to_model"]
    """What a ``SUPPORTED`` answer becomes when its cited evidence does not confirm a figure.

    Read by :func:`app.review.written_answer.judge_figures`. ``report_not_in_docs``
    (workflow) reports ``NOT_IN_DOCS`` with a ``FiguresUnverified`` reason and the
    :func:`~app.review.reports.figures_unverified_report` rationale: the workflow makes
    one check call and has no model to send the answer back to. ``return_to_model``
    (loop, prebuilt) sends the answer back with
    :func:`~app.review.written_answer.figures_problem`, which names each unconfirmed
    figure and its item, so the model can correct it or answer ``NOT_IN_DOCS``.
    """

    cited_evidence: Literal["as_retrieved", "reread_at_answer"]
    """Which evidence the figure check reads, and so whether holds are checked again.

    Decided by each path's structure, not branched on. ``as_retrieved`` (workflow):
    the check reads the cited hits as retrieval returned them, with the table readings
    the runner loads for the graded table chunks; holds are found once, at retrieval,
    and reported as an ``EvidenceHeld`` reason. ``reread_at_answer`` (loop, prebuilt):
    the cited chunks are read again when the model proposes the answer
    (:func:`app.review.evidence.read_cited_evidence`), and a chunk a later filing
    replaced or holds back since retrieval ends the run as a failure instead of being
    judged.
    """

    foreign_citations: Literal["downgrade_to_not_in_docs", "return_to_model"]
    """What a ``SUPPORTED`` answer becomes when it cites evidence the path did not admit.

    Decided by each path's structure, not branched on. ``downgrade_to_not_in_docs``
    (workflow): a cited chunk id the grader did not keep as relevant downgrades the
    whole answer to ``NOT_IN_DOCS`` with ``CitationsFiltered`` and
    ``SupportDowngraded`` reasons. ``return_to_model`` (loop, prebuilt): a citation
    whose complete identity no tool returned in this question is rejected by
    :func:`app.review.written_answer.validate_final_answer` and sent back to the model.
    """

    cell_answers: bool
    """Whether ``final_answer`` may select table cells instead of writing amounts.

    Decided by each path's structure, not branched on. Only the prebuilt agent offers
    the cell-selecting answer (``ReviewContext.cell_answers``), reviewed by
    :func:`app.review.cell_answer.review_cell_answer`; that mode also refuses
    ``not_found`` until a search has returned in the question. The workflow's check
    returns a written ``AnswerDecision`` and the loop offers only the written
    ``final_answer``, so neither can receive a cell selection.
    """


POLICIES: Final[Mapping[AnswerPath, AnswerPolicy]] = MappingProxyType(
    {
        "workflow": AnswerPolicy(
            unverified_figures="report_not_in_docs",
            cited_evidence="as_retrieved",
            foreign_citations="downgrade_to_not_in_docs",
            cell_answers=False,
        ),
        "loop": AnswerPolicy(
            unverified_figures="return_to_model",
            cited_evidence="reread_at_answer",
            foreign_citations="return_to_model",
            cell_answers=False,
        ),
        "prebuilt": AnswerPolicy(
            unverified_figures="return_to_model",
            cited_evidence="reread_at_answer",
            foreign_citations="return_to_model",
            cell_answers=True,
        ),
    }
)
