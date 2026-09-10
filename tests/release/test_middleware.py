"""Pure policy parsing and denial envelopes used by the release request guards."""

import json

import pytest

from app.release.middleware import PUBLIC_LOCK_MESSAGE, _control_denial, _forbidden


@pytest.mark.parametrize(
    ("payload", "profile", "expected"),
    [
        ({}, {}, None),
        ([], {}, None),
        ({"budget": {}}, {"prompt_policy": {}}, None),
        ({"budget": "invalid"}, {"prompt_policy": []}, None),
        ({"max_context_chars": 3000}, {}, None),
        ({"max_context_chars": 12_001}, {}, "max_context_chars must be at most 12000"),
        ({"budget": "invalid", "max_context_chars": 3000}, {}, None),
        ({"budget": {"max_iterations": 1}}, {}, PUBLIC_LOCK_MESSAGE),
        ({}, {"prompt_policy": {"additional_instructions": "Be concise."}}, PUBLIC_LOCK_MESSAGE),
        ({}, {"prompt_policy": [], "snapshot_id": 1}, PUBLIC_LOCK_MESSAGE),
        ({}, {"retrieval_preset": "custom"}, None),
        ({}, {"retrieval_preset": "custom", "custom_retrieval": "invalid"}, None),
        (
            {},
            {"retrieval_preset": "custom", "custom_retrieval": {"k": 10, "candidate_k": 50}},
            None,
        ),
        (
            {},
            {"retrieval_preset": "custom", "custom_retrieval": {"k": 11, "candidate_k": 50}},
            "custom_retrieval.k must be at most 10",
        ),
        (
            {},
            {"retrieval_preset": "custom", "custom_retrieval": {"k": 5, "candidate_k": 51}},
            "custom_retrieval.candidate_k must be at most 50",
        ),
        ({}, {"snapshot_id": 0}, PUBLIC_LOCK_MESSAGE),
        ({}, {"snapshot_id": None}, None),
    ],
)
def test_control_denial_preserves_route_validation_ownership(payload, profile, expected):
    """Deny only real overrides, naming exceeded bounds, without absorbing malformed fields."""
    denial = _control_denial(payload, profile)
    if expected is None:
        assert denial is None
    else:
        assert denial is not None
        assert denial.startswith(PUBLIC_LOCK_MESSAGE)
        assert expected in denial


def test_forbidden_preserves_the_public_error_envelope():
    """Keep each denial's code, message, empty details, and HTTP status unchanged."""
    response = _forbidden("capability_disabled", "Administrator resources are private.")
    assert response.status_code == 403
    assert json.loads(response.body) == {
        "error": {
            "code": "capability_disabled",
            "message": "Administrator resources are private.",
            "details": [],
        }
    }
