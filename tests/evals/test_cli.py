"""Argument types shared by the evaluation commands."""

import argparse

import pytest

from app.evals.cli import positive_int, unit_ratio


@pytest.mark.parametrize("value, parsed", [("1", 1), ("20", 20)])
def test_positive_int_accepts_a_positive_count(value, parsed):
    """Accept a strictly positive integer."""
    assert positive_int(value) == parsed


@pytest.mark.parametrize("value", ["0", "-1"])
def test_positive_int_rejects_a_nonpositive_count(value):
    """Reject a non-positive count during parsing."""
    with pytest.raises(argparse.ArgumentTypeError, match="must be positive"):
        positive_int(value)


@pytest.mark.parametrize("value, parsed", [("0.85", 0.85), ("1", 1.0)])
def test_unit_ratio_accepts_the_closed_upper_bound(value, parsed):
    """Accept a ratio in ``(0, 1]``, inclusive at 1."""
    assert unit_ratio(value) == pytest.approx(parsed)


@pytest.mark.parametrize("value", ["0", "-0.5", "1.5", "nan", "inf"])
def test_unit_ratio_rejects_a_ratio_outside_the_unit_interval(value):
    """Reject an out-of-range or non-finite ratio before a command spends a run on it."""
    with pytest.raises(argparse.ArgumentTypeError, match=r"\(0, 1\]"):
        unit_ratio(value)
