"""Reviewed expectations for the committed retrieval golden suite."""

CASE_ID_PATTERN = r"m3c-[0-9]{2}"
CASE_COUNT = 28
POSITIVE_CASE_COUNT = 24
ABSENT_CASE_COUNT = 4
POSITIVE_DOCUMENT_COUNT = 20
DEMO_HERO_COUNT = 8
MAX_ANSWER_SPAN_CHARS = 2_500

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
