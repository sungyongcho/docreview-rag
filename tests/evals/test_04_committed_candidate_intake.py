"""Committed generated candidates measured against the committed golden suite."""

from app.evals.curation import candidate_states, load_candidate_cases
from app.evals.loader import DEFAULT_GOLDEN_PATH, DEFAULT_MANIFEST_PATH, load_golden_cases
from tests.evals.golden import COMMITTED_ABSENT_CANDIDATE_COUNT, COMMITTED_CANDIDATE_COUNT

CANDIDATES_PATH = DEFAULT_GOLDEN_PATH.parent / "candidates" / "r1.json"


def test_committed_candidates_pass_every_machine_gate_and_stay_pending():
    """Pass every mechanical intake gate while staying unreviewed."""
    golden_cases = load_golden_cases(DEFAULT_GOLDEN_PATH, manifest_path=DEFAULT_MANIFEST_PATH)
    candidates = load_candidate_cases(
        CANDIDATES_PATH, golden_cases=golden_cases, manifest_path=DEFAULT_MANIFEST_PATH
    )

    assert len(candidates) == COMMITTED_CANDIDATE_COUNT
    absent = [candidate for candidate in candidates if candidate.category == "absent"]
    assert len(absent) == COMMITTED_ABSENT_CANDIDATE_COUNT
    assert all(candidate.id.startswith("m3s-") for candidate in candidates)
    assert all(candidate.generator.strip() for candidate in candidates)
    states = candidate_states(candidates)
    assert set(states.values()) == {"pending"}
