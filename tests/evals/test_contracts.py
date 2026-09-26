"""Reject contradictory or duplicated execution settings at the input boundary."""

from pydantic import ValidationError
import pytest

from app.evals.contracts import EvaluationRunRequest


def test_matrix_axes_must_be_unique_and_nonempty() -> None:
    """Refuse a matrix whose repeated axes would duplicate artifacts."""
    with pytest.raises(ValidationError, match="target_tokens must be nonempty and unique"):
        EvaluationRunRequest(
            suite_id="sec-en",
            mode="matrix",
            target_tokens=(1024, 1024),
        )
