"""Closed causes shared by figure comparisons, cell selection and report contracts."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

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


@dataclass(frozen=True, slots=True)
class UncertainComparison:
    """A comparison withheld for at least one established, canonical cause."""

    causes: tuple[WithholdingCause, ...]

    def __post_init__(self) -> None:
        """Require uncertainty to say why, with no unknown or repeated cause."""
        causes = ordered_causes(self.causes)
        if not causes:
            raise ValueError("uncertainty requires a cause")
        object.__setattr__(self, "causes", causes)


type Comparison = Literal["match", "no"] | UncertainComparison
