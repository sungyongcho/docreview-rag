"""Public evidence reads remain bounded and pinned to published identities."""

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EvalResult, EvaluationSnapshot
from app.evals.execution.evaluator import (
    evaluate_retriever,
    persist_evaluation,
    write_evaluation_artifact,
)
from app.evals.execution.models import EvaluationRetrieval
from app.evals.golden.binding import bind_golden
from app.evals.golden.loading import GOLDEN_CASES, golden_payload_sha256
from app.evals.golden.store import GoldenAdminService
from app.evals.results.artifacts import EvaluationArtifacts, write_json_artifact
from app.evals.results.identity import EVALUATED_GOLDEN_KEY, evaluated_golden_sha256
from app.evals.snapshots.evidence import PublicSnapshotDetails, SnapshotEvidenceError
from tests.evals.support import source_bound_golden


@pytest.fixture
def evidence(tmp_path):
    """Create real artifact bytes with a fake session that cannot execute work."""
    golden = json.loads(Path("data/golden/retrieval.json").read_text())[:3]
    digest = golden_payload_sha256(golden)
    config = {
        "admin_identity": {"golden_sha256": digest},
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
        "scoring": {"k": 5, "coverage_threshold": 0.5},
        EVALUATED_GOLDEN_KEY: evaluated_golden_sha256(golden),
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
    records = {EvaluationSnapshot: snapshot, EvalResult: result}
    session = AsyncMock()
    session.__aenter__.return_value = session
    source_rows = [
        (answer["doc_id"], answer["source_sha256"]) for case in golden for answer in case["answers"]
    ]
    session.execute = AsyncMock(return_value=Mock(all=lambda: source_rows))
    session.get.side_effect = lambda model, identity: records.get(model)
    service = PublicSnapshotDetails(lambda: session, EvaluationArtifacts(tmp_path))
    return SimpleNamespace(
        service=service,
        records=records,
        snapshot=snapshot,
        result=result,
        golden=golden,
        path=path,
        session=session,
    )


def test_detail_path_is_confined_before_stat(evidence, monkeypatch):
    """Public detail reads cannot inspect foreign paths or reveal them in their error."""
    evidence.result.raw_artifact_path = "/private/foreign.json"
    stat = Mock(side_effect=AssertionError("must not inspect a foreign artifact"))
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "stat", stat)
        with pytest.raises(SnapshotEvidenceError) as caught:
            asyncio.run(evidence.service.dataset(1))
    stat.assert_not_called()
    assert caught.value.code == "snapshot_evidence_unavailable"
    assert "/private" not in str(caught.value)


def test_exact_dataset_search_before_pagination(evidence):
    """Global search and sort return expected evidence, not internal notes."""
    page = asyncio.run(evidence.service.dataset(1, query="AMD", offset=1, limit=1))
    assert page.total == 3
    assert len(page.cases) == 1
    assert page.cases[0].id == "m3c-02"
    assert "note" not in page.cases[0].model_dump()
    evidence.session.execute.assert_awaited_once()
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
    evidence.session.execute.assert_awaited_once()
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
    with pytest.raises(SnapshotEvidenceError) as caught:
        asyncio.run(evidence.service.dataset(1))
    assert caught.value.code == "snapshot_not_found"
    assert evidence.session.get.await_count == 1


@pytest.mark.parametrize(
    "failure", ["missing_artifact", "hash", "missing_bound_identity", "tampered_case"]
)
def test_unavailable_exact_evidence_has_no_mutable_fallback(evidence, failure):
    """Missing and changed exact evidence fails instead of using the current suite."""
    if failure == "missing_artifact":
        evidence.path.unlink()
    elif failure == "hash":
        evidence.result.config[EVALUATED_GOLDEN_KEY] = "0" * 64
    elif failure == "missing_bound_identity":
        artifact = json.loads(evidence.path.read_text())
        del artifact["config"][EVALUATED_GOLDEN_KEY]
        evidence.path.write_text(json.dumps(artifact))
    else:
        artifact = json.loads(evidence.path.read_text())
        artifact["cases"][0]["golden"]["question"] = "Changed question"
        evidence.path.write_text(json.dumps(artifact))
    with pytest.raises(SnapshotEvidenceError) as caught:
        asyncio.run(evidence.service.dataset(1))
    assert caught.value.code == "snapshot_evidence_unavailable"
    assert str(evidence.path) not in str(caught.value)


def test_current_artifact_is_independent_of_json_key_order_and_old_database_revisions(evidence):
    """Sorted artifact bytes resolve only current snapshot and result rows."""
    artifact = json.loads(evidence.path.read_text())
    write_json_artifact(evidence.path, artifact)
    page = asyncio.run(evidence.service.dataset(1))
    assert [call.args[0] for call in evidence.session.get.await_args_list] == [
        EvaluationSnapshot,
        EvalResult,
    ]
    assert page.total == 3


def test_oversized_artifact_is_rejected_before_json_read(evidence):
    """A small response limit also has a bounded artifact input size."""
    with evidence.path.open("ab") as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    with pytest.raises(SnapshotEvidenceError) as caught:
        asyncio.run(evidence.service.evaluation(1))
    assert caught.value.code == "snapshot_evidence_unavailable"


@pytest.mark.parametrize("tamper", [None, "question", "source", "frozen_source", "old_identity"])
def test_custom_file_evidence_uses_its_evaluated_bound_identity(tmp_path, tamper):
    """A custom file can publish exact bound cases without a builtin file or DB revision reader."""

    async def scenario():
        """Author a real file, bind its sources, and read the evaluator's unchanged artifact."""
        corpus = tmp_path / "corpus"
        original, manifest, requirements = source_bound_golden(corpus)
        golden = tmp_path / "golden"
        golden.mkdir()
        (golden / "retrieval.json").write_text(json.dumps(original))
        service = GoldenAdminService(golden_dir=golden, corpus_dir=corpus)
        draft = await service.create_draft("sec-en", filename="custom.json")
        custom = {**original[0], "question": "My distinct evaluated revenue question?"}
        saved = await service.replace_case(
            draft.revision_id, custom["id"], expected_sha256=draft.sha256, payload=custom
        )
        saved_bytes = (golden / "custom.json").read_bytes()
        bound = bind_golden(saved.payload, manifest, "sec", requirements_path=requirements)
        assert bound.ready
        assert bound.cases[0].answers[0].doc_id == "sec-current"

        async def retriever(_query, _k):
            """Evaluate the bound case without external retrieval."""
            return EvaluationRetrieval(hits=())

        evaluation = await evaluate_retriever(
            bound.cases,
            retriever,
            suite="sec-en",
            config={
                "admin_identity": {"golden_sha256": saved.sha256},
                "golden_provenance": {"filename": "custom.json", "dataset_id": "file:custom"},
            },
        )
        artifacts = tmp_path / "artifacts"
        path = write_evaluation_artifact(artifacts / "custom-evaluation.json", evaluation)
        assert evaluation.config[EVALUATED_GOLDEN_KEY] != saved.sha256
        snapshot = SimpleNamespace(id=1, public=True, status="ready", eval_result_id=2)
        result = SimpleNamespace(
            id=2,
            suite="sec-en",
            config=evaluation.config,
            metrics=evaluation.metric_values(),
            raw_artifact_path=str(path),
            created_at=evaluation.recorded_at,
        )
        records = {EvaluationSnapshot: snapshot, EvalResult: result}
        session = AsyncMock()
        session.__aenter__.return_value = session

        async def get(model, identity):
            """Accept only current snapshot/result reads, never old golden ORM rows."""
            return records[model]

        session.get = AsyncMock(side_effect=get)
        sources = [
            (answer.doc_id, answer.source_sha256) for case in bound.cases for answer in case.answers
        ]
        session.execute = AsyncMock(return_value=Mock(all=lambda: sources))
        payload = json.loads(path.read_text())
        if tamper == "question":
            payload["cases"][0]["golden"]["question"] = "Tampered?"
        elif tamper == "source":
            payload["cases"][0]["golden"]["answers"][0]["doc_id"] = "another-source"
        elif tamper == "frozen_source":
            sources.clear()
        elif tamper == "old_identity":
            del payload["config"][EVALUATED_GOLDEN_KEY]
            result.config = payload["config"]
        if tamper:
            write_json_artifact(path, payload)
        original_bytes = path.read_bytes()
        details = PublicSnapshotDetails(lambda: session, EvaluationArtifacts(artifacts))
        if tamper:
            with pytest.raises(SnapshotEvidenceError) as caught:
                await details.dataset(1)
            assert caught.value.code == "snapshot_evidence_unavailable"
        else:
            page = await details.dataset(1)
            assert page.golden_sha256 == saved.sha256
            assert page.cases[0].question == custom["question"]
            assert page.cases[0].answers[0].doc_id == "sec-current"
        assert path.read_bytes() == original_bytes
        assert (golden / "custom.json").read_bytes() == saved_bytes
        assert session.get.await_count == 2
        session.commit.assert_not_called()

    asyncio.run(scenario())


@pytest.mark.parametrize("tamper", [None, "missing_scoring", "cutoff", "threshold", "retrieval"])
def test_current_evaluator_config_roundtrips_through_persistence_and_public_detail(
    evidence, tamper
):
    """Read real evaluator output unchanged; mismatched stored evidence is never repaired."""

    async def scenario():
        """Run the real evaluator, artifact writer, and persistence before public reading."""

        async def retriever(_query, _k):
            """Measure an empty retrieval without a provider or database."""
            return EvaluationRetrieval(hits=())

        config = {
            key: value
            for key, value in evidence.result.config.items()
            if key not in ("scoring", EVALUATED_GOLDEN_KEY)
        }
        evaluation = await evaluate_retriever(
            GOLDEN_CASES.validate_python(evidence.golden),
            retriever,
            suite=evidence.result.suite,
            config=config,
            k=3,
        )
        write_evaluation_artifact(evidence.path, evaluation)
        stored = []

        def add(row):
            """Capture the actual ORM row without replacing persistence behavior."""
            stored.append(row)

        async def flush():
            """Assign only the generated ID normally supplied by the database."""
            stored[0].id = 2

        evidence.session.add = Mock(side_effect=add)
        evidence.session.flush = AsyncMock(side_effect=flush)
        evidence.session.scalar = AsyncMock(return_value=None)
        source_rows = [
            (answer["doc_id"], answer["source_sha256"])
            for case in evidence.golden
            for answer in case["answers"]
        ]
        evidence.session.execute = AsyncMock(return_value=Mock(all=lambda: source_rows))
        persisted = await persist_evaluation(
            cast(AsyncSession, evidence.session),
            evaluation,
            raw_artifact_path=evidence.path,
        )
        evidence.records[EvalResult] = stored[0]
        artifact = json.loads(evidence.path.read_text())
        assert persisted.result_id == 2
        assert artifact["config"] == stored[0].config == evaluation.config
        assert artifact["config"]["scoring"] == {"k": 3, "coverage_threshold": 0.5}
        assert "scoring" not in config
        if tamper == "missing_scoring":
            del artifact["config"]["scoring"]
        elif tamper == "cutoff":
            artifact["config"]["scoring"]["k"] = 10
        elif tamper == "threshold":
            artifact["config"]["scoring"]["coverage_threshold"] = 0.75
        elif tamper == "retrieval":
            artifact["config"]["retrieval_profile"]["strategy"] = "vector"
        if tamper is not None:
            evidence.path.write_text(json.dumps(artifact))
        original_bytes = evidence.path.read_bytes()
        if tamper:
            with pytest.raises(SnapshotEvidenceError) as caught:
                await evidence.service.dataset(1)
            assert caught.value.code == "snapshot_evidence_unavailable"
        else:
            page = await evidence.service.evaluation(1)
            assert page.total == 3
            assert page.metrics["mrr"] == 0.0
            assert all(case.first_relevant_rank is None for case in page.cases)
        assert evidence.path.read_bytes() == original_bytes
        evidence.session.commit.assert_not_called()

    asyncio.run(scenario())
