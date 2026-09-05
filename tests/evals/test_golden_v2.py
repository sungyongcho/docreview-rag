"""Evidence alignment and provenance of the bilingual SEC v2 suite family."""

from collections import Counter
from pathlib import Path
import re

from app.evals.loader import load_golden_cases


def test_v2_suites_share_verified_evidence_and_preserve_unapproved_status():
    """Validate all 60 source-bound cases and the requested category/issuer distribution."""
    groups = [
        load_golden_cases(Path("data/golden") / f"sec_{language}_v2_astra.json")
        for language in ("en", "ko", "mixed")
    ]
    for cases in groups:
        assert len(cases) == 20
        assert Counter(case.category for case in cases) == {
            "simple_lookup": 8,
            "exact_number": 6,
            "multi_hop": 4,
            "absent": 2,
        }
        assert Counter(case.id.split("-")[0] for case in cases) == {
            "amd": 5,
            "intc": 5,
            "mu": 5,
            "nvda": 5,
        }
        assert all(
            case.human_verified is False and case.approval_status == "pending-author-approval"
            for case in cases
        )
    for en, ko, mixed in zip(*groups, strict=True):
        years = [
            set(re.findall(r"(?<!\d)20\d{2}(?!\d)", case.question)) for case in (en, ko, mixed)
        ]
        assert years[0] == years[1] == years[2]
        assert en.answers == ko.answers == mixed.answers
        assert en.expected_label == ko.expected_label == mixed.expected_label
        assert en.question != ko.question != mixed.question
