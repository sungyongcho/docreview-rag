"""Pure policy parsing and denial envelopes used by the release request guards."""

import json

import pytest

from app.release.middleware import _custom_controls, _forbidden


@pytest.mark.parametrize(
    ("payload", "profile", "expected"),
    [
        ({}, {}, False),
        ([], {}, False),
        ({"budget": {}}, {"prompt_policy": {}}, False),
        ({"budget": "invalid"}, {"prompt_policy": []}, False),
        ({"max_context_chars": 3000}, {}, True),
        ({"budget": "invalid", "max_context_chars": 3000}, {}, False),
        ({}, {"prompt_policy": {"additional_instructions": "Be concise."}}, True),
        ({}, {"prompt_policy": [], "snapshot_id": 1}, True),
        ({}, {"retrieval_preset": "custom"}, True),
        ({}, {"snapshot_id": 0}, True),
        ({}, {"snapshot_id": None}, False),
    ],
)
def test_custom_controls_preserve_route_validation_ownership(payload, profile, expected):
    """Detect valid overrides without converting malformed policy fields into guard errors."""
    assert _custom_controls(payload, profile) is expected


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
