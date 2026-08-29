"""Pinned model prices and accumulation of provider-reported trace cost."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from app.llm.schemas import TokenPricing
from app.observability.types import StepTrace

# Published launch prices are pinned so historical trace estimates never drift. The
# mapping is read-only because rebinding is not the way the table would be corrupted.
MODEL_PRICES: Final[Mapping[str, TokenPricing]] = MappingProxyType(
    {
        "gpt-4.1-mini": TokenPricing(
            input_per_million_usd=Decimal("0.40"),
            output_per_million_usd=Decimal("1.60"),
        ),
        "gpt-4.1-mini-2025-04-14": TokenPricing(
            input_per_million_usd=Decimal("0.40"),
            output_per_million_usd=Decimal("1.60"),
        ),
    }
)


class UnknownModelPriceError(ValueError):
    """Raised when cost would otherwise be silently reported as zero."""


def _token_count(value: object, name: str) -> int:
    """Return one nonnegative token count, rejecting bools and other coercions."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def estimate_cost_usd(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    *,
    prices: Mapping[str, TokenPricing] | None = None,
) -> Decimal:
    """Estimate uncached token cost from a pinned price table.

    Parameters
    ----------
    model_name : str
        Nonblank model key in the selected price table.
    input_tokens : int
        Nonnegative uncached input-token count.
    output_tokens : int
        Nonnegative output-token count.
    prices : Mapping[str, TokenPricing] | None
        Optional explicit versioned table; the pinned module table is the default.

    Returns
    -------
    Decimal
        Exact estimated USD cost.

    Raises
    ------
    ValueError
        If the model name or token counts are invalid.
    UnknownModelPriceError
        If the selected table has no exact model key.

    Notes
    -----
    The arithmetic is ``TokenPricing.estimate``, the same one the provider boundary
    charges against its budget. Unknown models fail closed because a zero estimate
    would weaken the budget signal.
    """
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name must be a nonblank string")
    input_count = _token_count(input_tokens, "input_tokens")
    output_count = _token_count(output_tokens, "output_tokens")
    table = MODEL_PRICES if prices is None else prices
    try:
        pricing = table[model_name]
    except KeyError as exc:
        raise UnknownModelPriceError(f"no pinned price for model {model_name!r}") from exc
    return pricing.estimate(input_count, output_count)


def estimate_trace_cost_usd(steps: tuple[StepTrace, ...] | list[StepTrace]) -> Decimal:
    """Total the cost each provider call already reported, without re-pricing it.

    Re-deriving cost here from a second price table would let a run report a figure
    the provider budget never enforced.
    """
    return sum((trace.estimated_cost_usd for trace in steps), Decimal(0))
