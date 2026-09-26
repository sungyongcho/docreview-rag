"""Runtime files a reset may delete: enumeration, permission diagnosis and verified removal."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shlex
import stat
from typing import Any

from app.operator.wipe_errors import WipeError

# Only these checkout directories hold runtime data; every other file in the checkout is kept.
RUNTIME_DIRECTORIES = ("data/corpus", "data/eval_runs", "data/local-settings")
# The corpus directory also holds source JSON such as manifest.json, so only the downloaded
# filing documents in it count as runtime data.
CORPUS_RUNTIME_SUFFIXES = {".html", ".xml", ".zip"}


def list_runtime_files(root: Path, tracked: set[str]) -> list[dict[str, Any]]:
    """Enumerate runtime-only paths while preserving every tracked file and source JSON.

    Each entry records the file size and SHA-256 digest so that removal can refuse a file
    that changed after the preview was confirmed.

    Parameters
    ----------
    root : Path
        Resolved checkout root that owns the runtime directories.
    tracked : set[str]
        Checkout-relative POSIX paths that Git tracks; they and their contents are kept.

    Returns
    -------
    list[dict[str, Any]]
        One ``path``/``bytes``/``sha256`` record per removable file, sorted by path.
    """
    removable = []
    for path in sorted(set(_runtime_candidates(root))):
        relative = path.relative_to(root).as_posix()
        if _is_tracked(relative, tracked):
            continue
        if path.is_symlink() or path.resolve() != path.absolute():
            raise WipeError(f"Runtime path contains a symbolic link: {relative}")
        if not path.is_file():
            continue
        removable.append(_describe_removable_file(root, path, relative))
    return removable


def _runtime_candidates(root: Path) -> list[Path]:
    """Walk the runtime directories, refusing links and directories that cannot be read.

    A link could lead outside the checkout, and a skipped directory would make the preview
    silently incomplete, so both stop the enumeration.
    """

    def refuse_unreadable(error: OSError) -> None:
        """Refuse an incomplete preview instead of silently skipping unreadable directories."""
        if isinstance(error, PermissionError) and error.filename:
            raise _permission_error(root, Path(error.filename), operation="enumerate") from error
        raise WipeError("Runtime files could not be fully enumerated") from error

    candidates: list[Path] = []
    for name in RUNTIME_DIRECTORIES:
        directory = root / name
        if not directory.exists():
            continue
        if directory.is_symlink() or directory.resolve() != directory.absolute():
            raise WipeError(f"Runtime directory contains a symbolic link: {name}")
        for parent, directories, filenames in os.walk(directory, onerror=refuse_unreadable):
            if any((Path(parent) / child).is_symlink() for child in directories):
                raise WipeError(f"Runtime directory contains a symbolic link: {name}")
            for filename in filenames:
                if name == "data/corpus" and Path(filename).suffix not in CORPUS_RUNTIME_SUFFIXES:
                    continue
                candidates.append(Path(parent) / filename)
    return candidates


def _is_tracked(relative: str, tracked: set[str]) -> bool:
    """Keep a path when Git tracks it or any directory that contains it."""
    if relative in tracked:
        return True
    return any(parent.as_posix() in tracked for parent in Path(relative).parents)


def _describe_removable_file(root: Path, path: Path, relative: str) -> dict[str, Any]:
    """Confirm that this operator can delete and read one file, then fingerprint it.

    These checks run while the preview is built, so a reset never stops halfway through its
    deletions for a permission problem that was visible beforehand.
    """
    if not os.access(path.parent, os.W_OK | os.X_OK, effective_ids=True):
        raise _permission_error(root, path, operation="remove")
    metadata = path.stat()
    parent_metadata = path.parent.stat()
    # In a sticky directory only root, the file owner or the directory owner may unlink.
    if parent_metadata.st_mode & stat.S_ISVTX and os.geteuid() not in {
        0,
        metadata.st_uid,
        parent_metadata.st_uid,
    }:
        raise _permission_error(root, path, operation="remove")
    try:
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
    except PermissionError as error:
        raise _permission_error(root, path, operation="read") from error
    return {
        "path": relative,
        "bytes": metadata.st_size,
        "sha256": fingerprint,
    }


def _permission_error(root: Path, path: Path, *, operation: str) -> WipeError:
    """Explain the denied operation without changing owners, modes, or runtime data."""
    uid = os.geteuid()
    details: dict[str, Any] = {
        "path": path.relative_to(root).as_posix(),
        "operation": operation,
        "operator_uid": uid,
        "operator_gid": os.getegid(),
        "operator_groups": sorted(set(os.getgroups()) | {os.getegid()}),
    }
    for key, item in (("file", path), ("parent", path.parent)):
        try:
            metadata = item.stat()
        except OSError:
            details[key] = {"path": str(item), "metadata": "unavailable"}
        else:
            details[key] = {
                "path": str(item),
                "uid": metadata.st_uid,
                "gid": metadata.st_gid,
                "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
            }
    actions = {
        "remove": "removed",
        "read": "read",
        "enumerate": "enumerated",
    }
    commands = (
        [f"sudo setfacl -m u:{uid}:rwx -- {shlex.quote(str(path))}"]
        if operation == "enumerate"
        else [
            f"sudo setfacl -m u:{uid}:rwx -- {shlex.quote(str(path.parent))}",
            f"sudo setfacl -m u:{uid}:r -- {shlex.quote(str(path))}",
        ]
    )
    return WipeError(
        f"Runtime file cannot be {actions[operation]} by this operator: {details['path']}",
        code="runtime_file_permission",
        details=details,
        remediation=[
            "The operator needs file read access and parent directory read, write, and "
            "search access. Ask the owner or administrator to grant these while preserving "
            "the application's existing access.",
            "If POSIX ACLs are supported, an administrator can run these targeted commands "
            "manually; they do not delete data:",
            *commands,
            "If access is still denied, check parent traversal permissions, sticky bits, "
            "ACLs, and read-only mounts. Then check reset availability again.",
        ],
    )


def remove_runtime_file(root: Path, item: dict[str, Any]) -> None:
    """Unlink a verified runtime entry through directory descriptors without following links.

    Parameters
    ----------
    root : Path
        Resolved checkout root the previewed path is relative to.
    item : dict[str, Any]
        One record from ``list_runtime_files``; its digest must still match the file.
    """
    relative = Path(item["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise WipeError("Runtime file escaped the checkout")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in relative.parts[:-1]:
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            os.close(directory)
            directory = child
        descriptor = os.open(
            relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]
            ):
                raise WipeError(f"File changed during reset: {item['path']}")
            current = os.stat(relative.name, dir_fd=directory, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                raise WipeError(f"File changed during reset: {item['path']}")
            os.unlink(relative.name, dir_fd=directory)
    finally:
        os.close(directory)
