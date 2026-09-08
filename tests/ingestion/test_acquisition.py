"""Common artifact publication and named selection behavior."""

from dataclasses import replace

import pytest

from app.ingestion.acquisition import (
    AcquiredFiling,
    current_primary,
    merge_acquired,
    publish_bytes,
    read_catalog,
    selection_identity,
)
from app.ingestion.manifest import Manifest
from tests.ingestion.support import filing_document, filing_source


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
    """Adding DART acquisition must preserve SEC documents and exact selected artifacts."""
    sec_path = tmp_path / "sec.html"
    sec_path.write_text("SEC source")
    dart_path = tmp_path / "dart.xml"
    dart_path.write_text("DART source")
    sec = filing_source(sec_path)
    dart = filing_source(dart_path, document=filing_document(registry="dart"))
    catalog = Manifest(corpus=sec.corpus)
    catalog = merge_acquired(
        catalog,
        [AcquiredFiling(sec.document, (sec.artifact,))],
        selection_id="sec",
        selected_document_ids=[sec.document.document_id],
        corpus_root=tmp_path,
    )
    catalog = merge_acquired(
        catalog,
        [AcquiredFiling(dart.document, (dart.artifact,))],
        selection_id="dart",
        selected_document_ids=[dart.document.document_id],
        corpus_root=tmp_path,
    )
    path = tmp_path / "manifest.json"
    catalog.write(path)
    loaded = read_catalog(path)
    assert loaded.selected_sources("sec", tmp_path)[0].read() == "SEC source"
    assert loaded.selected_sources("dart", tmp_path)[0].read() == "DART source"
    assert len(loaded.documents) == len(loaded.artifacts) == len(loaded.selections) == 2


def test_conflicting_legacy_primaries_require_an_unambiguous_valid_source(tmp_path):
    """Two valid revisions block acquisition reuse; one verified legacy copy can be recovered."""
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
    assert current_primary(catalog, source.document.document_id, tmp_path) is None
    new.write_text("corrupted")
    assert current_primary(catalog, source.document.document_id, tmp_path) == source.artifact


def test_acquisition_group_rejects_disconnected_artifacts(tmp_path):
    """Validate artifact ownership before a manifest write can occur."""
    path = tmp_path / "source"
    path.write_text("source")
    source = filing_source(path)
    with pytest.raises(ValueError, match="another document"):
        AcquiredFiling(filing_document(registry="dart"), (source.artifact,))
    with pytest.raises(ValueError, match="exactly one primary"):
        AcquiredFiling(source.document, ())


def test_selection_identity_normalizes_scope_and_distinguishes_requests():
    """Equivalent scopes reuse their selection, while new scopes stay separate."""
    identity = selection_identity("sec", ["NVDA", "AMD"], [2024, 2023])
    assert identity == selection_identity("sec", ["AMD", "NVDA", "AMD"], [2023, 2024])
    assert identity != selection_identity("sec", ["NVDA"], [2024])
    assert identity != selection_identity("dart", ["NVDA", "AMD"], [2024, 2023])


def test_reacquiring_prior_bytes_selects_the_actual_latest_acquisition(tmp_path):
    """A source reverting to earlier bytes must select that reacquired artifact."""
    first_path = tmp_path / "first.html"
    first_path.write_text("first")
    second_path = tmp_path / "second.html"
    second_path.write_text("second")
    first = filing_source(first_path)
    second = filing_source(second_path, document=first.document)
    second = replace(second, artifact=second.artifact.model_copy(update={"artifact_id": "second"}))
    catalog = Manifest(corpus=first.corpus)
    for source in (first, second, first):
        catalog = merge_acquired(
            catalog,
            [AcquiredFiling(source.document, (source.artifact,))],
            selection_id="latest",
            selected_document_ids=[source.document.document_id],
            corpus_root=tmp_path,
        )
        assert catalog.selected_sources("latest", tmp_path)[0].read() == source.read()
    assert len(catalog.artifacts) == 2
