"""Serialize managed source mutations and retain recoverable filesystem transactions."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import fcntl
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from app.ingestion.acquisition import publish_bytes
from app.ingestion.manifest import Manifest, SourceArtifact

JOURNAL = ".source-transaction"


def confined_path(root: Path, relative: str) -> Path:
    """Reject traversal, metadata collisions and every symlink in a managed path."""
    SourceArtifact.validate_path(relative)
    path = root / relative
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("Managed source paths must not contain symlinks.")
        if part == root:
            break
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Managed source path escapes the corpus root.")
    if path.exists() and not path.is_file():
        raise ValueError("Managed source path is not a regular file.")
    return path


def fingerprint(path: Path) -> str | None:
    """Fingerprint actual bytes for a mutation or explicit destructive preview."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@contextmanager
def source_lock(root: Path, *, recover: bool = False) -> Iterator[None]:
    """Serialize acquisitions, job input pinning and confirmed source deletion."""
    root.mkdir(parents=True, exist_ok=True)
    path = confined_path(root, ".source-lock")
    created = not path.exists()
    with path.open("a+b") as lock:
        if created:
            os.fchmod(lock.fileno(), 0o664)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            if (root / ".schema-recreate-journal").exists() or (
                root.parent / ".schema-recreate-journal"
            ).exists():
                raise ValueError("Source reset is pending; recover it before acquiring sources.")
            if (root / JOURNAL).exists():
                if recover:
                    recover_transaction(root)
                else:
                    raise ValueError(
                        "Source publication is pending; retry acquisition to recover it."
                    )
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _sync_directory(path: Path) -> None:
    """Make rename ordering durable before advancing the transaction journal."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def recover_transaction(root: Path) -> None:
    """Finish a committed publication or restore proven pre-publication bytes."""
    journal = root / JOURNAL
    if journal.is_symlink():
        raise ValueError("Source transaction journal must not be a symlink.")
    record = journal / "record.json"
    if not record.exists():
        raise ValueError(
            "Incomplete source transaction preparation; preserve the journal for recovery."
        )
    rows = json.loads(record.read_text())
    if not isinstance(rows, list) or not rows or rows[-1].get("path") != "manifest.json":
        raise ValueError("Invalid source transaction journal; manual recovery is required.")
    for row in rows:
        path = confined_path(root, row["path"])
        actual = fingerprint(path)
        if actual not in {row["before"], row["after"]}:
            raise ValueError("Source changed during recovery; preserve the journal for inspection.")
        if row["before"] is not None:
            backup = confined_path(root, f"{JOURNAL}/{row['backup']}")
            if fingerprint(backup) != row["before"]:
                raise ValueError("Source recovery backup changed; preserve the journal.")
    committed = (journal / "committed").exists()
    if committed and any(fingerprint(root / row["path"]) != row["after"] for row in rows):
        raise ValueError("Committed source files changed; preserve the recovery journal.")
    if not committed:
        for row in reversed(rows):
            path = confined_path(root, row["path"])
            if row["before"] is None:
                path.unlink(missing_ok=True)
            else:
                publish_bytes(root, row["path"], (journal / row["backup"]).read_bytes())
            _sync_directory(path.parent)
    shutil.rmtree(journal)
    _sync_directory(root)


def commit_sources(root: Path, manifest: Manifest, changes: Mapping[str, bytes | None]) -> None:
    """Commit validated file changes before the catalog, rolling back ordinary failures."""
    if (root / JOURNAL).exists():
        raise ValueError("An unresolved source transaction already exists.")
    payloads = dict(changes)
    if "manifest.json" in payloads or any(p.split("/")[0].startswith(".") for p in payloads):
        raise ValueError("Source changes collide with managed metadata.")
    payloads["manifest.json"] = (manifest.model_dump_json(indent=2) + "\n").encode()
    # Inspect all targets before creating the journal; a failed preview changes nothing.
    for relative in payloads:
        confined_path(root, relative)
    journal = root / JOURNAL
    journal.mkdir()
    rows = []
    prepared = False
    try:
        for index, (relative, payload) in enumerate(payloads.items()):
            path = confined_path(root, relative)
            before = path.read_bytes() if path.exists() else None
            backup = f"{index}.before"
            if before is not None:
                publish_bytes(root, f"{JOURNAL}/{backup}", before)
            if payload is not None:
                publish_bytes(root, f"{JOURNAL}/{index}.after", payload)
            rows.append(
                {
                    "path": relative,
                    "backup": backup,
                    "before": hashlib.sha256(before).hexdigest() if before is not None else None,
                    "after": hashlib.sha256(payload).hexdigest() if payload is not None else None,
                }
            )
        publish_bytes(root, f"{JOURNAL}/record.json", json.dumps(rows).encode())
        _sync_directory(journal)
        _sync_directory(root)
        prepared = True
        for index, (relative, payload) in enumerate(payloads.items()):
            path = confined_path(root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            if payload is None:
                path.unlink(missing_ok=True)
            else:
                os.replace(journal / f"{index}.after", path)
            _sync_directory(path.parent)
        publish_bytes(root, f"{JOURNAL}/committed", b"committed\n")
        _sync_directory(journal)
    except BaseException:
        if prepared:
            recover_transaction(root)
        else:
            shutil.rmtree(journal)
        raise
    recover_transaction(root)


def external_references(root: Path) -> dict[str, int]:
    """Count paths retained by immutable job inputs and other registered catalogs."""
    references: dict[str, int] = {}
    for path in sorted(root.glob("*-manifest.json")):
        confined_path(root, path.name)
        for artifact in Manifest.read(path).artifacts:
            references[artifact.path] = references.get(artifact.path, 0) + 1
    return references


@lru_cache(maxsize=4096)
def _validated_source(root: str, artifact_json: str, metadata: tuple[int, ...]) -> str | None:
    """Cache integrity results only for one exact artifact and filesystem revision."""
    artifact = SourceArtifact.model_validate_json(artifact_json)
    try:
        artifact.read(Path(root))
    except (OSError, ValueError, UnicodeError) as error:
        return str(error)
    return None


def validate_source(artifact: SourceArtifact, root: Path, *, cached: bool = False) -> None:
    """Use cheap stat checks for inventory and full integrity for execution boundaries."""
    path = confined_path(root, artifact.path)
    if not cached:
        artifact.read(root)
        return
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Source is not a regular file.")
    key = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
    error = _validated_source(str(root.resolve()), artifact.model_dump_json(), key)
    if error is not None:
        raise ValueError(error)
