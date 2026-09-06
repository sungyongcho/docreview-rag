"""Journal local source changes around a separately transactional database reset."""

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil

from app.ingestion.manifest import Manifest
from app.ingestion.source_selection import DRAFT_NAME

JOURNAL_NAME = ".schema-recreate-journal"


def source_preview(root: Path) -> dict:
    """Fingerprint exact confined raw files and manifests before asking for approval."""
    corpus = root / "data" / "corpus"
    if (root / "data" / JOURNAL_NAME).exists():
        raise ValueError(
            "Unfinished source reset journal exists; inspect "
            "data/.schema-recreate-journal/journal.json before retrying."
        )
    if corpus.is_symlink() or (root / "data").is_symlink():
        raise ValueError("Source reset refuses symlinked data directories.")
    manifests = {}
    raw = set()
    if corpus.exists():
        for path in sorted(corpus.glob("*.json")):
            if path.name != "manifest.json" and not path.name.endswith("-manifest.json"):
                continue
            if path.is_symlink():
                raise ValueError("Source reset refuses symlinked manifests.")
            manifest = Manifest.read(path)
            manifests[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            raw.update(artifact.path for artifact in manifest.artifacts)
        # Include interrupted acquisition files in the registry's raw formats.
        raw.update(
            str(path.relative_to(corpus))
            for path in corpus.rglob("*")
            if path.suffix.lower() in {".html", ".htm", ".xml", ".zip"}
        )
    if raw & (set(manifests) | {DRAFT_NAME}):
        raise ValueError("Source artifact paths collide with manifest or draft metadata.")
    files = {}
    for relative in sorted(raw):
        path = corpus / relative
        if any(
            parent.is_symlink() for parent in (path, *path.parents)
        ) or not path.resolve().is_relative_to(corpus.resolve()):
            raise ValueError("Source reset refuses symlinked or escaped raw paths.")
        if path.exists():
            if not path.is_file():
                raise ValueError("Source artifact is not a regular file.")
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    draft = corpus / DRAFT_NAME
    if draft.is_symlink():
        raise ValueError("Source reset refuses symlinked drafts.")
    return {
        "files": files,
        "manifests": manifests,
        "draft": hashlib.sha256(draft.read_bytes()).hexdigest() if draft.exists() else None,
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
