"""Journal local source changes around a separately transactional database reset."""

from collections import Counter
from collections.abc import Iterator
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from app.ingestion.manifest import Manifest
from app.ingestion.source_selection import DRAFT_NAME

JOURNAL_NAME = ".schema-recreate-journal"


class SourceAccessError(PermissionError):
    """Report every inaccessible reset directory without attempting a filesystem write."""

    def __init__(self, paths: tuple[Path, ...]) -> None:
        """Retain exact blocked paths for a scoped, elevated manual repair."""
        super().__init__(
            errno.EACCES, "Source directories require write and search access", str(paths[0])
        )
        self.paths = paths


def check_source_write_access(root: Path, preview: dict) -> None:
    """Check source parents and journal/catalog destinations using the effective host UID."""
    data = root / "data"
    corpus = data / "corpus"
    directories = {data, corpus}
    for name in preview["files"]:
        parent = (corpus / name).parent
        while parent.is_relative_to(corpus):
            directories.add(parent)
            parent = parent.parent
    existing = set()
    for path in directories:
        while not path.exists():
            path = path.parent
        existing.add(path)
    blocked = tuple(
        sorted(
            path for path in existing if not os.access(path, os.W_OK | os.X_OK, effective_ids=True)
        )
    )
    if blocked:
        raise SourceAccessError(blocked)


def _source_stat(path: Path) -> os.stat_result | None:
    """Treat only a missing path as absent; permission failures must stop the preview."""
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def check_source_journal(root: Path) -> None:
    """Require an inspectable data directory and no unfinished source journal."""
    data = root / "data"
    metadata = _source_stat(data)
    if metadata is None:
        return
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError("Source reset refuses symlinked data directories.")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Source data path is not a directory.")
    with os.scandir(data) as entries:
        if any(entry.name == JOURNAL_NAME for entry in entries):
            raise ValueError(
                "Unfinished source reset journal exists; inspect "
                "data/.schema-recreate-journal/journal.json before retrying."
            )


def _source_paths(directory: Path) -> Iterator[Path]:
    """Walk without following links or suppressing directory-access errors."""
    with os.scandir(directory) as entries:
        paths = sorted(Path(entry.path) for entry in entries)
    for path in paths:
        metadata = _source_stat(path)
        if metadata is None:
            raise ValueError("Source tree changed during inspection; review a new preview.")
        yield path
        if stat.S_ISDIR(metadata.st_mode):
            yield from _source_paths(path)


def source_preview(root: Path) -> dict:
    """Fingerprint exact confined raw files and manifests before asking for approval."""
    corpus = root / "data" / "corpus"
    check_source_journal(root)
    metadata = _source_stat(corpus)
    if metadata is not None and stat.S_ISLNK(metadata.st_mode):
        raise ValueError("Source reset refuses symlinked data directories.")
    if metadata is not None and not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Source corpus path is not a directory.")
    manifests = {}
    raw = set()
    if metadata is not None:
        paths = tuple(_source_paths(corpus))
        for path in paths:
            if path.parent != corpus or (
                path.name != "manifest.json" and not path.name.endswith("-manifest.json")
            ):
                continue
            entry = _source_stat(path)
            if entry is None:
                raise ValueError("Source manifest changed during inspection; review a new preview.")
            if stat.S_ISLNK(entry.st_mode):
                raise ValueError("Source reset refuses symlinked manifests.")
            manifest = Manifest.read(path)
            manifests[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            raw.update(artifact.path for artifact in manifest.artifacts)
        raw.update(
            str(path.relative_to(corpus))
            for path in paths
            if path.suffix.lower() in {".html", ".htm", ".xml", ".zip"}
        )
    if raw & (set(manifests) | {DRAFT_NAME}):
        raise ValueError("Source artifact paths collide with manifest or draft metadata.")
    files = {}
    for relative in sorted(raw):
        path = corpus / relative
        for parent in (path, *path.parents):
            entry = _source_stat(parent)
            if entry is not None and stat.S_ISLNK(entry.st_mode):
                raise ValueError("Source reset refuses symlinked or escaped raw paths.")
        if not path.resolve().is_relative_to(corpus.resolve()):
            raise ValueError("Source reset refuses symlinked or escaped raw paths.")
        entry = _source_stat(path)
        if entry is not None:
            if not stat.S_ISREG(entry.st_mode):
                raise ValueError("Source artifact is not a regular file.")
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    draft = corpus / DRAFT_NAME
    draft_entry = _source_stat(draft)
    if draft_entry is not None and stat.S_ISLNK(draft_entry.st_mode):
        raise ValueError("Source reset refuses symlinked drafts.")
    return {
        "files": files,
        "manifests": manifests,
        "draft": hashlib.sha256(draft.read_bytes()).hexdigest()
        if draft_entry is not None
        else None,
        "directories": dict(sorted(Counter(str(Path(name).parent) for name in files).items())),
    }


class SourceReset:
    """Retain exact source backups until the database outcome is confirmed."""

    def __init__(self, root: Path, preview: dict, *, sample: bool = False):
        """Bind the approved inventory to one checkout and preset."""
        self.root = root
        self.corpus = root / "data" / "corpus"
        self.journal = root / "data" / JOURNAL_NAME
        self.preview = preview
        self.sample = sample
        self.state = {"phase": "prepared", "moved": [], "created": {}, "preview": preview}

    def save(self, phase: str) -> None:
        """Atomically persist recovery evidence before further filesystem work."""
        self.state["phase"] = phase
        temporary = self.journal / "journal.tmp"
        with temporary.open("w") as output:
            json.dump(self.state, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(self.journal / "journal.json")
        descriptor = os.open(self.journal, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def stage(self) -> None:
        """Quarantine exact files and replace source catalogs without deleting backups."""
        if source_preview(self.root) != self.preview:
            raise ValueError("Source inventory changed; review a new preview. Nothing deleted.")
        check_source_write_access(self.root, self.preview)
        self.journal.mkdir(parents=True, exist_ok=False)
        self.save("staging")
        self.corpus.mkdir(parents=True, exist_ok=True)
        names = [*self.preview["files"], *self.preview["manifests"]]
        if self.preview["draft"] is not None:
            names.append(DRAFT_NAME)
        for name in names:
            source = self.corpus / name
            backup = self.journal / "sources" / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            self.state["moved"].append(name)
            self.save("staging")
            source.replace(backup)
        for name in self.preview["manifests"]:
            original = Manifest.read(self.journal / "sources" / name)
            empty = Manifest(corpus=original.corpus)
            payload = empty.model_dump_json(indent=2) + "\n"
            self.state["created"][name] = hashlib.sha256(payload.encode()).hexdigest()
            self.save("staging")
            if (self.corpus / name).exists():
                raise ValueError(
                    "New manifest appeared during reset; inspect the retained journal."
                )
            empty.write(self.corpus / name)
        payload = (
            json.dumps(
                {
                    "identifiers": ["NVDA", "AMD"] if self.sample else [],
                    "years": [2023, 2024] if self.sample else [],
                }
            )
            + "\n"
        )
        self.state["created"][DRAFT_NAME] = hashlib.sha256(payload.encode()).hexdigest()
        self.save("staging")
        with (self.corpus / DRAFT_NAME).open("x") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        self.save("database_pending")

    def restore(self, *, database_outcome_uncertain: bool = False) -> None:
        """Restore only unchanged generated paths and retain uncertain DB outcome evidence."""
        suffix = (
            "database_outcome_unconfirmed" if database_outcome_uncertain else "database_unchanged"
        )
        self.save(f"restoring_sources_{suffix}")
        # Check every destination before deleting any generated file or moving a backup.
        for name in set(self.state["created"]) | set(self.state["moved"]):
            path = self.corpus / name
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                raise ValueError("Source paths changed to symlinks; preserving the reset journal.")
        for name, digest in self.state["created"].items():
            path = self.corpus / name
            if path.is_symlink() or (
                path.exists()
                and (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest)
            ):
                raise ValueError(
                    "Generated source metadata changed; preserving it and the reset journal."
                )
        for name in self.state["moved"]:
            backup = self.journal / "sources" / name
            destination = self.corpus / name
            if (
                backup.exists()
                and (destination.exists() or destination.is_symlink())
                and name not in self.state["created"]
            ):
                raise ValueError(
                    "New source files appeared; preserving them and the reset journal."
                )
        for name in self.state["created"]:
            path = self.corpus / name
            if path.exists():
                path.unlink()
        for name in reversed(self.state["moved"]):
            backup = self.journal / "sources" / name
            if backup.exists():
                destination = self.corpus / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                backup.replace(destination)
        self.save(f"sources_restored_{suffix}")
        if not database_outcome_uncertain:
            shutil.rmtree(self.journal)

    def finish(self) -> None:
        """Delete backups only after DB commit; retain evidence if cleanup is incomplete."""
        self.save("database_committed_source_cleanup_pending")
        backups = self.journal / "sources"
        if backups.exists():
            shutil.rmtree(backups)
        self.save("complete")
        shutil.rmtree(self.journal)
