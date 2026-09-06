"""Deterministic token-cost estimates using versioned, explicit prices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from app.observability.types import StepTrace

TOKENS_PER_MILLION: Final[Decimal] = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD prices per one million uncached input and output tokens."""

    input_per_million: Decimal
    output_per_million: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.input_per_million, Decimal) or not isinstance(
            self.output_per_million, Decimal
        ):
            raise ValueError("model prices must be Decimal values")
        if not self.input_per_million.is_finite() or not self.output_per_million.is_finite():
            raise ValueError("model prices must be finite")
        if self.input_per_million < 0 or self.output_per_million < 0:
            raise ValueError("model prices must be nonnegative")


# Published launch prices are pinned so historical trace estimates never drift.
MODEL_PRICES: Final[dict[str, ModelPrice]] = {
    "gpt-4.1-mini": ModelPrice(Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1-mini-2025-04-14": ModelPrice(Decimal("0.40"), Decimal("1.60")),
}


class UnknownModelPriceError(ValueError):
    """Raised when cost would otherwise be silently reported as zero."""


def _token_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def estimate_cost_usd(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    *,
    prices: dict[str, ModelPrice] | None = None,
) -> Decimal:
    """Estimate uncached token cost exactly with decimal arithmetic.

    Unknown models fail closed because a zero estimate would weaken the budget signal.
    Callers can pass an explicit versioned table for other providers or pricing dates.
    """
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name must be a nonblank string")
    input_count = _token_count(input_tokens, "input_tokens")
    output_count = _token_count(output_tokens, "output_tokens")
    table = MODEL_PRICES if prices is None else prices
    try:
        price = table[model_name]
    except KeyError as exc:
        raise UnknownModelPriceError(f"no pinned price for model {model_name!r}") from exc
    return (
        Decimal(input_count) * price.input_per_million
        + Decimal(output_count) * price.output_per_million
    ) / TOKENS_PER_MILLION


def estimate_trace_cost_usd(
    steps: tuple[StepTrace, ...] | list[StepTrace],
    *,
    prices: dict[str, ModelPrice] | None = None,
) -> Decimal:
    """Sum deterministic per-trace estimates without floating-point rounding."""
    total = Decimal(0)
    for trace in steps:
        if not isinstance(trace, StepTrace):
            raise ValueError("steps must contain StepTrace values")
        total += estimate_cost_usd(
            trace.model_name,
            trace.input_tokens,
            trace.output_tokens,
            prices=prices,
        )
    return total
