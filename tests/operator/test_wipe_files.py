"""Runtime file enumeration, permission diagnosis and verified removal for a reset."""

import os
from pathlib import Path

import pytest

from app.operator.wipe_errors import WipeError
from app.operator.wipe_files import list_runtime_files, remove_runtime_file


def test_runtime_file_allowlist_preserves_sources_and_rejects_links(tmp_path):
    """Only runtime files are candidates; tracked sources and symlink targets survive."""
    for name in (
        "data/corpus/raw.html",
        "data/corpus/manifest.json",
        "data/corpus/protected.html",
        "data/local-settings/local-llm.json",
        "data/golden/new_v2_astra.json",
        ".env",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test")
    files = list_runtime_files(tmp_path, {"data/corpus/protected.html"})
    assert {row["path"] for row in files} == {
        "data/corpus/raw.html",
        "data/local-settings/local-llm.json",
    }
    (tmp_path / "data/corpus/link.html").symlink_to(tmp_path / ".env")
    with pytest.raises(WipeError, match="symbolic link"):
        list_runtime_files(tmp_path, set())


def test_file_deletion_refuses_changed_parent_directory(tmp_path):
    """Replacing a runtime directory with a link cannot delete the external target's file."""
    root = tmp_path / "checkout"
    corpus = root / "data/corpus"
    corpus.mkdir(parents=True)
    (corpus / "raw.html").write_text("same content")
    item = list_runtime_files(root, set())[0]
    external = tmp_path / "external"
    external.mkdir()
    (external / "raw.html").write_text("same content")
    corpus.rename(corpus.with_name("original"))
    corpus.symlink_to(external, target_is_directory=True)
    with pytest.raises(OSError):
        remove_runtime_file(root, item)
    assert (external / "raw.html").read_text() == "same content"
    assert (corpus.with_name("original") / "raw.html").exists()


def test_preview_refuses_runtime_files_without_delete_permission(tmp_path, monkeypatch):
    """Reject predictable filesystem failure before the database deletion stage is reachable."""
    corpus = tmp_path / "data/corpus"
    corpus.mkdir(parents=True)
    (corpus / "raw.html").write_text("keep this")
    monkeypatch.setattr("app.operator.wipe_files.os.access", lambda *_args, **_kwargs: False)
    with pytest.raises(WipeError, match="cannot be removed") as failure:
        list_runtime_files(tmp_path, set())
    diagnosis = failure.value.diagnosis
    assert diagnosis["code"] == "runtime_file_permission"
    assert diagnosis["details"]["path"] == "data/corpus/raw.html"
    assert diagnosis["details"]["parent"]["uid"] == corpus.stat().st_uid
    assert diagnosis["details"]["operator_uid"] == os.geteuid()
    assert any("setfacl" in step and str(corpus) in step for step in diagnosis["remediation"])
    assert (corpus / "raw.html").read_text() == "keep this"


def test_read_permission_failure_has_actionable_diagnosis(tmp_path, monkeypatch):
    """Explain unreadable contents even when parent delete permissions pass."""
    runtime = tmp_path / "data/local-settings/local-llm.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("preserve runtime")

    def unreadable(_path):
        """Model a denied fingerprint read without changing file permissions."""
        raise PermissionError("Permission denied")

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    with pytest.raises(WipeError, match="cannot be read") as failure:
        list_runtime_files(tmp_path, set())
    assert failure.value.diagnosis["details"]["operation"] == "read"
    assert runtime.read_text() == "preserve runtime"


def test_symlink_and_changed_file_fail_closed(tmp_path):
    """An external link or a modified preview entry cannot be silently erased."""
    target = tmp_path / "data/local-settings/connection.json"
    target.parent.mkdir(parents=True)
    target.write_text("before")
    item = list_runtime_files(tmp_path, set())[0]
    target.write_text("changed")
    with pytest.raises(WipeError, match="changed"):
        remove_runtime_file(tmp_path, item)
    assert target.read_text() == "changed"
    (tmp_path / "data/local-settings/connection.link").symlink_to(target)
    with pytest.raises(WipeError, match="symbolic link"):
        list_runtime_files(tmp_path, set())
