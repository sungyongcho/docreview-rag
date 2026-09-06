"""Reviewed expectations for the committed retrieval golden suite."""

from app.evals.curation import MAX_CANDIDATE_SPAN_CHARS

CASE_ID_PATTERN = r"m3c-[0-9]{2}"
CASE_COUNT = 28
POSITIVE_CASE_COUNT = 24
ABSENT_CASE_COUNT = 4
POSITIVE_DOCUMENT_COUNT = 20
DEMO_HERO_COUNT = 8

# The committed suite is held to the same width gate that admits new cases, so
# widening intake cannot leave the suite's own expectation behind.
MAX_ANSWER_SPAN_CHARS = MAX_CANDIDATE_SPAN_CHARS

CATEGORY_COUNTS = {
    "simple_lookup": 13,
    "exact_number": 5,
    "multi_hop": 6,
    "absent": 4,
}

FACET_COUNTS = {
    "factual": 6,
    "comparison": 6,
    "risk": 6,
    "policy": 5,
    "numeric": 5,
}

POSITIVE_ISSUER_COUNTS = {"AMD": 6, "INTC": 6, "MU": 6, "NVDA": 6}

# Generated candidates awaiting review, from data/golden/candidates/r1.json.
COMMITTED_CANDIDATE_COUNT = 4
COMMITTED_ABSENT_CANDIDATE_COUNT = 1
