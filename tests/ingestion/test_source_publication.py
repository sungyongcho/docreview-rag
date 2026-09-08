"""Fixed source lifecycle tests use only disposable local filing fixtures."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
from unittest.mock import patch

import pytest

from app.ingestion.acquisition import AcquiredFiling
from app.ingestion.manifest import Manifest
from app.ingestion.source_publication import publish_acquired
from app.ingestion.source_selection import record_selection, source_inventory
from app.ingestion.source_storage import JOURNAL
from tests.ingestion.support import write_selection_catalog


def test_repeated_publication_normalizes_legacy_duplicates_and_pins_inputs(tmp_path):
    """One current file survives revisions while an already queued input keeps its bytes."""
    catalog = write_selection_catalog(tmp_path)
    document = catalog.documents[0]
    artifact = next(a for a in catalog.artifacts if a.document_id == document.document_id)
    raw = artifact.read_bytes(tmp_path)
    duplicate = artifact.model_copy(
        update={"artifact_id": artifact.artifact_id + "-copy", "path": "copy.html"}
    )
    (tmp_path / duplicate.path).write_bytes(raw)
    catalog.model_copy(update={"artifacts": (*catalog.artifacts, duplicate)}).write(
        tmp_path / "manifest.json"
    )
    name, selected = record_selection(
        tmp_path, (document.issuer,), (document.fiscal_year,), (document.document_id,)
    )
    pinned = Manifest.read(tmp_path / name)
    normalized = publish_acquired(
        tmp_path / "manifest.json",
        [],
        selection_id="download",
        selected_document_ids=[document.document_id],
    )
    current = next(a for a in normalized.artifacts if a.document_id == document.document_id)
    assert current.path == f"sec/{document.filing_id}/primary.html"
    assert current.read_bytes(tmp_path) == raw
    assert not (tmp_path / artifact.path).exists()
    assert not (tmp_path / duplicate.path).exists()
    for body in (b"new source", raw):
        updated = current.model_copy(
            update={"sha256": hashlib.sha256(body).hexdigest(), "byte_length": len(body)}
        )
        normalized = publish_acquired(
            tmp_path / "manifest.json",
            [AcquiredFiling(document, (updated,), (body,))],
            selection_id="download",
            selected_document_ids=[document.document_id],
        )
        assert len([a for a in normalized.artifacts if a.document_id == document.document_id]) == 1
        assert (tmp_path / current.path).read_bytes() == body
        assert pinned.selected_sources(selected, tmp_path)[0].read().encode() == raw
    assert not (tmp_path / JOURNAL).exists()


def test_concurrent_publishers_preserve_other_filings_and_canonical_records(tmp_path):
    """Concurrent acquisition completions merge under one lock without lost catalog updates."""
    catalog = write_selection_catalog(tmp_path)
    filings = [
        AcquiredFiling(d, (a,), (a.read_bytes(tmp_path),))
        for d in catalog.documents
        for a in catalog.artifacts
        if a.document_id == d.document_id
    ]

    def publish(filing):
        """Complete one independently downloaded filing."""
        return publish_acquired(
            tmp_path / "manifest.json",
            [filing],
            selection_id=filing.document.document_id,
            selected_document_ids=[filing.document.document_id],
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(publish, [*filings, *filings]))
    result = Manifest.read(tmp_path / "manifest.json")
    assert len(result.documents) == len(result.artifacts) == 4
    assert all(row.ready for row in source_inventory(tmp_path))
    assert len(list((tmp_path / "sec").rglob("primary.html"))) == 4


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_failed_manifest_publication_restores_previous_original(tmp_path, failure):
    """Failures after file replacement restore the exact catalog and previous usable bytes."""
    import app.ingestion.source_storage as storage

    catalog = write_selection_catalog(tmp_path)
    document = catalog.documents[0]
    publish_acquired(
        tmp_path / "manifest.json",
        [],
        selection_id="first",
        selected_document_ids=[document.document_id],
    )
    before = (tmp_path / "manifest.json").read_bytes()
    current = next(
        a
        for a in Manifest.read(tmp_path / "manifest.json").artifacts
        if a.document_id == document.document_id
    )
    original = current.read_bytes(tmp_path)
    body = b"new complete source"
    updated = current.model_copy(
        update={"sha256": hashlib.sha256(body).hexdigest(), "byte_length": len(body)}
    )
    replace = storage.os.replace
    failed = False

    def fail_catalog(source, destination):
        """Interrupt only the first commit rename after the current file was replaced."""
        nonlocal failed
        if str(destination).endswith("/manifest.json") and not failed:
            failed = True
            raise failure("injected publication failure")
        return replace(source, destination)

    with patch.object(storage.os, "replace", fail_catalog), pytest.raises(failure):
        publish_acquired(
            tmp_path / "manifest.json",
            [AcquiredFiling(document, (updated,), (body,))],
            selection_id="new",
            selected_document_ids=[document.document_id],
        )
    assert (tmp_path / "manifest.json").read_bytes() == before
    assert current.read_bytes(tmp_path) == original
    assert not (tmp_path / JOURNAL).exists()


def test_inventory_caches_unchanged_bytes_but_detects_same_size_edits(tmp_path, monkeypatch):
    """Repeated UI refreshes stat files; changed bytes are revalidated before readiness."""
    from app.ingestion.manifest import SourceArtifact

    catalog = write_selection_catalog(tmp_path)
    original = SourceArtifact.read
    reads = []

    def counted(self, root):
        """Count real integrity reads without replacing their validation."""
        reads.append(self.path)
        return original(self, root)

    monkeypatch.setattr(SourceArtifact, "read", counted)
    assert all(row.ready for row in source_inventory(tmp_path))
    first = len(reads)
    assert first == 4
    assert all(row.ready for row in source_inventory(tmp_path))
    assert len(reads) == first
    artifact = catalog.artifacts[0]
    (tmp_path / artifact.path).write_bytes(b"x" * artifact.byte_length)
    row = next(row for row in source_inventory(tmp_path) if row.document_id == artifact.document_id)
    assert row.on_disk and not row.ready
    assert len(reads) == first + 1
    with pytest.raises(ValueError, match="not ready"):
        record_selection(tmp_path, (row.issuer,), (row.fiscal_year,), (row.document_id,))


def test_interrupted_process_recovers_before_the_next_publication(tmp_path, monkeypatch):
    """A retained journal proves how to undo a crash before the catalog commit."""
    import app.ingestion.source_storage as storage

    catalog = write_selection_catalog(tmp_path)
    document = catalog.documents[0]
    publish_acquired(
        tmp_path / "manifest.json",
        [],
        selection_id="first",
        selected_document_ids=[document.document_id],
    )
    old = Manifest.read(tmp_path / "manifest.json")
    current = next(a for a in old.artifacts if a.document_id == document.document_id)
    original = current.read_bytes(tmp_path)
    body = b"replacement before crash"
    updated = current.model_copy(
        update={"sha256": hashlib.sha256(body).hexdigest(), "byte_length": len(body)}
    )
    replace = storage.os.replace

    def stop_catalog(source, destination):
        """Leave the durable journal after replacing bytes but before catalog publication."""
        if str(destination).endswith("/manifest.json"):
            raise OSError("process stopped")
        return replace(source, destination)

    def unavailable_recovery(root):
        """Simulate a process exit before in-process rollback can execute."""
        raise KeyboardInterrupt("process exited")

    with (
        patch.object(storage.os, "replace", stop_catalog),
        patch.object(storage, "recover_transaction", unavailable_recovery),
        pytest.raises(KeyboardInterrupt),
    ):
        publish_acquired(
            tmp_path / "manifest.json",
            [AcquiredFiling(document, (updated,), (body,))],
            selection_id="new",
            selected_document_ids=[document.document_id],
        )
    assert (tmp_path / JOURNAL / "record.json").exists()
    assert not next(
        row for row in source_inventory(tmp_path) if row.document_id == document.document_id
    ).ready
    with storage.source_lock(tmp_path, recover=True):
        assert current.read_bytes(tmp_path) == original
    assert not (tmp_path / JOURNAL).exists()
    assert Manifest.read(tmp_path / "manifest.json") == old
