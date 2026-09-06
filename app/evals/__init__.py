"""Public contracts and loader for the M3 evaluation milestone."""

from app.evals.loader import (
    DEFAULT_GOLDEN_PATH,
    DEFAULT_MANIFEST_PATH,
    GoldenDataError,
    load_golden_cases,
    validate_golden_sources,
)
from app.evals.types import (
    ExpectedLabel,
    GoldenCase,
    GoldenCategory,
    GoldenFacet,
    GoldenSpan,
    GoldenTag,
)

__all__ = [
    "DEFAULT_GOLDEN_PATH",
    "DEFAULT_MANIFEST_PATH",
    "ExpectedLabel",
    "GoldenCase",
    "GoldenCategory",
    "GoldenDataError",
    "GoldenFacet",
    "GoldenSpan",
    "GoldenTag",
    "load_golden_cases",
    "validate_golden_sources",
]
