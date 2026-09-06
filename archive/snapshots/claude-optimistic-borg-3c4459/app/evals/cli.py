"""Argument types shared by the evaluation commands.

Every rejection here happens during parsing, before a command reads a corpus or spends
a provider call on a matrix it will refuse later.
"""

import argparse
import math


def positive_int(value: str) -> int:
    """Parse one argparse value that must be a positive integer."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def unit_ratio(value: str) -> float:
    """Parse one argparse value that must be a finite ratio in ``(0, 1]``."""
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.0 < parsed <= 1.0:
        raise argparse.ArgumentTypeError("value must be a ratio in (0, 1]")
    return parsed
