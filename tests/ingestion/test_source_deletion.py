"""Exact source deletion approvals never delete derived or past job inputs."""

import asyncio

import pytest

from app.config import Settings
from app.corpus_admin import AdminCommand, RuntimeCorpusAdminService
from app.ingestion.manifest import Manifest
from app.ingestion.source_deletion import SourceDeletion
from app.ingestion.source_selection import record_selection, source_inventory
from tests.ingestion.support import write_selection_catalog


def test_preview_cancel_and_confirm_have_separate_effects(tmp_path):
    """Preview leaves files unchanged; confirmation deletes originals but retains pinned inputs."""
    catalog = write_selection_catalog(tmp_path)
    document = catalog.documents[0]
    artifact = next(a for a in catalog.artifacts if a.document_id == document.document_id)
    name, selection_id = record_selection(
        tmp_path, (document.issuer,), (document.fiscal_year,), (document.document_id,)
    )
    original = artifact.read_bytes(tmp_path)
    sentinel = tmp_path / "unrelated.html"
    sentinel.write_text("keep")
    before = (tmp_path / "manifest.json").read_bytes()
    service = SourceDeletion(tmp_path)
    preview = service.preview((document.document_id,))
    assert preview["retained_derived"] and preview["retained_inputs"] == 1
    assert preview["documents"][0]["filing_id"] == document.filing_id
    assert (tmp_path / "manifest.json").read_bytes() == before
    assert artifact.read_bytes(tmp_path) == original
    service.reserve(preview["token"])
    summary = service.execute(preview["token"])
    assert "Deleted 1" in summary
    assert not (tmp_path / artifact.path).exists()
    assert sentinel.read_text() == "keep"
    assert (
        Manifest.read(tmp_path / name).selected_sources(selection_id, tmp_path)[0].read().encode()
        == original
    )
    assert len(Manifest.read(tmp_path / "manifest.json").documents) == len(catalog.documents)
    row = next(row for row in source_inventory(tmp_path) if row.document_id == document.document_id)
    assert not row.ready and not row.on_disk
    with pytest.raises(ValueError, match="already used"):
        service.reserve(preview["token"])
    with pytest.raises(ValueError, match="not ready"):
        record_selection(
            tmp_path, (document.issuer,), (document.fiscal_year,), (document.document_id,)
        )


@pytest.mark.parametrize("change", ["file", "manifest", "expiry", "restart"])
def test_changed_expired_or_replayed_approvals_cannot_delete(tmp_path, monkeypatch, change):
    """A queued confirmation grants no authority over changed or newly discovered state."""
    import app.ingestion.source_deletion as deletion

    catalog = write_selection_catalog(tmp_path)
    target = catalog.artifacts[0]
    service = SourceDeletion(tmp_path)
    preview = service.preview((target.document_id,))
    service.reserve(preview["token"])
    if change == "file":
        (tmp_path / target.path).write_text("foreign new bytes")
    elif change == "manifest":
        catalog.model_copy(update={"selections": ()}).write(tmp_path / "manifest.json")
        # Ensure drift even when the fixture catalog already has no selections.
        with (tmp_path / "manifest.json").open("a") as output:
            output.write(" ")
    elif change == "expiry":
        monkeypatch.setattr(deletion.time, "time", lambda: preview["expires_at"] + 1)
    else:
        service = SourceDeletion(tmp_path)
    before = (tmp_path / target.path).read_bytes()
    with pytest.raises(ValueError):
        service.execute(preview["token"])
    assert (tmp_path / target.path).read_bytes() == before


def test_shared_legacy_input_is_retained_and_only_current_registration_is_removed(tmp_path):
    """A legacy job manifest retains its exact original path when clearing current sources."""
    catalog = write_selection_catalog(tmp_path)
    catalog.write(tmp_path / "selected-legacy-manifest.json")
    target = catalog.artifacts[0]
    service = SourceDeletion(tmp_path)
    preview = service.preview((target.document_id,))
    assert preview["files"][0]["retained"] is True
    service.reserve(preview["token"])
    assert "Deleted 0" in service.execute(preview["token"])
    assert (tmp_path / target.path).exists()
    assert all(
        a.document_id != target.document_id
        for a in Manifest.read(tmp_path / "manifest.json").artifacts
    )


def test_queue_requires_fresh_confirmation_and_cannot_retry_deletion(tmp_path):
    """The normal corpus queue records honest deletion outcomes without touching a database."""
    catalog = write_selection_catalog(tmp_path)

    async def scenario():
        """Exercise service queue validation and terminal provenance in a disposable corpus."""
        service = RuntimeCorpusAdminService(settings=Settings(mode="dev", corpus_dir=tmp_path))
        preview = await service.preview_source_deletion((catalog.documents[0].document_id,))
        command = AdminCommand(
            "delete_sources", deletion_token=preview["token"], confirm_delete=True
        )
        (tmp_path / catalog.artifacts[0].path).write_text("changed after preview")
        job = await service.enqueue(command)
        await service._queue.join()
        assert (await service.jobs()).history[0].status == "failed"
        with pytest.raises(ValueError, match="cannot be retried"):
            await service.retry(job.job_id)

    asyncio.run(scenario())
    with pytest.raises(ValueError, match="confirmation"):
        AdminCommand("delete_sources")
