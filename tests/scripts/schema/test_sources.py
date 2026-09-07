"""Source clean-start fixtures never use the user's data or running database."""

import json
from unittest.mock import AsyncMock

import pytest

from app.ingestion.manifest import Manifest
from app.ingestion.source_selection import acquisition_draft, source_inventory
from scripts.schema import recreate
from scripts.schema.sources import SourceReset, source_preview
from tests.ingestion.support import write_selection_catalog


@pytest.mark.parametrize("sample", [False, True])
def test_clean_start_removes_sources_but_preserves_unrelated_paths(tmp_path, sample):
    """Clean start clears exact source entries and persists an empty or sample draft."""
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
    assert acquisition_draft(corpus, ())["identifiers"] == (["NVDA", "AMD"] if sample else [])
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
    monkeypatch.setattr(schema_recreate, "local_target", lambda root: (target, {}))
    monkeypatch.setattr(
        schema_recreate, "recreate", AsyncMock(side_effect=[{}, ValueError("fixture failure")])
    )
    phrase = f"RECREATE {tmp_path.name}" + ("" if keep_sources else " AND SOURCES")
    monkeypatch.setattr("builtins.input", lambda _: phrase)
    with pytest.raises(ValueError, match="fixture failure"):
        recreate.run(tmp_path, keep_sources=keep_sources)
    assert source_preview(tmp_path) == before


def test_cleanup_failure_reports_database_commit_and_retains_journal(tmp_path, monkeypatch, capsys):
    """Failure after DB commit must not become a success or an automatic repeat."""
    write_selection_catalog(tmp_path / "data/corpus")
    target = {"port": "1", "apps": [], "volume": "fixture", "docker": ["docker"]}
    monkeypatch.setattr(recreate.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(schema_recreate, "local_target", lambda root: (target, {}))
    monkeypatch.setattr(schema_recreate, "recreate", AsyncMock(return_value={}))
    monkeypatch.setattr("builtins.input", lambda _: f"RECREATE {tmp_path.name} AND SOURCES")
    import scripts.schema.sources as reset_module

    def refuse_cleanup(path):
        """Simulate lost write access only at post-commit backup removal."""
        raise PermissionError("fixture denied")

    monkeypatch.setattr(reset_module.shutil, "rmtree", refuse_cleanup)
    assert recreate.run(tmp_path) == 1
    assert "DB committed" in capsys.readouterr().err
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


def test_uncertain_database_outcome_retains_durable_recovery_evidence(tmp_path, monkeypatch):
    """A lost DB connection restores source bytes but blocks retry with a durable journal."""
    from sqlalchemy.exc import SQLAlchemyError

    corpus = tmp_path / "data/corpus"
    write_selection_catalog(corpus)
    original = (corpus / "manifest.json").read_bytes()
    target = {"port": "1", "apps": [], "volume": "fixture", "docker": ["docker"]}
    monkeypatch.setattr(recreate.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(schema_recreate, "local_target", lambda root: (target, {}))
    monkeypatch.setattr(
        schema_recreate, "recreate", AsyncMock(side_effect=[{}, SQLAlchemyError("connection lost")])
    )
    monkeypatch.setattr("builtins.input", lambda _: f"RECREATE {tmp_path.name} AND SOURCES")
    with pytest.raises(SQLAlchemyError):
        recreate.run(tmp_path)
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
