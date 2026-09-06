"""Committed golden suite bound to the committed corpus snapshots."""

from collections import Counter
import re

import pytest

from app.evals.loader import DEFAULT_GOLDEN_PATH, DEFAULT_MANIFEST_PATH, load_golden_cases
from app.evals.types import GoldenCase
from tests.evals.golden import (
    ABSENT_CASE_COUNT,
    CASE_COUNT,
    CASE_ID_PATTERN,
    CATEGORY_COUNTS,
    DEMO_HERO_COUNT,
    FACET_COUNTS,
    MAX_ANSWER_SPAN_CHARS,
    POSITIVE_CASE_COUNT,
    POSITIVE_DOCUMENT_COUNT,
    POSITIVE_ISSUER_COUNTS,
)


@pytest.fixture(scope="module")
def cases() -> list[GoldenCase]:
    """Load the committed suite, which fails unless every span still binds."""
    return load_golden_cases(DEFAULT_GOLDEN_PATH, manifest_path=DEFAULT_MANIFEST_PATH)


def test_committed_suite_loads_with_exact_balance_and_pending_status(cases):
    """Keep the reviewed category, facet, and provenance balance of the suite."""
    positive = [case for case in cases if case.category != "absent"]

    assert len(cases) == CASE_COUNT
    assert all(re.fullmatch(CASE_ID_PATTERN, case.id) for case in cases)
    assert len(positive) == POSITIVE_CASE_COUNT
    assert len(cases) - len(positive) == ABSENT_CASE_COUNT
    assert Counter(case.category for case in cases) == CATEGORY_COUNTS
    assert Counter(case.facet for case in cases) == FACET_COUNTS
    assert sum("demo-hero" in case.tags for case in cases) == DEMO_HERO_COUNT
    assert all(case.curation_status == "agent-curated" for case in cases)
    assert all(case.approval_status == "pending-author-approval" for case in cases)
    assert all(case.human_verified is False for case in cases)


def test_positive_cases_cover_every_filing_and_are_issuer_balanced(cases):
    """Cover every corpus filing and keep questions evenly spread across issuers."""
    positive = [case for case in cases if case.answers]
    doc_ids = {answer.doc_id for case in positive for answer in case.answers}
    issuers = Counter(next(iter(case.answers)).doc_id.split("-", 1)[0] for case in positive)

    assert len(doc_ids) == POSITIVE_DOCUMENT_COUNT
    assert issuers == POSITIVE_ISSUER_COUNTS


def test_every_answer_span_stays_within_the_curated_width_limit(cases):
    """Keep every cited span narrow enough to remain reviewable evidence."""
    widest = max(answer.end_char - answer.start_char for case in cases for answer in case.answers)

    assert widest <= MAX_ANSWER_SPAN_CHARS
