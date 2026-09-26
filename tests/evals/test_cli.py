"""Argument types shared by the evaluation commands."""

import argparse

import pytest

from app.evals.cli import positive_int, unit_ratio


def test_positive_int_rejects_a_nonpositive_count():
    """Reject a non-positive count during parsing."""
    with pytest.raises(argparse.ArgumentTypeError, match="must be positive"):
        positive_int("0")


def test_unit_ratio_accepts_an_interior_ratio():
    """Accept a ratio strictly inside ``(0, 1]``."""
    assert unit_ratio("0.85") == pytest.approx(0.85)


@pytest.mark.parametrize("value", ["0", "nan"])
def test_unit_ratio_rejects_a_ratio_outside_the_unit_interval(value):
    """Reject an out-of-range or non-finite ratio before a command spends a run on it."""
    with pytest.raises(argparse.ArgumentTypeError, match=r"\(0, 1\]"):
        unit_ratio(value)
