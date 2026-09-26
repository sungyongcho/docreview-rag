"""Arm naming, ordering, and artifact identity shared by the evaluation commands."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.evals.identity import artifact_filename

RECORDED_AT = datetime(2026, 8, 12, 14, 30, tzinfo=UTC)


def test_artifact_filename_normalizes_equivalent_instants_to_one_utc_stem():
    """Encode one UTC second-resolution timestamp regardless of the caller's zone."""
    seoul = RECORDED_AT.astimezone(timezone(timedelta(hours=9)))

    assert artifact_filename(RECORDED_AT, "structure-1200-hybrid-bm25") == (
        "20260812T143000Z-structure-1200-hybrid-bm25.json"
    )
    assert artifact_filename(seoul, "budgets") == artifact_filename(RECORDED_AT, "budgets")
    assert artifact_filename(RECORDED_AT, "budgets") == "20260812T143000Z-budgets.json"


def test_artifact_filename_rejects_a_naive_recording_time():
    """Reject a naive timestamp rather than stamping an ambiguous instant on disk."""
    with pytest.raises(ValueError, match="timezone-aware"):
        artifact_filename(RECORDED_AT.replace(tzinfo=None), "structure-1200-vector")


@pytest.mark.parametrize("arm_name", ["../../escape", ""])
def test_artifact_filename_rejects_a_name_that_would_leave_the_artifact_directory(arm_name):
    """Reject a name carrying a separator, since it is interpolated into a path."""
    with pytest.raises(ValueError, match="kebab-case"):
        artifact_filename(RECORDED_AT, arm_name)
