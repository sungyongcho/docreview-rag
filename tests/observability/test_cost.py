"""Exact token-cost estimates from versioned prices."""

from decimal import Decimal

import pytest

from app.observability.cost import (
    MODEL_PRICES,
    UnknownModelPriceError,
    estimate_cost_usd,
    estimate_trace_cost_usd,
)
from tests.observability.support import step_trace


def test_cost_estimation_is_exact_accumulative_and_fail_closed():
    """Accumulate cost in exact decimals and fail closed on an unpriced model."""
    million = 1_000_000

    assert estimate_cost_usd("gpt-5.6-terra", million, million) == Decimal("14.00")
    assert estimate_cost_usd(
        "gpt-5.6-terra",
        million,
        million,
        cached_input_tokens=200_000,
        cache_write_input_tokens=100_000,
    ) == Decimal("13.69")
    assert estimate_cost_usd("gpt-5.6-terra", 0, 0) == Decimal("0")
    assert estimate_trace_cost_usd([step_trace()]) == Decimal("0.000072")
    with pytest.raises(UnknownModelPriceError):
        estimate_cost_usd("unpriced-model", 100, 20)
    with pytest.raises(ValueError):
        estimate_cost_usd("gpt-5.6-terra", -1, 0)
    with pytest.raises(ValueError):
        estimate_cost_usd("gpt-5.6-terra", True, 0)


def test_trace_cost_totals_what_the_provider_charged_rather_than_repricing():
    """Total the cost recorded on each trace instead of consulting the price table."""
    traces = [
        step_trace(model_name="unpriced-model", estimated_cost_usd=Decimal("0.25")),
        step_trace(step=2, model_name="unpriced-model", estimated_cost_usd=Decimal("0.75")),
    ]

    assert estimate_trace_cost_usd(traces) == Decimal("1.00")


def test_pinned_price_table_cannot_be_mutated_by_a_consumer():
    """Refuse an in-place edit of the pinned table that would rewrite past estimates."""
    with pytest.raises(TypeError):
        MODEL_PRICES["gpt-5.6-terra"] = MODEL_PRICES["gpt-5.6-luna"]
