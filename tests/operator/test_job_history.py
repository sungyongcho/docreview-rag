"""History maintenance against an explicitly isolated PostgreSQL schema."""

import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import OperatorJob
from app.operator.job_history import ARCHIVE_KEY, HistoryConflictError, JobHistoryService
from app.operator.jobs import JobStore
from tests.live_postgres import isolated_session_factory


async def seed(factory: async_sessionmaker[AsyncSession]) -> None:
    """Insert six statuses with recognizable references and full serializable records."""
    async with factory() as session, session.begin():
        for status in ("queued", "running", "succeeded", "failed", "interrupted", "cancelled"):
            session.add(
                OperatorJob(
                    job_id=status,
                    domain="corpus",
                    kind="ingest_manifest",
                    request_json={"source": "keep-source.html"},
                    status=status,
                    stage=status,
                    current=2,
                    total=4,
                    message="Unicode evidence: 한글",
                    result_refs={"result_id": "keep-result", "files": ["keep-source.html"]},
                    created_at=datetime.now(UTC),
                )
            )


@pytest.mark.live_postgres
def test_restored_evaluation_is_visible_without_restarting_its_service(tmp_path: Path) -> None:
    """Read restored evaluation history from PostgreSQL in the already running service."""
    from app.api.admin_schemas import EvaluationRunRequest
    from app.config import Settings
    from app.evals.admin import EvaluationAdminService
    from app.retrieval.embeddings import DeterministicEmbeddingProvider

    async def scenario() -> None:
        """Archive before service startup, then restore through the real history owner."""
        async with isolated_session_factory() as factory:
            store = JobStore(session_factory=factory)
            request = EvaluationRunRequest(suite_id="sec-en")
            created = await store.create(
                job_id="restored-evaluation",
                domain="evaluation",
                kind="quick",
                request_json=request.model_dump(mode="json"),
            )
            await store.put(
                created.job_id,
                status="failed",
                stage="failed",
                current=2,
                total=3,
                detail_current=None,
                detail_total=None,
                message="Recorded evaluation failure",
                started_at=created.created_at,
                finished_at=datetime.now(UTC),
                error_code="evaluation_failed",
            )
            history = JobHistoryService(factory, tmp_path / "backups")
            await history.apply("archive", 1)
            evaluations = EvaluationAdminService(
                settings=Settings(corpus_dir=tmp_path),
                session_factory=factory,
                provider=DeterministicEmbeddingProvider(),
                job_store=store,
            )
            assert (await evaluations.jobs()).jobs == ()
            await history.apply("restore", 1)
            restored = (await evaluations.jobs()).jobs
            assert len(restored) == 1
            assert restored[0].job_id == created.job_id
            assert restored[0].request == request
            assert restored[0].status == "failed"
            assert (restored[0].current, restored[0].total) == (2, 3)
            assert restored[0].message == "Recorded evaluation failure"

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_archive_restore_and_backed_up_delete(tmp_path: Path) -> None:
    """Archive visibility, restore it, then back up complete terminal rows before deletion."""

    async def scenario() -> None:
        """Exercise the service and production list filter in an isolated schema."""
        async with isolated_session_factory() as factory:
            await seed(factory)
            service = JobHistoryService(factory, tmp_path / "backups")
            store = JobStore(session_factory=factory)
            assert (await service.summary()).visible == 4
            result = await service.apply("archive", 4)
            assert len(result.changed_ids) == 4
            assert result.backup_id is None
            assert {job.job_id for job in await store.list()} == {"queued", "running"}
            assert len(await store.list(include_archived=True)) == 6
            summary = await service.summary()
            assert (summary.visible, summary.archived, summary.active) == (0, 4, 2)
            with pytest.raises(HistoryConflictError):
                await service.apply("restore", 3)
            assert len((await service.apply("restore", 4)).changed_ids) == 4
            for job in await store.list():
                assert ARCHIVE_KEY not in job.result_refs
                assert job.result_refs["result_id"] == "keep-result"
            with pytest.raises(ValueError, match="DELETE JOB HISTORY"):
                await service.apply("delete", 4, "DELETE")
            with pytest.raises(HistoryConflictError):
                await service.apply("delete", 5, "DELETE JOB HISTORY")
            assert not (tmp_path / "backups").exists()
            result = await service.apply("delete", 4, "DELETE JOB HISTORY")
            assert result.backup_id
            backup = service.backup_path(result.backup_id)
            assert backup.stat().st_mode & 0o777 == 0o600
            assert backup.parent.stat().st_mode & 0o777 == 0o700
            records = json.loads(backup.read_text())["records"]
            assert {record["job_id"] for record in records} == set(result.changed_ids)
            assert set(records[0]) == set(OperatorJob.__table__.columns.keys())
            assert records[0]["result_refs"]["files"] == ["keep-source.html"]
            assert records[0]["created_at"]
            assert {job.job_id for job in await store.list(include_archived=True)} == {
                "queued",
                "running",
            }
            assert (await service.summary()).active == 2

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_backup_failure_preserves_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail backup publication and prove that neither archived nor visible rows disappear."""

    async def scenario() -> None:
        """Raise at atomic publication after the temporary backup has been written."""
        async with isolated_session_factory() as factory:
            await seed(factory)
            service = JobHistoryService(factory, tmp_path / "backups")
            await service.apply("archive", 4)

            def fail_replace(*_args: object) -> None:
                """Simulate a filesystem failure at backup publication."""
                raise OSError("Backup disk unavailable")

            monkeypatch.setattr("app.operator.job_history.os.replace", fail_replace)
            with pytest.raises(OSError, match="Backup disk unavailable"):
                await service.apply("delete", 4, "DELETE JOB HISTORY")
            async with factory() as session:
                assert len(tuple(await session.scalars(select(OperatorJob)))) == 6
            assert (await service.summary()).archived == 4
            assert list((tmp_path / "backups").iterdir()) == []

    asyncio.run(scenario())


def unused_session_factory() -> AsyncSession:
    """Stand in for the session factory where only backup paths are validated."""
    raise AssertionError("backup path validation must not open a database session")


def test_backup_paths_reject_traversal_symlinks_and_public_files(tmp_path: Path) -> None:
    """Allow canonical private UUID files only, including directory ownership checks."""
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    service = JobHistoryService(unused_session_factory, directory)
    backup_id = str(uuid4())
    target = directory / f"{backup_id}.json"
    target.write_text("{}")
    with pytest.raises(ValueError):
        service.backup_path("../outside")
    target.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        service.backup_path(backup_id)
    target.chmod(0o600)
    assert service.backup_path(backup_id) == target
    link_id = str(uuid4())
    (directory / f"{link_id}.json").symlink_to(target)
    with pytest.raises(ValueError):
        service.backup_path(link_id)
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        JobHistoryService(unused_session_factory, linked_directory).backup_path(backup_id)
