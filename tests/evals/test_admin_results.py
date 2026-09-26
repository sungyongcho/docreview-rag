"""Stored-result reading: detail, comparison, confinement, and baseline lookup."""

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Self, cast

import pytest

from app.config import Settings
from app.db.models import EvalResult
from app.evals.admin import EvaluationAdminService
from app.evals.admin_results import compatible_baseline
from app.evals.regression import SCORING_CONFIG_KEY
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.support import load_settings


class _Row:
    """One stored evaluation result standing in for the ORM row."""

    def __init__(self, row_id: int, artifact: Path, config: dict[str, Any]) -> None:
        self.id = row_id
        self.suite = "sec-en"
        self.config = config
        self.metrics = {"recall_at_k": 0.75}
        self.raw_artifact_path = str(artifact)
        self.created_at = datetime(2026, 9, 2, tzinfo=UTC)


class _Session:
    """Async session that resolves stored rows from a fixed mapping."""

    def __init__(self, rows: dict[int, _Row]) -> None:
        self._rows = rows

    async def __aenter__(self) -> Self:
        """Enter the caller-owned session scope."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Leave the session scope without suppressing anything."""
        return None

    async def get(self, _model: object, row_id: int) -> _Row | None:
        """Return the stored row for one identifier."""
        return self._rows.get(row_id)

    async def scalars(self, _statement: object) -> tuple[_Row, ...]:
        """Return every stored row, newest first, ignoring the statement's filters."""
        return tuple(sorted(self._rows.values(), key=lambda row: row.id, reverse=True))


def _artifact(path: Path, first_rank: int | None) -> Path:
    """Write one evaluation artifact in the shape the reader expects."""
    payload = {
        "metrics": {"recall_at_k": 0.75, "hit_rate_at_k": 1.0, "mrr": 0.5, "mean_latency_ms": 12.0},
        "cases": [
            {
                "golden": {"id": "case-01", "question": "What drove revenue?"},
                "score": {"first_relevant_rank": first_rank},
                "hits": [{"citation": "NVDA FY2024 §7 c1"}],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _service(tmp_path: Path, rows: dict[int, _Row]) -> EvaluationAdminService:
    """Build the service against on-disk artifacts and stored rows."""
    return EvaluationAdminService(
        settings=load_settings(Settings, env_file=None, corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        artifact_dir=tmp_path / "runs",
        session_factory=cast(Any, lambda: _Session(rows)),
    )


def test_result_detail_reads_the_stored_artifact(tmp_path: Path) -> None:
    """Exercise the real reader, which a stubbed service cannot do.

    Notes
    -----
    The route-level tests substitute a duck-typed fake for the whole service, so an
    argument mismatch inside this method is invisible to them. This test reads a real
    file through the real call.
    """
    runs = tmp_path / "runs"
    runs.mkdir()
    row = _Row(
        1, _artifact(runs / "one.json", 2), {"admin_identity": "a", SCORING_CONFIG_KEY: {"k": 5}}
    )

    detail = asyncio.run(_service(tmp_path, {1: row}).result_detail(1))

    assert detail is not None
    assert detail.result_id == 1
    assert detail.metrics["recall_at_k"] == 0.75
    assert [case.case_id for case in detail.cases] == ["case-01"]
    assert detail.cases[0].first_relevant_rank == 2
    assert detail.cases[0].citations == ("NVDA FY2024 §7 c1",)


def test_result_detail_is_absent_for_an_unknown_identifier(tmp_path: Path) -> None:
    """A missing row is absence, not an error."""
    assert asyncio.run(_service(tmp_path, {}).result_detail(9)) is None


def test_compare_reads_both_artifacts_on_the_compatible_path(tmp_path: Path) -> None:
    """The success path is the one that reads artifacts; the guards never get there."""
    runs = tmp_path / "runs"
    runs.mkdir()
    config = {"admin_identity": "a", SCORING_CONFIG_KEY: {"k": 5}}
    rows = {
        1: _Row(1, _artifact(runs / "candidate.json", 1), config),
        2: _Row(2, _artifact(runs / "baseline.json", 3), config),
    }

    comparison = asyncio.run(_service(tmp_path, rows).compare(1, 2))

    assert comparison.candidate_id == 1
    assert comparison.baseline_id == 2
    assert {metric.name for metric in comparison.metrics} == {
        "recall_at_k",
        "hit_rate_at_k",
        "mrr",
        "mean_latency_ms",
    }


def test_compare_rejects_incompatible_results_before_reading(tmp_path: Path) -> None:
    """Incompatibility is a caller error, reported as ValueError for a typed 400."""
    runs = tmp_path / "runs"
    runs.mkdir()
    rows = {
        1: _Row(
            1,
            _artifact(runs / "candidate.json", 1),
            {"admin_identity": "a", SCORING_CONFIG_KEY: {}},
        ),
        2: _Row(
            2, _artifact(runs / "baseline.json", 1), {"admin_identity": "b", SCORING_CONFIG_KEY: {}}
        ),
    }

    with pytest.raises(ValueError, match="not compatible"):
        asyncio.run(_service(tmp_path, rows).compare(1, 2))


def test_artifact_outside_the_configured_directory_is_refused(tmp_path: Path) -> None:
    """Confinement failures stay ValueError so the boundary answers 400, not 500."""
    (tmp_path / "runs").mkdir()
    outside = _artifact(tmp_path / "escaped.json", 1)
    row = _Row(1, outside, {"admin_identity": "a", SCORING_CONFIG_KEY: {}})

    with pytest.raises(ValueError, match="outside the configured directory"):
        asyncio.run(_service(tmp_path, {1: row}).result_detail(1))


def test_compatible_baseline_reads_the_scoring_stamp_that_persistence_writes(
    tmp_path: Path,
) -> None:
    """The baseline lookup reads the key ``persist_eval_result`` stamps into the config."""
    runs = tmp_path / "runs"
    runs.mkdir()
    identity = {"golden_sha256": "a" * 64, "corpus_fingerprint": "b" * 64}
    config = {"admin_identity": identity, SCORING_CONFIG_KEY: {"k": 5}}
    row = _Row(1, _artifact(runs / "one.json", 1), config)

    async def lookup(k: int) -> EvalResult | None:
        """Ask for the newest baseline scored at cutoff ``k``."""
        async with _Session({1: row}) as session:
            return await compatible_baseline(
                cast(Any, session),
                suite="sec-en",
                golden_sha256="a" * 64,
                corpus_fingerprint="b" * 64,
                k=k,
            )

    assert asyncio.run(lookup(5)) is row
    assert asyncio.run(lookup(10)) is None


def test_compare_rejects_results_scored_at_different_cutoffs(tmp_path: Path) -> None:
    """Cutoff compatibility is read from the persisted scoring stamp."""
    runs = tmp_path / "runs"
    runs.mkdir()
    rows = {
        1: _Row(
            1,
            _artifact(runs / "candidate.json", 1),
            {"admin_identity": "a", SCORING_CONFIG_KEY: {"k": 5}},
        ),
        2: _Row(
            2,
            _artifact(runs / "baseline.json", 1),
            {"admin_identity": "a", SCORING_CONFIG_KEY: {"k": 10}},
        ),
    }

    with pytest.raises(ValueError, match="cutoffs are not compatible"):
        asyncio.run(_service(tmp_path, rows).compare(1, 2))
