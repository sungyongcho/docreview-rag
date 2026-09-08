"""Resolve the acquisition draft against exact downloaded primary artifacts."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from app.ingestion.acquisition import publish_bytes
from app.ingestion.manifest import Manifest, ProcessingSelection, SourceArtifact
from app.ingestion.source_catalog import (
    approved_company,
    default_acquisition_draft,
)
from app.ingestion.source_publication import fixed_path
from app.ingestion.source_storage import JOURNAL, confined_path, source_lock, validate_source

DRAFT_NAME = "acquisition-draft.json"


@dataclass(frozen=True, slots=True)
class SourceInventory:
    """Expose filing identity and actual local availability before database ingestion."""

    manifest: str
    document_id: str
    registry: str
    issuer: str
    name: str
    fiscal_year: int
    on_disk: bool
    ready: bool
    can_redownload: bool
    filing_id: str
    blocker: str | None = None


def catalogs(root: Path, *, strict: bool = True) -> tuple[tuple[Path, Manifest], ...]:
    """Read canonical source catalogs, excluding immutable generated job selections."""
    rows = []
    for path in sorted(root.glob("*.json")):
        if path.name.startswith("selected-") or not (
            path.name == "manifest.json" or path.name.endswith("-manifest.json")
        ):
            continue
        try:
            if path.is_symlink() or path.resolve().parent != root.resolve():
                raise ValueError("manifest resolves outside the corpus root")
            rows.append((path, Manifest.read(path)))
        except OSError, ValueError:
            if strict:
                raise
            # Invalid catalogs stay visible as invalid in the companion manifest summaries.
            continue
    return tuple(rows)


def acquired_catalog(root: Path) -> Manifest | None:
    """Read only the canonical catalog written by the two acquisition adapters."""
    path = root / "manifest.json"
    if path.is_symlink():
        raise ValueError("acquisition manifest must not be a symlink")
    return Manifest.read(path) if path.exists() else None


class SourceDownloadRequiredError(ValueError):
    """Identify a missing or invalid source that acquisition can download again."""


def resolve_primary(
    manifest: Manifest, document_id: str, root: Path, *, cached: bool = False
) -> SourceArtifact:
    """Validate one current fixed-path bundle without legacy selection or migration."""
    document = next(d for d in manifest.documents if d.document_id == document_id)
    sources = [
        a
        for a in manifest.artifacts
        if a.document_id == document_id and a.role in {"primary", "archive"}
    ]
    primaries = [a for a in sources if a.role == "primary"]
    archives = [a for a in sources if a.role == "archive"]
    scope = f"{document.issuer} FY{document.fiscal_year}"
    if len(primaries) > 1:
        raise ValueError(
            f"Conflicting primary sources: {scope}. "
            "Multiple registrations require explicit cleanup."
        )
    if len(archives) > 1:
        raise ValueError(
            "Archive identity is ambiguous: multiple ZIP registrations require explicit cleanup."
        )
    for artifact in sources:
        expected = fixed_path(document.registry, document.filing_id, artifact.role)
        if artifact.path != expected:
            raise ValueError(
                f"Unsupported current source path: {artifact.path}. "
                f"Expected {expected}; reset and download the filing again."
            )
    if not primaries:
        raise SourceDownloadRequiredError(
            f"Source is not ready: {scope}. Download it again in Filings."
        )
    primary = primaries[0]
    if document.registry == "dart":
        if not archives:
            raise SourceDownloadRequiredError(
                "Registered DART archive is missing. Download the filing again in Filings."
            )
        if primary.acquisition.archive_sha256 != archives[0].sha256:
            raise ValueError(
                "Archive identity is unlinked; inspect manifest.json before acquisition."
            )
    for artifact in sources:
        try:
            validate_source(artifact, root, cached=cached)
        except (OSError, ValueError, UnicodeError) as error:
            label = (
                "Registered DART archive is not ready"
                if artifact.role == "archive"
                else f"Source is not ready: {scope}"
            )
            raise SourceDownloadRequiredError(
                f"{label}. Download it again in Filings. {artifact.path}: {error}"
            ) from error
    return primary


def source_inventory(root: Path) -> tuple[SourceInventory, ...]:
    """Expose acquisition-only availability and the same primary decision used by execution."""
    try:
        manifest = acquired_catalog(root)
    except OSError, ValueError:
        return ()  # The canonical manifest summary reports its invalid state separately.
    if manifest is None:
        return ()
    rows = []
    for document in manifest.documents:
        if not approved_company(document.registry, document.issuer):
            continue
        present = False
        blocker = None
        can_redownload = False
        try:
            present = confined_path(
                root, fixed_path(document.registry, document.filing_id, "primary")
            ).is_file()
            resolve_primary(manifest, document.document_id, root, cached=True)
            if (root / JOURNAL).exists():
                raise SourceDownloadRequiredError(
                    "Source publication is pending; retry acquisition to recover it."
                )
        except ValueError as error:
            blocker = str(error)
            can_redownload = isinstance(error, SourceDownloadRequiredError)
        rows.append(
            SourceInventory(
                manifest="manifest.json",
                document_id=document.document_id,
                registry=document.registry,
                issuer=document.issuer,
                name=next((a for a in document.aliases if a != document.issuer), document.issuer),
                fiscal_year=document.fiscal_year,
                on_disk=present,
                ready=blocker is None,
                blocker=blocker,
                can_redownload=can_redownload,
                filing_id=document.filing_id,
            )
        )
    return tuple(rows)


def acquisition_draft(root: Path) -> dict[str, object]:
    """Return explicit reset intent with a revision, never infer choices from disk contents."""
    path = root / DRAFT_NAME
    value = default_acquisition_draft()
    revision = "default-v1"
    if path.exists():
        if path.is_symlink():
            raise ValueError("acquisition draft must not be a symlink")
        raw = path.read_text()
        stored = json.loads(raw)
        if not isinstance(stored, dict) or set(stored) != {"identifiers", "years", "pairs"}:
            raise ValueError("invalid persisted acquisition draft; exact pairs are required")
        identifiers, years, pairs = stored["identifiers"], stored["years"], stored["pairs"]
        if (
            not isinstance(identifiers, list)
            or not all(isinstance(v, str) for v in identifiers)
            or not isinstance(years, list)
            or not all(type(v) is int and 1900 <= v <= 2100 for v in years)
            or not isinstance(pairs, list)
            or any(
                not isinstance(pair, dict)
                or set(pair) != {"registry", "issuer", "year"}
                or not isinstance(pair["issuer"], str)
                or not approved_company(pair["registry"], pair["issuer"])
                or type(pair["year"]) is not int
                or not 1900 <= pair["year"] <= 2100
                for pair in pairs
            )
        ):
            raise ValueError("invalid persisted acquisition pairs")
        keys = {(pair["registry"], pair["issuer"], pair["year"]) for pair in pairs}
        if (
            len(keys) != len(pairs)
            or set(identifiers) != {pair["issuer"] for pair in pairs}
            or set(years) != {pair["year"] for pair in pairs}
        ):
            raise ValueError("acquisition draft fields disagree with its exact pairs")
        value = stored
        revision = hashlib.sha256(f"{path.stat().st_mtime_ns}:{raw}".encode()).hexdigest()[:24]
    return {**value, "revision": revision}


def record_selection(
    root: Path,
    identifiers: tuple[str, ...],
    years: tuple[int, ...],
    document_ids: tuple[str, ...],
) -> tuple[str, str]:
    """Pin selected inputs under the same lock used by acquisition and deletion."""
    with source_lock(root):
        return _record_selection(root, identifiers, years, document_ids)


def _record_selection(
    root: Path,
    identifiers: tuple[str, ...],
    years: tuple[int, ...],
    document_ids: tuple[str, ...],
) -> tuple[str, str]:
    """Persist one immutable selection, rejecting missing or ambiguous acquired sources."""
    if not identifiers or not years:
        raise ValueError("Choose companies and fiscal years in Filings first.")
    if not document_ids or len(set(document_ids)) != len(document_ids):
        raise ValueError("Choose unique downloaded document IDs before parsing.")
    manifest = acquired_catalog(root)
    if manifest is None:
        raise ValueError("Download missing sources in Filings: no acquisition manifest.json")
    requested = {(issuer.upper(), year) for issuer in identifiers for year in years}
    exact_ids = set(document_ids)
    matching = [d for d in manifest.documents if d.document_id in exact_ids]
    if len(matching) != len(exact_ids) or any(
        (d.issuer.upper(), d.fiscal_year) not in requested for d in matching
    ):
        raise ValueError("Selected filing identities changed; reselect downloaded originals.")
    documents = {}
    artifacts = {}
    corpus = manifest.corpus
    for document in matching:
        if not approved_company(document.registry, document.issuer):
            raise ValueError(f"Unsupported acquisition company: {document.issuer}")
        artifact = resolve_primary(manifest, document.document_id, root)
        documents[document.document_id] = document
        artifacts[artifact.artifact_id] = artifact
    # A future current-source replacement must not change an already queued job input.
    pinned = {}
    for identity, artifact in artifacts.items():
        document = documents[artifact.document_id]
        payload = artifact.read_bytes(root)
        suffix = ".html" if document.registry == "sec" else ".xml"
        relative = f"inputs/{document.registry}/{document.filing_id}/{artifact.sha256}{suffix}"
        destination = confined_path(root, relative)
        if destination.exists() and destination.read_bytes() != payload:
            raise ValueError("Recorded job input changed; refusing to overwrite.")
        if not destination.exists():
            publish_bytes(root, relative, payload)
        pinned[identity] = artifact.model_copy(update={"path": relative})
    artifacts = pinned
    ordered_documents = tuple(sorted(documents.values(), key=lambda document: document.document_id))
    ordered_artifacts = tuple(sorted(artifacts.values(), key=lambda artifact: artifact.artifact_id))
    payload = json.dumps(
        {
            "corpus": corpus.model_dump(mode="json"),
            "documents": [document.model_dump(mode="json") for document in ordered_documents],
            "artifacts": [artifact.model_dump(mode="json") for artifact in ordered_artifacts],
        },
        sort_keys=True,
    )
    selection_id = "selected-" + hashlib.sha256(payload.encode()).hexdigest()[:24]
    selected = Manifest(
        corpus=corpus,
        documents=ordered_documents,
        artifacts=ordered_artifacts,
        selections=(
            ProcessingSelection(selection_id=selection_id, artifact_ids=tuple(sorted(artifacts))),
        ),
    )
    name = f"{selection_id}-manifest.json"
    path = root / name
    if path.exists():
        if path.is_symlink() or Manifest.read(path) != selected:
            raise ValueError("Recorded processing selection changed; refusing to overwrite.")
    else:
        selected.write(path)
    return name, selection_id
