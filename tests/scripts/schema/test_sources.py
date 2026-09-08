"""Source clean-start fixtures never use the user's data or running database."""

import json
from unittest.mock import AsyncMock

import pytest

from app.ingestion.manifest import Manifest
from app.ingestion.source_selection import acquisition_draft, source_inventory
from scripts.schema import recreate
from scripts.schema.sources import (
    SourceAccessError,
    SourceReset,
    check_source_write_access,
    source_preview,
)
from tests.ingestion.support import write_selection_catalog


@pytest.mark.parametrize("sample", [False, True])
def test_clean_start_removes_sources_but_preserves_unrelated_paths(tmp_path, sample):
    """Clean start preserves unrelated files and stores default or sample pairs."""
    corpus = tmp_path / "data/corpus"
    write_selection_catalog(corpus)
    sentinel = tmp_path / "data/evaluation-export.json"
    sentinel.write_text("keep")
    (tmp_path / ".env").write_text("keep")
    before = source_preview(tmp_path)
    assert len(before["files"]) == 4
    reset = SourceReset(tmp_path, before, sample=sample)
    reset.stage()
    assert not Manifest.read(corpus / "manifest.json").artifacts
    assert not source_inventory(corpus)
    assert len(acquisition_draft(corpus, ())["pairs"]) == (4 if sample else 18)
    reset.finish()
    assert not reset.journal.exists()
    assert sentinel.read_text() == (tmp_path / ".env").read_text() == "keep"


def test_staging_restore_recovers_exact_files_and_manifest(tmp_path):
    """A DB failure can restore every original byte rather than leave half a catalog."""
    corpus = tmp_path / "data/corpus"
    write_selection_catalog(corpus)
    before = source_preview(tmp_path)
    reset = SourceReset(tmp_path, before)
    reset.stage()
    reset.restore()
    assert source_preview(tmp_path) == before


def test_changed_source_preview_and_symlinks_refuse_mutation(tmp_path):
    """Stale confirmations and escaped artifacts cannot reach quarantine."""
    corpus = tmp_path / "data/corpus"
    catalog = write_selection_catalog(corpus)
    before = source_preview(tmp_path)
    target = corpus / catalog.artifacts[0].path
    target.write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        SourceReset(tmp_path, before).stage()
    target.unlink()
    target.symlink_to(tmp_path / ".env")
    with pytest.raises(ValueError, match="symlinked"):
        source_preview(tmp_path)


@pytest.mark.parametrize("keep_sources", [False, True])
def test_command_preserves_sources_on_database_failure(tmp_path, monkeypatch, keep_sources):
    """Both reset modes preserve raw bytes when DB recreation fails."""
    corpus = tmp_path / "data/corpus"
    write_selection_catalog(corpus)
    before = source_preview(tmp_path)
    target = {"port": "1", "apps": [], "volume": "fixture", "docker": ["docker"]}
    monkeypatch.setattr(recreate.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(recreate, "local_target", lambda root: (target, {}))
    monkeypatch.setattr(
        recreate, "recreate", AsyncMock(side_effect=[{}, ValueError("fixture failure")])
    )
    phrase = "Y"
    monkeypatch.setattr("builtins.input", lambda _: phrase)
    with pytest.raises(ValueError, match="fixture failure"):
        recreate.run(tmp_path, keep_sources=keep_sources)
    assert source_preview(tmp_path) == before


@pytest.mark.parametrize("failure", [PermissionError, KeyboardInterrupt])
def test_cleanup_failure_reports_database_commit_and_retains_journal(
    tmp_path, monkeypatch, capsys, failure
):
    """Failure after DB commit must not become a success or an automatic repeat."""
    write_selection_catalog(tmp_path / "data/corpus")
    target = {"port": "1", "apps": [], "volume": "fixture", "docker": ["docker"]}
    monkeypatch.setattr(recreate.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(recreate, "local_target", lambda root: (target, {}))
    monkeypatch.setattr(recreate, "recreate", AsyncMock(return_value={}))
    monkeypatch.setattr("builtins.input", lambda _: "Y")
    import scripts.schema.sources as reset_module

    def refuse_cleanup(path):
        """Simulate lost write access only at post-commit backup removal."""
        raise failure("fixture denied")

    monkeypatch.setattr(reset_module.shutil, "rmtree", refuse_cleanup)
    assert recreate.run(tmp_path) == "incomplete"
    output = capsys.readouterr().err
    assert "DB committed" in output
    assert "rag-dev up -d" in output
    journal = tmp_path / "data/.schema-recreate-journal/journal.json"
    assert json.loads(journal.read_text())["phase"] == "database_committed_source_cleanup_pending"
    with pytest.raises(ValueError, match="Unfinished"):
        source_preview(tmp_path)


@pytest.mark.parametrize("name", ["manifest.json", "acquisition-draft.json"])
def test_restore_preserves_metadata_changed_after_staging(tmp_path, name):
    """Foreign writes after the preview are never removed by rollback."""
    corpus = tmp_path / "data/corpus"
    write_selection_catalog(corpus)
    reset = SourceReset(tmp_path, source_preview(tmp_path))
    reset.stage()
    (corpus / name).write_text("foreign update")
    with pytest.raises(ValueError, match="changed"):
        reset.restore()
    assert (corpus / name).read_text() == "foreign update"
    assert (reset.journal / "journal.json").exists()
    assert (reset.journal / "sources/manifest.json").exists()


def test_uncertain_database_outcome_retains_durable_recovery_evidence(
    tmp_path, monkeypatch, capsys
):
    """A lost DB connection restores source bytes but blocks retry with a durable journal."""
    from sqlalchemy.exc import SQLAlchemyError

    corpus = tmp_path / "data/corpus"
    write_selection_catalog(corpus)
    original = (corpus / "manifest.json").read_bytes()
    target = {"port": "1", "apps": [], "volume": "fixture", "docker": ["docker"]}
    monkeypatch.setattr(recreate.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(recreate, "local_target", lambda root: (target, {}))
    monkeypatch.setattr(
        recreate, "recreate", AsyncMock(side_effect=[{}, SQLAlchemyError("connection lost")])
    )
    monkeypatch.setattr("builtins.input", lambda _: "Y")
    with pytest.raises(SQLAlchemyError):
        recreate.run(tmp_path)
    output = capsys.readouterr().err
    assert "Database outcome is unconfirmed" in output
    assert "database and sources are unchanged" not in output
    assert "rag-dev up -d" in output
    assert (corpus / "manifest.json").read_bytes() == original
    journal = tmp_path / "data/.schema-recreate-journal/journal.json"
    assert (
        json.loads(journal.read_text())["phase"] == "sources_restored_database_outcome_unconfirmed"
    )
    with pytest.raises(ValueError, match="Unfinished"):
        source_preview(tmp_path)


def test_source_paths_cannot_collide_with_manifest_metadata(tmp_path):
    """A malformed raw path cannot move the manifest twice or destroy reset metadata."""
    corpus = tmp_path / "data/corpus"
    catalog = write_selection_catalog(corpus)
    changed = catalog.artifacts[0].model_copy(update={"path": "manifest.json"})
    catalog.model_copy(update={"artifacts": (changed, *catalog.artifacts[1:])}).write(
        corpus / "manifest.json"
    )
    with pytest.raises(ValueError, match="collide"):
        source_preview(tmp_path)


def test_restore_refuses_a_source_parent_replaced_by_a_symlink(tmp_path):
    """Rollback cannot write outside the corpus after an external directory replacement."""
    corpus = tmp_path / "data/corpus"
    catalog = write_selection_catalog(corpus)
    reset = SourceReset(tmp_path, source_preview(tmp_path))
    reset.stage()
    parent = (corpus / catalog.artifacts[0].path).parent
    parent.rmdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    parent.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        reset.restore()
    assert not list(foreign.iterdir())
    assert (reset.journal / "journal.json").exists()


@pytest.mark.parametrize("denied_kind", ["file", "corpus", "nested"])
def test_unreadable_sources_cannot_be_reported_as_an_empty_inventory(tmp_path, denied_kind):
    """Unreadable files and directories block preview before deletion can be approved."""
    import os

    if os.geteuid() == 0:
        pytest.skip("Root bypasses the Unix mode-denial fixture.")
    corpus = tmp_path / "data/corpus"
    nested = corpus / "sec" / "locked directory"
    nested.mkdir(parents=True)
    source = nested / "private-source.html"
    source.write_text("keep inaccessible bytes")
    (corpus / "visible.html").write_text("keep visible bytes")
    denied = {"file": source, "corpus": corpus, "nested": nested}[denied_kind]
    denied.chmod(0)
    try:
        with pytest.raises(PermissionError):
            source_preview(tmp_path)
    finally:
        denied.chmod(0o600 if denied_kind == "file" else 0o700)
    assert source.read_text() == "keep inaccessible bytes"


@pytest.mark.parametrize("directory", ["data", "data/corpus"])
def test_source_write_check_covers_journal_and_catalog_destinations(tmp_path, directory):
    """Journal and empty-catalog creation require host write access even without source files."""
    import os

    if os.geteuid() == 0:
        pytest.skip("Root bypasses the Unix write-permission fixture.")
    (tmp_path / "data/corpus").mkdir(parents=True)
    preview = source_preview(tmp_path)
    denied = tmp_path / directory
    denied.chmod(0o555)
    try:
        with pytest.raises(SourceAccessError) as caught:
            check_source_write_access(tmp_path, preview)
        assert denied in caught.value.paths
    finally:
        denied.chmod(0o755)


def test_failed_source_rollback_preserves_journal_and_reports_unconfirmed_recovery(
    tmp_path, monkeypatch, capsys
):
    """A restoration failure must not claim intact sources or silently leave the API stopped."""
    corpus = tmp_path / "data/corpus"
    write_selection_catalog(corpus)
    target = {"port": "1", "apps": [], "volume": "fixture", "docker": ["docker"]}
    monkeypatch.setattr(recreate.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(recreate, "local_target", lambda _: (target, {}))
    monkeypatch.setattr(
        recreate, "recreate", AsyncMock(side_effect=[{}, ValueError("rollback DB")])
    )
    monkeypatch.setattr("builtins.input", lambda _: "Y")

    def fail_restore(self, **options):
        """Model a filesystem error while leaving the real staging journal intact."""
        raise PermissionError("fixture restore denied")

    monkeypatch.setattr(SourceReset, "restore", fail_restore)
    with pytest.raises(RuntimeError, match="Source recovery failed"):
        recreate.run(tmp_path)
    output = capsys.readouterr().err
    assert "rollback could not be confirmed" in output
    assert "database and sources are unchanged" not in output
    assert "rag-dev up -d" in output
    assert (tmp_path / "data/.schema-recreate-journal/journal.json").exists()


def test_reset_clears_managed_inputs_and_preserves_unregistered_html(tmp_path):
    """Only registered or managed-namespace originals and pinned inputs enter the reset."""
    from app.ingestion.source_selection import record_selection

    corpus = tmp_path / "data/corpus"
    write_selection_catalog(corpus)
    record_selection(corpus, ("NVDA",), (2024,))
    unrelated = corpus / "notes.html"
    unrelated.write_text("unrelated local report")
    orphan = corpus / "sec/orphan/primary.html"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("unregistered managed original")
    preview = source_preview(tmp_path)
    assert "notes.html" not in preview["files"]
    assert "sec/orphan/primary.html" in preview["files"]
    assert any(path.startswith("inputs/") for path in preview["files"])
    reset = SourceReset(tmp_path, preview)
    reset.stage()
    reset.finish()
    assert unrelated.read_text() == "unrelated local report"
    assert not orphan.exists()
    assert not list((corpus / "inputs").rglob("*.html"))


def test_pending_acquisition_journal_blocks_source_reset(tmp_path):
    """Reset cannot remove the backups needed to recover an interrupted acquisition."""
    corpus = tmp_path / "data/corpus"
    write_selection_catalog(corpus)
    (corpus / ".source-transaction").mkdir()
    with pytest.raises(ValueError, match="publication is pending"):
        source_preview(tmp_path)
