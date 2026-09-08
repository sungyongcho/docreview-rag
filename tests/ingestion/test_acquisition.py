"""Common artifact publication and named selection behavior."""

from dataclasses import replace

import pytest

from app.ingestion.acquisition import (
    AcquiredFiling,
    current_primary,
    publish_bytes,
    read_catalog,
    selection_identity,
)
from app.ingestion.manifest import Manifest
from app.ingestion.source_publication import publish_acquired
from tests.ingestion.support import acquired_filing, filing_document, filing_source


def test_public_source_bytes_remain_readable_across_runtime_users(tmp_path):
    """Share public filing artifacts between host and container readers."""
    path = publish_bytes(tmp_path, "source.html", b"public evidence")
    assert path.read_bytes() == b"public evidence"
    assert path.stat().st_mode & 0o044 == 0o044


def test_atomic_publication_refuses_traversal_and_symlink_escape(tmp_path):
    """Confine publication even when a relative path crosses a symlink."""
    root = tmp_path / "corpus"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    for path in ("../outside/file.html", "/absolute.html", "escape/file.html"):
        with pytest.raises(ValueError):
            publish_bytes(root, path, b"evidence")
    assert list(outside.iterdir()) == []


def test_mixed_catalog_retains_existing_selection_and_source_identities(tmp_path):
    """A current DART ZIP/XML pair preserves the existing SEC identity and exact selection."""
    sec = acquired_filing(tmp_path, payload=b"SEC source")
    dart = acquired_filing(
        tmp_path,
        document=filing_document(registry="dart", document_id="opaque-dart-id"),
        payload=b"<DOCUMENT>DART source</DOCUMENT>",
    )
    for label, filing in (("sec", sec), ("dart", dart)):
        publish_acquired(
            tmp_path / "manifest.json",
            [filing],
            selection_id=label,
            selected_document_ids=[filing.document.document_id],
        )
    loaded = read_catalog(tmp_path / "manifest.json")
    assert loaded.selected_sources("sec", tmp_path)[0].read() == "SEC source"
    assert "DART source" in loaded.selected_sources("dart", tmp_path)[0].read()
    assert len(loaded.documents) == len(loaded.selections) == 2
    assert len(loaded.artifacts) == 3
    assert loaded.documents[1].document_id == "opaque-dart-id"


@pytest.mark.parametrize("latest_state", ["corrupt", "missing"])
def test_conflicting_legacy_primaries_block_even_when_a_copy_is_invalid(tmp_path, latest_state):
    """Registered conflicting identities cannot silently fall back to an older valid source."""
    old = tmp_path / "old.html"
    old.write_text("old")
    new = tmp_path / "new.html"
    new.write_text("new")
    source = filing_source(old)
    newer = filing_source(new, document=source.document)
    newer = replace(
        newer, artifact=newer.artifact.model_copy(update={"artifact_id": "new-primary"})
    )
    catalog = Manifest(
        corpus=source.corpus,
        documents=(source.document,),
        artifacts=(source.artifact, newer.artifact),
    )
    with pytest.raises(ValueError, match="Conflicting primary sources"):
        current_primary(catalog, source.document.document_id, tmp_path)
    if latest_state == "corrupt":
        new.write_text("corrupted")
    else:
        new.unlink()
    with pytest.raises(ValueError, match="Conflicting primary sources"):
        current_primary(catalog, source.document.document_id, tmp_path)


def test_acquisition_group_rejects_disconnected_artifacts(tmp_path):
    """Validate artifact ownership before a manifest write can occur."""
    path = tmp_path / "source"
    path.write_text("source")
    source = filing_source(path)
    with pytest.raises(ValueError, match="another document"):
        AcquiredFiling(filing_document(registry="dart"), (source.artifact,), (b"source",))
    with pytest.raises(ValueError, match="exactly one primary"):
        AcquiredFiling(source.document, (), ())


def test_selection_identity_normalizes_scope_and_distinguishes_requests():
    """Equivalent scopes reuse their selection, while new scopes stay separate."""
    identity = selection_identity("sec", ["NVDA", "AMD"], [2024, 2023])
    assert identity == selection_identity("sec", ["AMD", "NVDA", "AMD"], [2023, 2024])
    assert identity != selection_identity("sec", ["NVDA"], [2024])
    assert identity != selection_identity("dart", ["NVDA", "AMD"], [2024, 2023])


def test_reacquiring_prior_bytes_selects_the_actual_latest_acquisition(tmp_path):
    """Returning to earlier bytes keeps one current artifact and an opaque document ID."""
    document = filing_document(document_id="opaque-source-identity")
    for payload in (b"first", b"second", b"first"):
        filing = acquired_filing(tmp_path, document=document, payload=payload)
        catalog = publish_acquired(
            tmp_path / "manifest.json",
            [filing],
            selection_id="latest",
            selected_document_ids=[document.document_id],
        )
        selected = catalog.selected_sources("latest", tmp_path)[0]
        assert selected.read().encode() == payload
        assert selected.document.document_id == document.document_id
        assert len(catalog.artifacts) == 1


def test_acquisition_requires_explicit_payloads(tmp_path):
    """No producer may implicitly reread an old path instead of supplying acquired bytes."""
    filing = acquired_filing(tmp_path)
    with pytest.raises(TypeError):
        AcquiredFiling(filing.document, filing.artifacts)
    with pytest.raises(ValueError, match="payload"):
        AcquiredFiling(filing.document, filing.artifacts, ())
