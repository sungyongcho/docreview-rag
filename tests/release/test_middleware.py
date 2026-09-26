"""Pure policy parsing used by the release request guards."""

import pytest

from app.release.middleware import PUBLIC_LOCK_MESSAGE, _control_denial


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ({}, None),
        ({"prompt_policy": {}}, None),
        ({"prompt_policy": []}, None),
        ({"prompt_policy": [], "snapshot_id": 1}, PUBLIC_LOCK_MESSAGE),
        ({"retrieval_preset": "custom"}, None),
        ({"retrieval_preset": "custom", "custom_retrieval": "invalid"}, None),
        ({"snapshot_id": 0}, PUBLIC_LOCK_MESSAGE),
        ({"snapshot_id": None}, None),
    ],
    ids=[
        "no-controls",
        "explicitly-empty-prompt-policy",
        "malformed-prompt-policy",
        "snapshot-beside-a-malformed-prompt-policy",
        "custom-preset-without-custom-retrieval",
        "malformed-custom-retrieval",
        "snapshot-zero",
        "null-snapshot",
    ],
)
def test_control_denial_preserves_route_validation_ownership(profile, expected):
    """Deny only real overrides without absorbing malformed or explicitly empty fields."""
    denial = _control_denial(profile)
    if expected is None:
        assert denial is None
    else:
        assert denial is not None
        assert denial.startswith(PUBLIC_LOCK_MESSAGE)
        assert expected in denial
