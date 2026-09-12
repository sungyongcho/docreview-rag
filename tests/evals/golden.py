"""Reviewed expectations for the committed retrieval golden suite."""

from app.evals.curation import MAX_CANDIDATE_SPAN_CHARS

CASE_ID_PATTERN = r"m3c-[0-9]{2}"
CASE_COUNT = 16
POSITIVE_CASE_COUNT = 12
ABSENT_CASE_COUNT = 4
POSITIVE_DOCUMENT_COUNT = 10
DEMO_HERO_COUNT = 4

# The committed suite is held to the same width gate that admits new cases, so
# widening intake cannot leave the suite's own expectation behind.
MAX_ANSWER_SPAN_CHARS = MAX_CANDIDATE_SPAN_CHARS

CATEGORY_COUNTS = {
    "simple_lookup": 6,
    "exact_number": 3,
    "multi_hop": 3,
    "absent": 4,
}

FACET_COUNTS = {
    "factual": 5,
    "comparison": 3,
    "risk": 3,
    "policy": 2,
    "numeric": 3,
}

# Canonical accession ids do not encode the issuer, so cases resolve it here.
DOCUMENT_ISSUERS = {
    "sec-0000002488-20-000008": "AMD",
    "sec-0001628280-21-001185": "AMD",
    "sec-0000002488-22-000016": "AMD",
    "sec-0000002488-23-000047": "AMD",
    "sec-0000002488-24-000012": "AMD",
    "sec-0001045810-20-000010": "NVDA",
    "sec-0001045810-21-000010": "NVDA",
    "sec-0001045810-22-000036": "NVDA",
    "sec-0001045810-23-000017": "NVDA",
    "sec-0001045810-24-000029": "NVDA",
}

POSITIVE_ISSUER_COUNTS = {"AMD": 6, "NVDA": 6}

# Generated candidates awaiting review, from data/golden/candidates/r1.json.
COMMITTED_CANDIDATE_COUNT = 2
COMMITTED_ABSENT_CANDIDATE_COUNT = 1
