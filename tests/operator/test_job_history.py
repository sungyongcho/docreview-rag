"""History maintenance against an explicitly isolated PostgreSQL schema."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import OperatorJob
from app.operator.job_history import ARCHIVE_KEY, HistoryConflictError, JobHistoryService
from app.operator.jobs import JobStore


@asynccontextmanager
async def isolated_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Create only a unique test schema on the dedicated isolated database port."""
    url_text = os.environ.get("DOCREVIEW_HISTORY_TEST_DATABASE_URL")
    if not url_text:
        pytest.skip("Set DOCREVIEW_HISTORY_TEST_DATABASE_URL to the isolated port 55439")
    url = make_url(url_text)
    if url.host not in ("localhost", "127.0.0.1") or url.port != 55439:
        pytest.fail("History tests require localhost port 55439; refusing another database")
    schema = f"history_test_{uuid4().hex}"
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url, poolclass=NullPool, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(OperatorJob.__table__.create)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


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
def test_archive_restore_and_backed_up_delete(tmp_path: Path) -> None:
    """Archive visibility, restore it, then back up complete terminal rows before deletion."""

    async def scenario() -> None:
        """Exercise the service and production list filter in an isolated schema."""
        async with isolated_factory() as factory:
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
        async with isolated_factory() as factory:
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


def test_backup_paths_reject_traversal_symlinks_and_public_files(tmp_path: Path) -> None:
    """Allow canonical private UUID files only, including directory ownership checks."""
    directory = tmp_path / "backups"
    directory.mkdir(mode=0o700)
    service = JobHistoryService(lambda: None, directory)  # type: ignore[arg-type, return-value]
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
        JobHistoryService(lambda: None, linked_directory).backup_path(backup_id)  # type: ignore[arg-type, return-value]
