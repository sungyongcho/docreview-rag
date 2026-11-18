"""Uncertain comparisons, which withhold a figure for the closed causes of the contracts."""

from dataclasses import dataclass
from typing import Literal

from app.contracts.figures import WithholdingCause, ordered_causes


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
