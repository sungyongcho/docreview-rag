"""Stable on-disk JSON encoding shared by every evaluation artifact."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.evals.artifacts import utc_text, write_json_artifact


def test_utc_text_rejects_a_naive_timestamp():
    """Reject a timestamp whose instant cannot be resolved."""
    with pytest.raises(ValueError, match="timezone-aware"):
        utc_text(datetime(2026, 8, 12, 15))


def test_utc_text_normalizes_equivalent_instants_to_one_utc_string():
    """Render the same instant identically whatever offset recorded it."""
    in_utc = datetime(2026, 8, 12, 15, tzinfo=UTC)
    in_seoul = datetime(2026, 8, 13, 0, tzinfo=timezone(timedelta(hours=9)))

    assert utc_text(in_utc) == "2026-08-12T15:00:00Z"
    assert utc_text(in_seoul) == utc_text(in_utc)


def test_a_non_json_destination_is_rejected_before_anything_is_created(tmp_path):
    """Reject a non-JSON destination without creating its file or parent."""
    target = tmp_path / "runs" / "artifact.txt"

    with pytest.raises(ValueError, match="must end in .json"):
        write_json_artifact(target, {"suite": "retrieval-v1"})

    assert not target.exists()
    assert not target.parent.exists()


def test_artifact_bytes_are_stable_and_the_parent_is_created(tmp_path):
    """Write sorted, indented, non-ASCII-preserving JSON with one terminal newline."""
    target = write_json_artifact(
        tmp_path / "runs" / "artifact.json",
        {"suite": "retrieval-v1", "cases": [1, "±"]},
    )

    assert target.read_text(encoding="utf-8") == (
        '{\n  "cases": [\n    1,\n    "±"\n  ],\n  "suite": "retrieval-v1"\n}\n'
    )


def test_a_non_finite_number_leaves_no_partial_artifact(tmp_path):
    """Reject a payload JSON cannot represent comparably, writing no file."""
    target = tmp_path / "artifact.json"

    with pytest.raises(ValueError):
        write_json_artifact(target, {"p95_latency_ms": float("nan")})

    assert not target.exists()
