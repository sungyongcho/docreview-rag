"""Public comparisons bound stored evidence without changing administrator reads."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api.errors import ApiProblemError
from app.evals.snapshots import SnapshotService


@pytest.fixture
def comparison(tmp_path):
    """Use two local artifacts and read-only session results, without a database."""
    paths = [tmp_path / "before.json", tmp_path / "after.json"]
    payload = {
        "cases": [
            {
                "golden": {"id": "case-1", "question": "Revenue?"},
                "score": {"first_relevant_rank": 2},
            }
        ]
    }
    for path in paths:
        path.write_text(json.dumps(payload))
    snapshots = [
        SimpleNamespace(
            id=index, public=True, status="ready", eval_result_id=index, golden_revision_id=1
        )
        for index in (1, 2)
    ]
    results = [
        SimpleNamespace(
            id=index,
            suite="sec-en",
            config={},
            metrics={"mrr": 0.5},
            raw_artifact_path=str(paths[index - 1]),
        )
        for index in (1, 2)
    ]
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.scalars.side_effect = lambda _: (
        snapshots if session.scalars.await_count % 2 else results
    )
    service = SnapshotService(session_factory=lambda: session, artifact_dir=tmp_path)
    return SimpleNamespace(service=service, paths=paths, session=session, results=results)


def test_public_comparison_keeps_ordinary_recorded_results(comparison):
    """A normal comparison only reads the saved rows and preserves its contract."""
    response = asyncio.run(comparison.service.compare(1, 2, public_only=True))
    assert response.common_case_count == 1
    assert response.cases[0].baseline_question == "Revenue?"
    assert response.cases[0].baseline_rank == 2
    assert response.metrics[0].delta == 0
    comparison.session.commit.assert_not_called()
    comparison.session.execute.assert_not_called()


def test_artifact_size_cap_precedes_json_read(comparison, monkeypatch):
    """Oversized sparse files never reach the JSON reader."""
    with comparison.paths[0].open("ab") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    reader = Mock(side_effect=AssertionError("must not read oversized bytes"))
    monkeypatch.setattr(comparison.service, "_artifact", reader)
    with pytest.raises(ApiProblemError) as caught:
        asyncio.run(comparison.service.compare(1, 2, public_only=True))
    assert caught.value.status_code == 409
    reader.assert_not_called()


def test_public_path_is_confined_before_stat(comparison, monkeypatch):
    """No metadata or bytes are read for a path outside the artifact directory."""
    comparison.results[0].raw_artifact_path = "/private/foreign.json"
    stat = Mock(side_effect=AssertionError("must not stat outside artifact directory"))
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "stat", stat)
        with pytest.raises(ApiProblemError) as caught:
            asyncio.run(comparison.service.compare(1, 2, public_only=True))
        assert caught.value.status_code == 409
        stat.assert_not_called()
    assert "/private" not in caught.value.error.message


def test_public_case_cap_does_not_truncate_or_limit_admin(comparison):
    """Large collections fail publicly while the existing admin result is preserved."""
    payload = {
        "cases": [
            {
                "golden": {"id": f"case-{index}", "question": "Revenue?"},
                "score": {"first_relevant_rank": 1},
            }
            for index in range(1001)
        ]
    }
    for path in comparison.paths:
        path.write_text(json.dumps(payload))
    with pytest.raises(ApiProblemError) as caught:
        asyncio.run(comparison.service.compare(1, 2, public_only=True))
    assert caught.value.status_code == 409
    assert asyncio.run(comparison.service.compare(1, 2)).common_case_count == 1001


def test_public_response_byte_cap_does_not_truncate_admin(comparison):
    """Large projected text is refused despite fitting the artifact and case limits."""
    payload = {
        "cases": [
            {
                "golden": {"id": "case-1", "question": "q" * 600_000},
                "score": {"first_relevant_rank": 1},
            }
        ]
    }
    for path in comparison.paths:
        path.write_text(json.dumps(payload))
    with pytest.raises(ApiProblemError) as caught:
        asyncio.run(comparison.service.compare(1, 2, public_only=True))
    assert caught.value.status_code == 409
    response = asyncio.run(comparison.service.compare(1, 2))
    assert len(response.cases[0].baseline_question) == 600_000
