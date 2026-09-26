"""Corpus job queue ordering, cancellation, retry and ledger persistence tests."""

import asyncio
from dataclasses import replace
from pathlib import Path

from pydantic import SecretStr
import pytest

from app.config import Settings
from app.corpus_admin.runtime import RuntimeCorpusAdminService
from app.corpus_admin.types import AdminCommand, OperationOutcome
from app.ingestion.progress import OperationProgress
from app.operator.corpus_access import JobCancelledError
from app.operator.progress import PROGRESS_KEY, stored_progress
from tests.corpus_admin.support import LedgerStore


def test_runtime_queue_runs_one_job_at_a_time_in_submission_order(tmp_path: Path) -> None:
    """Run one job at a time and preserve submission order in bounded history."""

    async def scenario() -> None:
        """Queue two jobs and verify FIFO execution and history."""
        gate = asyncio.Event()
        calls: list[str] = []

        async def runner(command, publish) -> OperationOutcome:
            """Record order while keeping the first job active long enough to queue another."""
            calls.append(command.kind)
            publish(OperationProgress("work", 1, 2, f"running {command.kind}"))
            if len(calls) == 1:
                await gate.wait()
            publish(OperationProgress("work", 2, 2, f"finished {command.kind}"))
            return OperationOutcome(f"completed {command.kind}")

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            operation_runner=runner,
        )
        first = await service.enqueue(AdminCommand("rebuild_bm25"))
        second = await service.enqueue(AdminCommand("backfill_embeddings"))
        await asyncio.sleep(0)
        board = await service.jobs()
        assert board.active is not None
        assert board.active.job_id == first.job_id
        assert [job.job_id for job in board.queued] == [second.job_id]

        gate.set()
        await service._job_queue._queue.join()
        board = await service.jobs()

        assert calls == ["rebuild_bm25", "backfill_embeddings"]
        assert board.active is None
        assert [job.status for job in board.history] == ["succeeded", "succeeded"]
        assert [job.command.kind for job in board.history] == [
            "backfill_embeddings",
            "rebuild_bm25",
        ]

    asyncio.run(scenario())


def test_failed_job_is_redacted_and_retryable(tmp_path: Path) -> None:
    """Remove server credentials from failure history and permit a bounded retry."""

    async def scenario() -> None:
        """Fail once with a secret, then retry successfully."""
        attempts = 0
        secret = "dart-test-secret-123"

        async def runner(command, publish) -> OperationOutcome:
            """Fail once with a secret-bearing message, then succeed."""
            nonlocal attempts
            del command, publish
            attempts += 1
            if attempts == 1:
                raise RuntimeError(f"provider rejected {secret}")
            return OperationOutcome("retry succeeded")

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path, dart_api_key=SecretStr(secret)),
            operation_runner=runner,
        )
        failed = await service.enqueue(AdminCommand("backfill_embeddings"))
        await service._job_queue._queue.join()
        board = await service.jobs()
        assert board.history[0].status == "failed"
        assert secret not in board.history[0].message
        assert "[REDACTED]" in board.history[0].message

        retried = await service.retry(failed.job_id)
        await service._job_queue._queue.join()
        board = await service.jobs()
        assert retried.job_id != failed.job_id
        assert board.history[0].status == "succeeded"
        assert board.history[0].result_refs is not None
        assert board.history[0].result_refs["retry_of"] == failed.job_id

    asyncio.run(scenario())


def test_queued_job_can_be_cancelled_without_running(tmp_path: Path) -> None:
    """Remove queued work at dispatch time while allowing the active job to finish."""

    async def scenario() -> None:
        """Hold the first job, cancel the second, and inspect terminal history."""
        gate = asyncio.Event()
        calls: list[str] = []

        async def runner(command, publish) -> OperationOutcome:
            """Block the first command long enough to cancel its successor."""
            del publish
            calls.append(command.kind)
            await gate.wait()
            return OperationOutcome("done")

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            operation_runner=runner,
        )
        first = await service.enqueue(AdminCommand("rebuild_bm25"))
        second = await service.enqueue(AdminCommand("backfill_embeddings"))
        await asyncio.sleep(0)
        cancelled = await service.cancel(second.job_id)
        gate.set()
        await service._job_queue._queue.join()
        board = await service.jobs()

        assert calls == [first.command.kind]
        assert cancelled.status == "cancelled"
        assert {job.status for job in board.history} == {"succeeded", "cancelled"}

    asyncio.run(scenario())


def test_running_backfill_cancels_at_the_next_batch_boundary(tmp_path: Path) -> None:
    """Cooperatively stop only a running operation with a declared safe boundary."""

    async def scenario() -> None:
        """Request cancellation while a fake embedding batch is in flight."""
        gate = asyncio.Event()

        async def runner(command, publish) -> OperationOutcome:
            """Publish once, wait, then hit the cancellation-aware boundary."""
            assert command.kind == "backfill_embeddings"
            publish(OperationProgress("embedding", 1, 2, "first batch"))
            await gate.wait()
            publish(OperationProgress("embedding", 2, 2, "second batch"))
            return OperationOutcome("unexpected completion")

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            operation_runner=runner,
        )
        job = await service.enqueue(AdminCommand("backfill_embeddings"))
        await asyncio.sleep(0)
        cancelled = await service.cancel(job.job_id)
        gate.set()
        await service._job_queue._queue.join()
        board = await service.jobs()

        assert cancelled.status == "cancelled"
        assert board.history[0].status == "cancelled"
        assert board.history[0].message == "Cancelled by operator."
        assert (board.history[0].current, board.history[0].total) == (1, 2)

    asyncio.run(scenario())


def test_worker_survives_ledger_failures_and_lands_the_terminal_state(tmp_path: Path) -> None:
    """Keep the queue alive when ledger writes fail, coalesce progress, and persist success last."""

    async def scenario() -> None:
        """Fail the first two writes, then require succeeded rows and a live worker."""
        store = LedgerStore(failures=2)

        async def runner(command, publish) -> OperationOutcome:
            """Publish a burst of progress in one turn, then finish."""
            for step in range(1, 6):
                publish(OperationProgress("work", step, 5, f"{command.kind} {step}"))
            await asyncio.sleep(0)
            return OperationOutcome(f"completed {command.kind}")

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path),
            operation_runner=runner,
            job_store=store,
        )
        first = await service.enqueue(AdminCommand("rebuild_bm25"))
        await service._job_queue._queue.join()
        second = await service.enqueue(AdminCommand("backfill_embeddings"))
        await service._job_queue._queue.join()

        assert store.rows[first.job_id].status == "succeeded"
        assert store.rows[second.job_id].status == "succeeded"
        assert store.rows[second.job_id].current == 5
        # Ten progress events became at most one running write per job, and the
        # succeeded write is always the last one for each job.
        assert store.puts.count("running") <= 2
        assert store.puts[-1] == "succeeded"
        assert [job.status for job in (await service.jobs()).history] == ["succeeded", "succeeded"]

    asyncio.run(scenario())


def test_acquisition_result_keeps_selection_in_completed_job(tmp_path):
    """Keep machine-readable acquisition provenance on the shared job board."""

    async def scenario():
        """Complete an injected operation through the real job queue."""

        async def runner(command, publish):
            """Return the same structured result as acquisition adapters."""
            return OperationOutcome("Fetched 1 filing", "manifest.json", "selected")

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path), operation_runner=runner
        )
        await service.enqueue(AdminCommand("acquire_edgar", identifiers=("NVDA",), years=(2024,)))
        await service._job_queue._queue.join()
        job = (await service.jobs()).history[0]
        assert job.status == "succeeded"
        progress = stored_progress(job.result_refs)
        assert progress is not None
        assert progress.overall_current == 100
        assert job.result_refs is not None
        assert {key: value for key, value in job.result_refs.items() if key != PROGRESS_KEY} == {
            "manifest": "manifest.json",
            "selection_id": "selected",
            "summary": "Fetched 1 filing",
        }

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["succeeded", "failed", "cancelled"])
def test_embedding_usage_survives_job_transitions(tmp_path, outcome):
    """Preserve charged usage through progress, failure and cancellation writes."""
    from decimal import Decimal

    from app.observability.usage import USAGE_KEY, UsageSink, provider_identity, usage_record

    async def scenario():
        """Use the bounded in-memory ledger to exercise real worker transition code."""
        store = LedgerStore()
        service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path), job_store=store)

        async def operation(command, publish, on_usage: UsageSink | None = None):
            """Record two provider responses before selecting the terminal outcome."""
            # The job queue always passes its usage recorder to the operation it runs.
            assert on_usage is not None
            record = usage_record(
                identity=provider_identity(
                    provider="openai_embeddings", local=False, credential_slot="dev"
                ),
                model_name="text-embedding-3-large",
                role="embedding",
                input_tokens=12,
                estimated_cost_usd=Decimal("0.0001"),
            )
            await on_usage(record)
            publish(OperationProgress("embedding", 1, 2, "first batch"))
            await on_usage(record)
            if outcome == "failed":
                raise ValueError("fixture failed after provider response")
            if outcome == "cancelled":
                raise JobCancelledError("fixture cancellation")
            return OperationOutcome("completed")

        service._job_queue._run_operation = operation
        job = await service.enqueue(AdminCommand("backfill_embeddings"))
        await service._job_queue._queue.join()
        stored = store.rows[job.job_id]
        assert stored.status == outcome
        usage = stored.result_refs[USAGE_KEY]
        assert isinstance(usage, list)
        assert usage[0]["requests"] == 2
        assert usage[0]["input_tokens"] == 24

    asyncio.run(scenario())


def test_restored_embedding_usage_ledger_cannot_be_retried_or_read_as_a_command(tmp_path):
    """An archived usage event stays non-executable even if history is restored manually."""

    async def scenario():
        """Use a restored terminal ledger without reaching a database or provider."""
        store = LedgerStore()
        row = await store.create(
            job_id="usage-ledger",
            domain="corpus",
            kind="embedding_usage",
            request_json={"executable": False},
        )
        store.rows[row.job_id] = replace(row, status="failed")
        service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path), job_store=store)
        assert not (await service.jobs()).history
        with pytest.raises(ValueError, match="cannot be executed"):
            await service.retry(row.job_id)

    asyncio.run(scenario())


def test_historical_ingestion_without_selection_is_refused_on_retry(tmp_path):
    """An old ingest row without a selection stays unexecutable when its retry is requested."""

    async def scenario():
        """Retry one restored failed row without reaching a database or provider."""
        store = LedgerStore()
        row = await store.create(
            job_id="old-ingest",
            domain="corpus",
            kind="ingest_manifest",
            request_json={"manifest": "manifest.json"},
        )
        store.rows[row.job_id] = replace(row, status="failed")
        service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path), job_store=store)
        with pytest.raises(ValueError, match="manifest and selection_id"):
            await service.retry(row.job_id)
        assert list(store.rows) == [row.job_id]

    asyncio.run(scenario())


def test_corpus_job_waits_for_search_before_running(tmp_path: Path) -> None:
    """The actual job worker drains an admitted search before starting an index update."""

    async def exercise():
        called = asyncio.Event()

        async def runner(command, publish):
            """Observe when the worker is permitted to mutate the index."""
            called.set()
            return OperationOutcome("indexed")

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path), operation_runner=runner
        )
        async with service.corpus_access.search():
            await service.enqueue(AdminCommand("rebuild_bm25"))
            await asyncio.sleep(0)
            assert service.corpus_access.updating
            assert not called.is_set()
        await asyncio.wait_for(service._job_queue._queue.join(), 1)
        assert called.is_set()
        assert not service.corpus_access.updating

    asyncio.run(exercise())
