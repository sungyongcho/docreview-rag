"""Corpus status probe, manifest summary and snapshot tests."""

import asyncio
import json
from pathlib import Path

import pytest

from app.config import Settings
import app.corpus_admin.inspection as inspection
from app.corpus_admin.runtime import RuntimeCorpusAdminService
from tests.corpus_admin.support import write_manifest
from tests.live_postgres import live_postgres_unavailable


def test_manifest_summaries_report_registry_and_sources_on_disk(tmp_path: Path) -> None:
    """Expose exact selection identities from the common catalog."""
    write_manifest(tmp_path)
    (tmp_path / "broken-manifest.json").write_text("{")
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))
    summaries = {item.name: item for item in service._inspector.manifest_summaries()}
    summary = summaries["manifest.json"]
    assert summary.registries == ("sec",)
    assert summary.documents == 1
    assert summary.sources_present == 1
    assert summary.selections[0].document_ids == ("nvda-2024",)
    assert summary.selections[0].artifact_ids == ("nvda-source",)
    assert summary.selections[0].sources_present == 1
    assert summaries["broken-manifest.json"].valid is False


def test_manifest_file_counts_do_not_count_archives_as_extra_filings(tmp_path):
    """A primary source and its archive represent one available filing."""
    write_manifest(tmp_path)
    path = tmp_path / "manifest.json"
    payload = json.loads(path.read_text())
    artifact = dict(payload["artifacts"][0])
    artifact.update(artifact_id="archive-copy", role="archive", path="archive.zip", encoding=None)
    (tmp_path / "archive.zip").write_bytes(b"archive")
    payload["artifacts"].append(artifact)
    path.write_text(json.dumps(payload))
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))
    summary = service._inspector.manifest_summaries()[0]
    assert summary.valid is True
    assert summary.sources_present == 1
    assert summary.documents == 1


def test_manifest_companies_are_available_before_source_download(tmp_path):
    """Project source registry and company labels without requiring ingested rows or bytes."""
    write_manifest(tmp_path)
    path = tmp_path / "manifest.json"
    payload = json.loads(path.read_text())
    payload["documents"][0]["aliases"] = ["NVDA", "NVIDIA"]
    path.write_text(json.dumps(payload))
    (tmp_path / "report.html").unlink()
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))
    summary = service._inspector.manifest_summaries()[0]
    assert summary.sources_present == 0
    assert [(item.registry, item.issuer, item.name) for item in summary.issuers] == [
        ("sec", "NVDA", "NVIDIA")
    ]


def test_schema_drift_does_not_misreport_source_permissions(tmp_path, monkeypatch):
    """A schema mismatch must not masquerade as an unwritable corpus directory."""
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))

    async def drifted():
        """Report only the database mismatch."""
        return "drifted", "Missing source relationship columns", set()

    monkeypatch.setattr(service._inspector, "schema_state", drifted)
    snapshot = asyncio.run(service.snapshot())
    assert snapshot.status.schema_status == "drifted"
    assert snapshot.status.writable is True


def _status_service(tmp_path, monkeypatch, *, tables=None):
    """Build a service whose schema and count probes are counted and never load documents."""
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))
    calls = {"schema": 0, "counts": 0}
    present = tables if tables is not None else {"documents", "chunks", "bm25_corpus_stats"}

    async def compatible():
        """Report one compatible schema and count the measurement."""
        calls["schema"] += 1
        return "compatible", "ok", set(present)

    async def counts(_tables):
        """Report fixed counts and count the measurement."""
        calls["counts"] += 1
        return 3, 30, 30, True

    async def documents(_tables):
        """Fail if the status path ever loads document rows."""
        raise AssertionError("status must not load document rows")

    monkeypatch.setattr(service._inspector, "schema_state", compatible)
    monkeypatch.setattr(service._inspector, "_counts", counts)
    monkeypatch.setattr(service._inspector, "_documents", documents)
    return service, calls


def test_status_reuses_a_fresh_probe_and_never_loads_document_rows(tmp_path, monkeypatch):
    """Two status reads inside the window measure once and skip document rows entirely."""
    service, calls = _status_service(tmp_path, monkeypatch)

    async def scenario():
        """Read the status twice within one two-second window."""
        first = await service.status(max_age_s=2.0)
        second = await service.status(max_age_s=2.0)
        return first, second

    first, second = asyncio.run(scenario())
    assert (first.documents, first.chunks, first.embedded_chunks, first.bm25_ready) == (
        3,
        30,
        30,
        True,
    )
    assert first.pending_embeddings == 0
    assert first.writable is True
    assert second == first
    assert calls == {"schema": 1, "counts": 1}


def test_status_recomputes_after_the_max_age_and_on_invalidation(tmp_path, monkeypatch):
    """A reading older than the window, an invalidation, or a zero window measures again."""
    service, calls = _status_service(tmp_path, monkeypatch)
    clock = {"now": 100.0}
    monkeypatch.setattr(inspection.time, "monotonic", lambda: clock["now"])

    async def scenario():
        """Age the memo past the window, invalidate it, then demand a fresh reading."""
        await service.status(max_age_s=2.0)
        clock["now"] += 1.0
        await service.status(max_age_s=2.0)
        clock["now"] += 2.0
        await service.status(max_age_s=2.0)
        service.invalidate_status()
        await service.status(max_age_s=2.0)
        await service.status(max_age_s=0.0)

    asyncio.run(scenario())
    assert calls["schema"] == 4


def test_snapshot_refreshes_the_status_memo(tmp_path, monkeypatch):
    """snapshot() always measures and its reading serves the next status() in the window."""
    service, calls = _status_service(tmp_path, monkeypatch)

    async def documents(_tables):
        """Return no document rows for the administrator table."""
        return ()

    monkeypatch.setattr(service._inspector, "_documents", documents)

    async def scenario():
        """Take a snapshot, a cached status, then a second fresh snapshot."""
        snapshot = await service.snapshot()
        status = await service.status(max_age_s=2.0)
        await service.snapshot()
        return snapshot, status

    snapshot, status = asyncio.run(scenario())
    assert status == snapshot.status
    assert calls["schema"] == 2


@pytest.mark.live_postgres
def test_live_postgres_admin_snapshot_reports_schema_state() -> None:
    """Inspect the real configured database without mutating its corpus or schema."""
    try:
        snapshot = asyncio.run(RuntimeCorpusAdminService().snapshot())
    except Exception as error:  # noqa: BLE001 - shared live-test availability policy
        live_postgres_unavailable(str(error))

    if not snapshot.status.database_connected:
        live_postgres_unavailable(snapshot.status.schema_message)
    assert snapshot.status.schema_status in {"compatible", "empty", "drifted"}
    if snapshot.status.schema_status == "drifted":
        assert isinstance(snapshot.status.writable, bool)
        assert "DROP TABLE" not in snapshot.status.schema_message


@pytest.mark.live_postgres
def test_live_postgres_admin_status_matches_snapshot_status() -> None:
    """The status path reports the same non-secret status as the full snapshot."""
    service = RuntimeCorpusAdminService()

    async def both():
        """Take one full snapshot and one fresh status reading on this event loop."""
        # The shared engine may hold connections opened by an earlier asyncio.run loop;
        # recycle them so this reading measures the database, not a stale pool.
        from app.db.session import engine

        await engine.dispose()
        return await service.snapshot(), await service.status(max_age_s=0.0)

    try:
        snapshot, status = asyncio.run(both())
    except Exception as error:  # noqa: BLE001 - shared live-test availability policy
        live_postgres_unavailable(str(error))

    if not status.database_connected:
        live_postgres_unavailable(status.schema_message)
    assert status == snapshot.status
