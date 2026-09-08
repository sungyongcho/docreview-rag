"""Golden suite metadata and serialized evaluation queue behavior."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pytest

from app.api.admin_schemas import EvaluationPreparationResource, EvaluationRunRequest
from app.config import Settings
from app.corpus_admin import AdminCommand, CorpusStatus, OperationOutcome, RuntimeCorpusAdminService
import app.evals.admin as admin_module
from app.evals.admin import EvaluationAdminService, EvaluationAlreadyQueuedError
from app.operator.jobs import JobExecutionCoordinator
from app.retrieval.embeddings import DeterministicEmbeddingProvider


def _absent_case(question: str) -> dict[str, object]:
    """Build one source-free revision case for focused resolver tests."""
    return {
        "id": "test-01",
        "question": question,
        "category": "absent",
        "facet": "policy",
        "tags": [],
        "answers": [],
        "expected_label": "NOT_IN_DOCS",
        "reference_answer": "NOT_IN_DOCS",
        "note": "Deliberate negative case.",
        "curation_status": "agent-curated",
        "approval_status": "pending-author-approval",
        "human_verified": False,
    }


@pytest.fixture
def ready_evaluation_inputs(monkeypatch):
    """Keep queue/coordinator tests independent from the separately tested input preflight."""

    async def prepared(self, request):
        """Provide a ready request before exercising scheduling and persistence behavior."""
        return EvaluationPreparationResource(
            suite_id=request.suite_id, kind="builtin", state="ready"
        )

    monkeypatch.setattr(EvaluationAdminService, "preparation", prepared)


def test_suite_catalog_preserves_unapproved_provenance(tmp_path: Path) -> None:
    """Never present agent-curated pending cases as human-verified goldens."""
    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        artifact_dir=tmp_path / "runs",
    )

    suites = asyncio.run(service.suites())

    assert {suite.suite_id for suite in suites} == {
        "sec-en",
        "sec-ko",
        "dart-en",
        "dart-ko",
        "sec-en_v2_astra",
        "sec-ko_v2_astra",
        "sec-mixed_v2_astra",
    }
    assert all(suite.approval_status == "pending-author-approval" for suite in suites)
    assert all(suite.human_verified is False for suite in suites)
    assert all(suite.source_ready is False for suite in suites)


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_evaluation_queue_runs_one_job_to_completion(tmp_path: Path, monkeypatch) -> None:
    """Keep evaluation execution serial and retain its terminal artifact identity."""

    async def scenario() -> None:
        """Queue one evaluation and inspect its completed state."""
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )

        async def quick(job_id, request):
            """Stand in for one completed quick evaluation."""
            del job_id, request
            artifact = tmp_path / "runs" / "result.json"
            return 7, 6, artifact

        monkeypatch.setattr(service, "_quick", quick)
        job = await service.enqueue(EvaluationRunRequest(suite_id="sec-en"))
        await service._queue.join()
        completed = await service.job(job.job_id)

        assert completed is not None
        assert completed.status == "succeeded"
        assert completed.result_id == 7
        assert completed.baseline_id == 6

    asyncio.run(scenario())


def test_matrix_forwards_dart_manifest_and_profile_parameters(tmp_path: Path, monkeypatch) -> None:
    """Bind isolated DART runs to their exact selection and explicit BM25 values."""

    async def scenario() -> None:
        """Capture one matrix invocation and verify its explicit parameters."""
        captured = None
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )

        async def run_cli(args):
            """Capture the parsed matrix namespace without corpus or database work."""
            nonlocal captured
            captured = args
            return {"persisted": [], "artifacts": []}

        from app.ingestion.source_publication import publish_acquired
        from tests.ingestion.support import acquired_filing, filing_document

        filing = acquired_filing(tmp_path, document=filing_document(registry="dart"))
        publish_acquired(
            tmp_path / "manifest.json",
            [filing],
            selection_id="download",
            selected_document_ids=[filing.document.document_id],
        )

        async def cases(request):
            """Use a source-free question to isolate matrix scope construction."""
            from app.evals.loader import GOLDEN_CASES

            return GOLDEN_CASES.validate_python([_absent_case("Absent?")]), "a" * 64

        monkeypatch.setattr(service, "_evaluation_cases", cases)
        monkeypatch.setattr(admin_module, "_run_cli", run_cli)
        request = EvaluationRunRequest(
            suite_id="dart-ko",
            mode="matrix",
            profile={"bm25_k1": 1.5, "bm25_b": 0.6},
        )
        await service._matrix(request)

        assert captured is not None
        assert Path(captured.manifest_name).name.startswith(".evaluation-scope-")
        assert not Path(captured.manifest_name).exists()
        assert captured.selection_id == "evaluation-scope"
        assert captured.bm25_k1 == 1.5
        assert captured.bm25_b == 0.6

    asyncio.run(scenario())


def test_selected_golden_revision_drives_quick_and_matrix_inputs(
    tmp_path: Path, monkeypatch
) -> None:
    """Evaluate the selected DB payload instead of silently falling back to canonical JSON."""

    async def scenario() -> None:
        """Resolve one revision for quick mode and materialize it for matrix mode."""
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        raw = "<p>Source.</p>"
        digest = hashlib.sha256(raw.encode()).hexdigest()
        source_path = corpus_dir / "sec/TEST/0000000001-24-000001/primary.html"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(raw)
        manifest = corpus_dir / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "corpus": {"corpus_id": "test", "name": "Test"},
                    "documents": [
                        {
                            "document_id": "TEST-FY2024",
                            "registry": "sec",
                            "language": "en",
                            "issuer": "TEST",
                            "issuer_id": "0000000001",
                            "filing_id": "0000000001-24-000001",
                            "fiscal_year": 2024,
                            "form": "10-K",
                            "filing_date": "2025-01-01",
                            "report_period": "2024-12-31",
                            "source_url": "https://example.org/source",
                            "sec": {
                                "cik": "0000000001",
                                "accession": "0000000001-24-000001",
                                "primary_document": "source.html",
                            },
                        }
                    ],
                    "artifacts": [
                        {
                            "artifact_id": "source",
                            "document_id": "TEST-FY2024",
                            "role": "primary",
                            "path": "sec/TEST/0000000001-24-000001/primary.html",
                            "sha256": digest,
                            "byte_length": len(raw.encode()),
                            "encoding": "utf-8",
                            "acquisition": {
                                "acquired_at": "2025-01-01T00:00:00Z",
                                "url": "https://example.org/source",
                                "media_type": "text/html",
                            },
                        }
                    ],
                    "selections": [{"selection_id": "sec-evaluation", "artifact_ids": ["source"]}],
                }
            ),
            encoding="utf-8",
        )
        payload = [_absent_case("Revision question?")]
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=corpus_dir),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )

        from app.evals.golden_admin import GoldenAdminService

        golden_dir = tmp_path / "golden"
        golden_dir.mkdir()
        (golden_dir / "retrieval.json").write_text(json.dumps(payload))
        golden = GoldenAdminService(golden_dir=golden_dir, corpus_dir=corpus_dir)
        draft = await golden.create_draft("sec-en", filename="custom.json")
        service._golden_dir = golden_dir

        captured = None

        async def run_cli(args):
            """Read the temporary matrix input while it is still present."""
            nonlocal captured
            captured = (args, json.loads(args.golden.read_text(encoding="utf-8")))
            return {"persisted": [], "artifacts": []}

        monkeypatch.setattr(admin_module, "_run_cli", run_cli)
        request = EvaluationRunRequest(suite_id="sec-en", golden_revision_id=draft.revision_id)

        cases, sha256 = await service._evaluation_cases(request)
        await service._matrix(request.model_copy(update={"mode": "matrix"}))

        assert cases[0].question == "Revision question?"
        assert sha256 == draft.sha256
        assert captured is not None
        args, written = captured
        assert written == payload
        assert args.admin_metadata["golden_provenance"]["filename"] == "custom.json"
        assert args.admin_metadata["golden_provenance"]["golden_sha256"] == draft.sha256
        assert not args.golden.exists()

    asyncio.run(scenario())


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_queued_evaluation_can_be_cancelled_before_execution(tmp_path: Path, monkeypatch) -> None:
    """Keep cancellation cost-free by allowing it only before evaluation starts."""

    async def scenario() -> None:
        """Hold one active evaluation and cancel its queued successor."""
        gate = asyncio.Event()
        calls = 0
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
        )

        async def quick(job_id, request):
            """Block the first evaluation and record that the second never ran."""
            nonlocal calls
            del job_id, request
            calls += 1
            await gate.wait()
            return 1, None, tmp_path / "runs" / "result.json"

        monkeypatch.setattr(service, "_quick", quick)
        await service.enqueue(EvaluationRunRequest(suite_id="sec-en"))
        second = await service.enqueue(EvaluationRunRequest(suite_id="sec-ko"))
        await asyncio.sleep(0)
        cancelled = await service.cancel(second.job_id)
        gate.set()
        await service._queue.join()

        assert calls == 1
        assert cancelled.status == "cancelled"
        assert (await service.job(second.job_id)).status == "cancelled"

    asyncio.run(scenario())


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_corpus_and_evaluation_workers_share_one_execution_lock(
    tmp_path: Path, monkeypatch
) -> None:
    """Keep heavy corpus and evaluation work serialized across domain queues."""

    async def scenario() -> None:
        """Hold corpus work and prove evaluation remains queued until release."""
        lock = asyncio.Lock()
        coordinator = JobExecutionCoordinator()
        gate = asyncio.Event()
        events: list[str] = []

        async def corpus_runner(command, publish) -> OperationOutcome:
            """Hold the shared lock while one corpus job is active."""
            del command, publish
            events.append("corpus-start")
            await gate.wait()
            events.append("corpus-finish")
            return OperationOutcome("done")

        corpus = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            operation_runner=corpus_runner,
            execution_lock=lock,
            execution_coordinator=coordinator,
        )
        evaluation = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            artifact_dir=tmp_path / "runs",
            execution_lock=lock,
            execution_coordinator=coordinator,
        )

        async def quick(job_id, request):
            """Record evaluation start only after corpus releases the lock."""
            del job_id, request
            events.append("evaluation-start")
            return 1, None, tmp_path / "runs" / "result.json"

        monkeypatch.setattr(evaluation, "_quick", quick)
        await corpus.enqueue(AdminCommand("rebuild_bm25"))
        evaluation_job = await evaluation.enqueue(EvaluationRunRequest(suite_id="sec-en"))
        await asyncio.sleep(0)
        assert events == ["corpus-start"]
        assert (await evaluation.job(evaluation_job.job_id)).status == "queued"

        gate.set()
        await corpus._queue.join()
        await evaluation._queue.join()
        assert events == ["corpus-start", "corpus-finish", "evaluation-start"]

    asyncio.run(scenario())


def test_suite_source_failure_is_typed_without_guessing(tmp_path: Path, monkeypatch) -> None:
    """Only actual source absence is classified as an acquisition prerequisite."""
    from app.evals.loader import GoldenDataError

    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        artifact_dir=tmp_path / "runs",
    )

    def missing(*args, **kwargs):
        """Simulate the loader's explicit absent-artifact contract."""
        from app.evals.source_binding import BoundGolden, SourceCheck

        return BoundGolden(
            (),
            (
                SourceCheck(
                    "missing",
                    "sec",
                    "NVDA",
                    2024,
                    "receipt",
                    None,
                    "source_missing",
                    "missing artifact",
                ),
            ),
        )

    monkeypatch.setattr(admin_module, "bind_golden", missing)
    assert all(row.source_error_code == "source_missing" for row in asyncio.run(service.suites()))

    def invalid(*args, **kwargs):
        """Keep invalid hashes or manifests distinct from missing downloads."""
        raise GoldenDataError("invalid source contract")

    monkeypatch.setattr(admin_module, "bind_golden", invalid)
    assert all(row.source_error_code == "source_invalid" for row in asyncio.run(service.suites()))


@pytest.mark.parametrize("preparation_succeeds", [True, False])
@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_waiting_evaluation_deduplicates_and_rechecks_preparation(
    tmp_path, monkeypatch, preparation_succeeds
):
    """Queue behind embeddings, reject duplicates, and never measure a failed partial index."""

    async def scenario():
        """Hold the corpus turn, submit twice, then expose the actual terminal readiness."""
        coordinator = JobExecutionCoordinator()
        await coordinator.register("embedding-job", datetime.now(UTC), kind="backfill_embeddings")
        status = CorpusStatus(True, "compatible", "ok", 1, 10, 5, 5, True, True, "deterministic")
        calls = []

        async def readiness():
            """Return readiness as changed by the simulated corpus completion."""
            return status

        async def quick(job_id, request):
            """Record evaluation only after readiness has been checked."""
            calls.append(job_id)
            return 1, None, tmp_path / "result.json"

        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            execution_coordinator=coordinator,
            corpus_status=readiness,
        )
        monkeypatch.setattr(service, "_quick", quick)
        request = EvaluationRunRequest(suite_id="sec-en")
        async with coordinator.turn("embedding-job"):
            first, duplicate = await asyncio.gather(
                service.enqueue(request),
                service.enqueue(request),
                return_exceptions=True,
            )
            assert isinstance(duplicate, EvaluationAlreadyQueuedError)
            assert duplicate.job_id == first.job_id
            assert first.message == "Waiting for backfill_embeddings embedding-job to finish."
            assert len(service._jobs) == 1
            assert calls == []
            if preparation_succeeds:
                status = replace(status, pending_embeddings=0, embedded_chunks=10)
        await service._queue.join()
        result = await service.job(first.job_id)
        assert result.status == ("succeeded" if preparation_succeeds else "failed")
        assert len(calls) == int(preparation_succeeds)
        if not preparation_succeeds:
            assert "step 3" in result.message

    asyncio.run(scenario())


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_evaluation_waiting_message_tracks_the_current_global_blocker(tmp_path):
    """Refresh every queued evaluation when the active corpus job advances to BM25."""

    async def scenario():
        """Advance a controlled queue without starting expensive evaluation work."""
        coordinator = JobExecutionCoordinator()
        now = datetime.now(UTC)
        await coordinator.register("embed", now, kind="backfill_embeddings")
        await coordinator.register("lexical", now, kind="rebuild_bm25")
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            execution_coordinator=coordinator,
        )
        async with coordinator.turn("embed"):
            first = await service.enqueue(EvaluationRunRequest(suite_id="sec-en"))
            second = await service.enqueue(EvaluationRunRequest(suite_id="sec-ko"))
            assert "embed" in second.message
        async with coordinator.turn("lexical"):
            assert "rebuild_bm25 lexical" in (await service.job(first.job_id)).message
            assert "rebuild_bm25 lexical" in (await service.job(second.job_id)).message
            await service.cancel(first.job_id)
            await service.cancel(second.job_id)
        await service._queue.join()
        assert coordinator.busy is False
        assert coordinator.has_kind("backfill_embeddings") is False

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "strategy,embeddings,bm25,allowed",
    [
        ("hybrid", False, True, False),
        ("hybrid", True, False, False),
        ("vector", True, False, True),
        ("lexical", False, True, True),
        ("hybrid", True, True, True),
    ],
)
def test_quick_evaluation_preparation_matches_the_selected_strategy(
    tmp_path, strategy, embeddings, bm25, allowed
):
    """Keep BM25 explicit while allowing vector or lexical profiles their independent ready lane."""

    async def status():
        """Return one corpus combination without provider or database work."""
        return CorpusStatus(
            True,
            "compatible",
            "ok",
            1,
            10,
            10 if embeddings else 0,
            0 if embeddings else 10,
            bm25,
            True,
            "deterministic",
        )

    service = EvaluationAdminService(
        settings=Settings(corpus_dir=tmp_path),
        provider=DeterministicEmbeddingProvider(),
        corpus_status=status,
    )
    request = EvaluationRunRequest(
        suite_id="sec-en",
        profile={"strategy": strategy, "lexical_ranker": None if strategy == "vector" else "bm25"},
    )
    if allowed:
        asyncio.run(service._require_preparation(request, allow_pending=False))
    else:
        with pytest.raises(ValueError, match="step [34]"):
            asyncio.run(service._require_preparation(request, allow_pending=False))


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_failed_durable_enqueue_does_not_leave_a_duplicate_reservation(tmp_path):
    """Allow retry after failed ledger creation without leaving a ghost queued job."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    async def scenario():
        """Fail one durable create, then confirm the same request receives a real queue ticket."""
        coordinator = JobExecutionCoordinator()
        await coordinator.register("blocker", datetime.now(UTC))
        store = SimpleNamespace(
            interrupt_incomplete=AsyncMock(),
            create=AsyncMock(side_effect=[RuntimeError("offline"), None]),
            put=AsyncMock(),
            cancel=AsyncMock(),
        )
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            job_store=store,
            execution_coordinator=coordinator,
        )
        request = EvaluationRunRequest(suite_id="sec-en")
        with pytest.raises(RuntimeError, match="offline"):
            await service.enqueue(request)
        assert not service._jobs
        job = await service.enqueue(request)
        assert service._queue.qsize() == 1
        assert list(service._jobs) == [job.job_id]
        # Cancel from the in-memory record; no retrieval or user DB is involved.
        service._job_store = None
        await service.cancel(job.job_id)
        await coordinator.cancel("blocker")
        await service._queue.join()
        await service._persister.flush(job.job_id)

    asyncio.run(scenario())


@pytest.mark.usefixtures("ready_evaluation_inputs")
def test_cancel_waits_for_queued_progress_before_persisting_terminal_state(tmp_path):
    """A delayed queued message must not overwrite a cancellation in the persistent job board."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    async def scenario():
        """Hold a queued metadata write, request cancellation, then release the stale write."""
        started = asyncio.Event()
        release = asyncio.Event()
        written = []

        async def put(job_id, **fields):
            """Delay the first queued snapshot to reproduce an out-of-order commit."""
            if fields["status"] == "queued":
                started.set()
                await release.wait()
            written.append(fields["status"])

        store = SimpleNamespace(interrupt_incomplete=AsyncMock(), create=AsyncMock(), put=put)
        coordinator = JobExecutionCoordinator()
        await coordinator.register("blocker", datetime.now(UTC), kind="backfill_embeddings")
        service = EvaluationAdminService(
            settings=Settings(corpus_dir=tmp_path),
            provider=DeterministicEmbeddingProvider(),
            job_store=store,
            execution_coordinator=coordinator,
        )
        job = await service.enqueue(EvaluationRunRequest(suite_id="sec-en"))
        await started.wait()
        cancellation = asyncio.create_task(service.cancel(job.job_id))
        await asyncio.sleep(0)
        assert not cancellation.done()
        release.set()
        assert (await cancellation).status == "cancelled"
        await service._queue.join()
        assert written == ["queued", "cancelled"]
        await coordinator.cancel("blocker")

    asyncio.run(scenario())
