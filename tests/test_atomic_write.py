"""Atomic text replacement with explicit mode, durability and encoding choices."""

import os
import stat

import pytest

from app.atomic_write import write_text_atomically


def test_replacement_publishes_exact_text_without_a_temporary_sibling(tmp_path):
    """Replace prior bytes with the encoded text and leave only the destination behind."""
    path = tmp_path / "state.json"
    path.write_text("old")

    write_text_atomically(
        path,
        '{"name": "코퍼스"}\n',
        mode=0o600,
        apply_umask=True,
        fsync_file=True,
        fsync_directory=True,
        encoding="utf-8",
    )

    assert path.read_bytes() == '{"name": "코퍼스"}\n'.encode()
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    ("mode", "apply_umask", "umask", "expected"),
    [(0o664, False, 0o077, 0o664), (0o666, True, 0o022, 0o644), (0o666, True, 0o077, 0o600)],
)
def test_mode_is_exact_or_narrowed_by_the_process_umask(
    tmp_path, mode, apply_umask, umask, expected
):
    """An exact mode ignores the umask; otherwise the umask narrows it as open() does."""
    path = tmp_path / "state.json"
    previous = os.umask(umask)
    try:
        write_text_atomically(
            path,
            "{}",
            mode=mode,
            apply_umask=apply_umask,
            fsync_file=False,
            fsync_directory=False,
            encoding=None,
        )
    finally:
        os.umask(previous)

    assert stat.S_IMODE(path.stat().st_mode) == expected


@pytest.mark.parametrize(
    ("fsync_file", "fsync_directory", "synced"),
    [(False, False, []), (True, False, ["file"]), (True, True, ["file", "directory"])],
)
def test_only_the_requested_file_and_directory_syncs_run(
    tmp_path, monkeypatch, fsync_file, fsync_directory, synced
):
    """Each durability flag adds exactly its own fsync, the file before the directory."""
    calls = []
    real_fsync = os.fsync

    def record(descriptor):
        """Name the kind of synced descriptor, then perform the real sync."""
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            calls.append("directory")
        else:
            calls.append("file")
        real_fsync(descriptor)

    monkeypatch.setattr("app.atomic_write.os.fsync", record)
    write_text_atomically(
        tmp_path / "state.json",
        "{}",
        mode=0o600,
        apply_umask=True,
        fsync_file=fsync_file,
        fsync_directory=fsync_directory,
        encoding=None,
    )

    assert calls == synced


def test_failed_rename_keeps_prior_bytes_and_removes_the_temporary_file(tmp_path, monkeypatch):
    """A failed replacement leaves the destination untouched and no partial file behind."""
    path = tmp_path / "state.json"
    path.write_text("old")

    def fail_replace(*_args):
        """Simulate a filesystem that refuses the atomic rename."""
        raise OSError("rename failed")

    monkeypatch.setattr("app.atomic_write.os.replace", fail_replace)
    with pytest.raises(OSError, match="rename failed"):
        write_text_atomically(
            path,
            "new",
            mode=0o600,
            apply_umask=True,
            fsync_file=True,
            fsync_directory=True,
            encoding="utf-8",
        )

    assert path.read_text() == "old"
    assert list(tmp_path.iterdir()) == [path]
