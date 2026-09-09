"""Public evidence reads remain bounded and pinned to published identities."""

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api.errors import ApiProblemError
from app.db.models import EvalResult, EvaluationSnapshot, GoldenRevision
from app.evals.loader import golden_payload_sha256
from app.evals.public_snapshot_details import PublicSnapshotDetails
from app.evals.snapshots import SnapshotService


@pytest.fixture
def evidence(tmp_path):
    """Create real artifact bytes with a fake session that cannot execute work."""
    golden = json.loads(Path("data/golden/retrieval.json").read_text())[:3]
    digest = golden_payload_sha256(golden)
    config = {
        "golden_sha256": digest,
        "retrieval_profile": {
            "k": 5,
            "strategy": "hybrid",
            "bm25_k1": 1.2,
            "bm25_b": 0.75,
            "bm25_idf": "lucene",
            "reranker": None,
            "private_token": "not-public",
        },
        "private_path": "/private/secret",
    }
    rows = [
        {
            "golden": case,
            "latency_ms": 12.5,
            "score": {
                "first_relevant_rank": 1,
                "recall_at_k": 1.0,
                "hit_at_k": 1.0,
                "reciprocal_rank": 1.0,
            },
            "hits": [],
        }
        for case in golden
    ]
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps({"suite": "retrieval", "config": config, "cases": rows}))
    snapshot = SimpleNamespace(
        id=1, public=True, status="ready", eval_result_id=2, golden_revision_id=3
    )
    result = SimpleNamespace(
        id=2,
        suite="retrieval",
        config=config,
        metrics={"mrr": 1.0},
        raw_artifact_path=str(path),
        created_at=datetime.now(UTC),
    )
    revision = SimpleNamespace(id=3, status="published", sha256=digest, payload=golden, version=2)
    records = {EvaluationSnapshot: snapshot, EvalResult: result, GoldenRevision: revision}
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute = AsyncMock(return_value=Mock(all=lambda: []))
    session.get.side_effect = lambda model, identity: records.get(model)
    snapshots = SnapshotService(session_factory=lambda: session, artifact_dir=tmp_path)
    service = PublicSnapshotDetails(lambda: session, snapshots)
    return SimpleNamespace(
        service=service,
        records=records,
        snapshot=snapshot,
        result=result,
        revision=revision,
        path=path,
        session=session,
    )


def test_exact_dataset_search_before_pagination(evidence):
    """Global search and sort return expected evidence, not internal notes."""
    page = asyncio.run(evidence.service.dataset(1, query="AMD", offset=1, limit=1))
    assert page.total == 3
    assert len(page.cases) == 1
    assert page.cases[0].id == "m3c-02"
    assert page.version == 2
    assert "note" not in page.cases[0].model_dump()
    evidence.session.execute.assert_not_called()
    evidence.session.commit.assert_not_called()


def test_recorded_evaluation_settings_and_scores(evidence):
    """Evaluation details expose only allowlisted settings and recorded metrics."""
    page = asyncio.run(evidence.service.evaluation(1, limit=1))
    assert page.config == {
        "k": 5,
        "strategy": "hybrid",
        "bm25_k1": 1.2,
        "bm25_b": 0.75,
        "bm25_idf": "lucene",
        "reranker": None,
    }
    assert "not-public" not in page.model_dump_json()
    assert page.cases[0].latency_ms == 12.5
    assert page.cases[0].first_relevant_rank == 1
    assert "/private" not in page.model_dump_json()
    evidence.session.execute.assert_not_called()
    evidence.session.commit.assert_not_called()


@pytest.mark.parametrize("visibility", ["private", "archived", "missing"])
def test_nonpublic_snapshots_never_read_linked_evidence(evidence, visibility):
    """Publication is checked before loading evaluation or revision records."""
    if visibility == "missing":
        evidence.records.pop(EvaluationSnapshot)
    elif visibility == "private":
        evidence.snapshot.public = False
    else:
        evidence.snapshot.status = "archived"
    with pytest.raises(ApiProblemError) as caught:
        asyncio.run(evidence.service.dataset(1))
    assert caught.value.status_code == 404
    assert evidence.session.get.await_count == 1


@pytest.mark.parametrize(
    "failure", ["missing_artifact", "hash", "draft", "missing_revision", "tampered_case"]
)
def test_unavailable_exact_evidence_has_no_mutable_fallback(evidence, failure):
    """Missing and changed exact evidence fails instead of using the current suite."""
    if failure == "missing_artifact":
        evidence.path.unlink()
    elif failure == "hash":
        evidence.revision.sha256 = "0" * 64
    elif failure == "draft":
        evidence.revision.status = "draft"
    elif failure == "missing_revision":
        evidence.records.pop(GoldenRevision)
    else:
        artifact = json.loads(evidence.path.read_text())
        artifact["cases"][0]["golden"]["question"] = "Changed question"
        evidence.path.write_text(json.dumps(artifact))
    with pytest.raises(ApiProblemError) as caught:
        asyncio.run(evidence.service.dataset(1))
    assert caught.value.status_code == 409
    assert str(evidence.path) not in caught.value.error.message


def test_artifact_only_snapshot_is_hash_verified(evidence):
    """Legacy snapshots may read the persisted exact payload, never a live file."""
    evidence.snapshot.golden_revision_id = None
    page = asyncio.run(evidence.service.dataset(1))
    assert page.revision_id is None
    assert page.total == 3


def test_oversized_artifact_is_rejected_before_json_read(evidence):
    """A small response limit also has a bounded artifact input size."""
    with evidence.path.open("ab") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(ApiProblemError) as caught:
        asyncio.run(evidence.service.evaluation(1))
    assert caught.value.status_code == 409


@pytest.mark.parametrize("tamper", [None, "source", "question", "original"])
def test_historical_source_bound_artifact_requires_exact_original_and_frozen_source(
    evidence, tamper
):
    """Production artifacts use filing IDs while the pinned builtin hash uses aliases."""
    import hashlib

    evidence.snapshot.golden_revision_id = None
    evidence.result.suite = "sec-en"
    golden_dir = evidence.path.parent / "golden"
    golden_dir.mkdir()
    original = evidence.revision.payload
    raw = (json.dumps(original, ensure_ascii=False, indent=2) + "\n").encode()
    source_file = golden_dir / "retrieval.json"
    source_file.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    evidence.result.config["golden_sha256"] = digest
    artifact = json.loads(evidence.path.read_text())
    artifact["suite"] = "sec-en"
    artifact["config"] = evidence.result.config
    sources = []
    for row in artifact["cases"]:
        for answer in row["golden"]["answers"]:
            alias = answer["doc_id"]
            issuer, year = alias.split("-FY")
            filing_id = f"sec-filings-{year}"
            answer["doc_id"] = filing_id
            sources.append((filing_id, issuer, int(year), answer["source_sha256"]))
    if tamper == "source":
        sources[0] = (*sources[0][:3], "0" * 64)
    if tamper == "question":
        artifact["cases"][0]["golden"]["question"] = "Different question"
    if tamper == "original":
        source_file.write_bytes(raw + b" ")
    evidence.path.write_text(json.dumps(artifact))
    evidence.service._snapshots._artifact_dir = evidence.path.parent / "eval_runs"
    evidence.service._snapshots._artifact_dir.mkdir()
    relocated = evidence.service._snapshots._artifact_dir / evidence.path.name
    evidence.path.replace(relocated)
    evidence.result.raw_artifact_path = str(relocated)
    evidence.session.execute = AsyncMock(return_value=Mock(all=lambda: sources))
    if tamper:
        with pytest.raises(ApiProblemError) as caught:
            asyncio.run(evidence.service.dataset(1))
        assert caught.value.status_code == 409
    else:
        page = asyncio.run(evidence.service.dataset(1))
        assert page.cases[0].answers[0].doc_id == "sec-filings-2019"
        assert page.golden_sha256 == digest
        assert page.cases[0].question == original[0]["question"]


@pytest.mark.parametrize("tamper", [None, "cutoff", "threshold", "retrieval"])
def test_version_one_scoring_stamp_matches_persisted_configuration(evidence, tamper):
    """Accept the writer's scoring stamp while rejecting changed evaluation settings."""
    artifact = json.loads(evidence.path.read_text())
    artifact["schema_version"] = 1
    artifact["metrics"] = {"k": 5}
    evidence.result.config = {
        **evidence.result.config,
        "scoring": {"k": 5, "coverage_threshold": 0.5},
    }
    if tamper == "cutoff":
        artifact["metrics"]["k"] = 10
    elif tamper == "threshold":
        evidence.result.config["scoring"]["coverage_threshold"] = 0.75
    elif tamper == "retrieval":
        artifact["config"]["retrieval_profile"]["k"] = 10
    evidence.path.write_text(json.dumps(artifact))
    if tamper:
        with pytest.raises(ApiProblemError):
            asyncio.run(evidence.service.dataset(1))
    else:
        assert asyncio.run(evidence.service.dataset(1)).total == 3
