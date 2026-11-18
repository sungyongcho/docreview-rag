"""What a figure check may establish about an answer, as records every path reports.

The figure check (:func:`app.figures.answers.check_figures`) compares each figure an
answer states with its cited evidence. Three outcomes qualify the answer, and each has
one record here that the workflow, the agent loop and the prebuilt agent all use:
:class:`FiguresUnverified`, :class:`FiguresWithheld` and :class:`PeriodMismatch`. The
``code`` field names the record in a workflow report's ``reasons`` and in every JSON
payload that carries one.
"""

from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from app.contracts.validation import NonBlank, PositiveInt, StrictSchema

type WithholdingCause = Literal["scale", "currency", "direction"]
_CAUSE_ORDER: tuple[WithholdingCause, ...] = ("scale", "currency", "direction")


def ordered_causes(causes: Iterable[WithholdingCause]) -> tuple[WithholdingCause, ...]:
    """Deduplicate established causes in a fixed order, rejecting unknown causes."""
    found = set(causes)
    if found - set(_CAUSE_ORDER):
        raise ValueError("unknown withholding cause")
    return tuple(cause for cause in _CAUSE_ORDER if cause in found)


type WithholdingCauses = Annotated[
    tuple[WithholdingCause, ...], Field(min_length=1), AfterValidator(ordered_causes)
]


class FiguresUnverified(StrictSchema):
    """A supported answer stated figures its cited evidence contradicts or cannot hold.

    A figure is confirmed only by a cited table cell whose row is the item the answer
    names, whose column is the requested (or stated) period, and whose value matches in
    units both sides state. Running text cannot show which period a figure belongs to,
    so it confirms a figure only when no period is asked or stated.
    """

    code: Literal["figures_unverified"] = "figures_unverified"
    figures: tuple[NonBlank, ...]


class FiguresWithheld(StrictSchema):
    """Figures withheld for the established scale, currency or direction causes."""

    code: Literal["figures_withheld"] = "figures_withheld"
    causes: WithholdingCauses
    figures: tuple[NonBlank, ...]


class PeriodMismatch(StrictSchema):
    """Figures of the answer matched only a different known fiscal period."""

    code: Literal["period_mismatch"] = "period_mismatch"
    requested_fiscal_years: tuple[PositiveInt, ...]
    evidenced_fiscal_years: tuple[PositiveInt, ...]
    figures: tuple[NonBlank, ...]
