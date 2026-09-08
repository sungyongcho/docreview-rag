"""Publish acquired bytes and explicit selections in the common corpus manifest."""

from collections.abc import Sequence
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import tempfile

from app.ingestion.manifest import (
    CorpusIdentity,
    DocumentReference,
    Manifest,
    SourceArtifact,
)


@dataclass(frozen=True, slots=True)
class AcquiredFiling:
    """One common document and the exact artifacts acquired for it."""

    document: DocumentReference
    artifacts: tuple[SourceArtifact, ...]
    payloads: tuple[bytes, ...] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        """Require one coherent source artifact group for the document."""
        if any(artifact.document_id != self.document.document_id for artifact in self.artifacts):
            raise ValueError("acquired artifact belongs to another document")
        if len({artifact.artifact_id for artifact in self.artifacts}) != len(self.artifacts):
            raise ValueError("acquisition contains duplicate artifacts")
        if len(self.payloads) != len(self.artifacts):
            raise ValueError("acquisition payloads must match artifacts")
        _ = self.primary
        roles = [artifact.role for artifact in self.artifacts]
        expected = {"primary", "archive"} if self.document.registry == "dart" else {"primary"}
        if len(roles) != len(expected) or set(roles) != expected:
            raise ValueError("acquisition requires the complete current source bundle")

    @property
    def primary(self) -> SourceArtifact:
        """Return the single selected primary source artifact."""
        matches = [artifact for artifact in self.artifacts if artifact.role == "primary"]
        if len(matches) != 1:
            raise ValueError("acquisition must contain exactly one primary artifact")
        return matches[0]


def read_catalog(path: Path) -> Manifest:
    """Read the canonical manifest or initialize a new corpus identity."""
    if path.name != "manifest.json":
        raise ValueError("acquisition requires the canonical manifest.json")
    if path.exists():
        return Manifest.read(path)
    return Manifest(corpus=CorpusIdentity(corpus_id="filings", name="Filing corpus"))


def selection_identity(registry: str, issuers: Sequence[str], years: Sequence[int]) -> str:
    """Identify an acquisition request deterministically without creating another catalog."""
    scope = json.dumps([registry, sorted(set(issuers)), sorted(set(years))], separators=(",", ":"))
    return f"{registry}-{hashlib.sha256(scope.encode()).hexdigest()[:16]}"


def publish_bytes(corpus_root: Path, relative_path: str, payload: bytes) -> Path:
    """Atomically publish complete bytes beneath the confined corpus root."""
    SourceArtifact.validate_path(relative_path)
    corpus_root.mkdir(parents=True, exist_ok=True)
    root = corpus_root.resolve(strict=True)
    destination = root / relative_path
    if not destination.resolve().is_relative_to(root):
        raise ValueError("artifact resolves outside the corpus root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o664)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination


def current_primary(
    manifest: Manifest, document_id: str, corpus_root: Path
) -> SourceArtifact | None:
    """Return an unambiguous verified original; conflicting revisions require intervention."""
    from app.ingestion.source_selection import SourceDownloadRequiredError, resolve_primary

    if not any(d.document_id == document_id for d in manifest.documents):
        return None
    try:
        return resolve_primary(manifest, document_id, corpus_root)
    except SourceDownloadRequiredError:
        return None
