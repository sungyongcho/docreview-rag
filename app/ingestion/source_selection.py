"""Resolve the acquisition draft against exact downloaded primary artifacts."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from app.ingestion.manifest import Manifest, ProcessingSelection, SourceArtifact
from app.ingestion.source_catalog import (
    ACQUISITION_COMPANIES,
    approved_company,
    default_acquisition_draft,
)

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
    ready: bool = False
    blocker: str | None = None
    can_redownload: bool = False


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


def resolve_primary(manifest: Manifest, document_id: str, root: Path) -> SourceArtifact:
    """Collapse equivalent primaries without hiding a missing or damaged conflicting revision."""
    candidates = [
        a for a in manifest.artifacts if a.document_id == document_id and a.role == "primary"
    ]
    label = next(d for d in manifest.documents if d.document_id == document_id)
    scope = f"{label.issuer} FY{label.fiscal_year}"
    identities = {(a.sha256, a.byte_length, a.encoding) for a in candidates}
    if len(identities) > 1:
        raise ValueError(
            f"Conflicting primary sources: {scope}. Inspect manifest.json and reacquire "
            "the intended filing before parsing. Artifacts: "
            + ", ".join(sorted(a.artifact_id for a in candidates))
        )
    valid = []
    failures = []
    for artifact in candidates:
        try:
            artifact.read(root)
        except (OSError, ValueError, UnicodeError) as error:
            failures.append(str(error))
        else:
            valid.append(artifact)
    if not valid:
        reason = failures[0] if failures else "No primary artifact is registered."
        raise SourceDownloadRequiredError(
            f"Source is not ready: {scope}. Download it again in Filings. {reason}"
        )
    return min(valid, key=lambda a: (a.path, a.artifact_id))


def source_inventory(root: Path) -> tuple[SourceInventory, ...]:
    """Expose acquisition-only availability and the same primary decision used by execution."""
    try:
        manifest = acquired_catalog(root)
    except OSError, ValueError:
        return ()  # The canonical manifest summary reports its invalid state separately.
    if manifest is None:
        return ()
    rows = []
    pair_counts: dict[tuple[str, str, int], int] = {}
    for document in manifest.documents:
        key = (document.registry, document.issuer.upper(), document.fiscal_year)
        pair_counts[key] = pair_counts.get(key, 0) + 1
    for document in manifest.documents:
        if not approved_company(document.registry, document.issuer):
            continue
        primaries = [
            a
            for a in manifest.artifacts
            if a.document_id == document.document_id and a.role == "primary"
        ]
        present = any(
            (root / a.path).resolve().is_relative_to(root.resolve()) and (root / a.path).is_file()
            for a in primaries
        )
        blocker = None
        can_redownload = False
        try:
            resolve_primary(manifest, document.document_id, root)
        except ValueError as error:
            blocker = str(error)
            can_redownload = isinstance(error, SourceDownloadRequiredError)
        if pair_counts[(document.registry, document.issuer.upper(), document.fiscal_year)] > 1:
            can_redownload = False
            blocker = (
                f"Ambiguous filing identity: {document.issuer} FY{document.fiscal_year}. "
                "Inspect manifest.json before parsing."
            )
        rows.append(
            SourceInventory(
                "manifest.json",
                document.document_id,
                document.registry,
                document.issuer,
                next((a for a in document.aliases if a != document.issuer), document.issuer),
                document.fiscal_year,
                present,
                blocker is None,
                blocker,
                can_redownload,
            )
        )
    return tuple(rows)


def acquisition_draft(root: Path, sources: tuple[SourceInventory, ...]) -> dict[str, object]:
    """Return explicit reset intent with a revision, never infer choices from disk contents."""
    path = root / DRAFT_NAME
    value = default_acquisition_draft()
    revision = "default-v1"
    if path.exists():
        if path.is_symlink():
            raise ValueError("acquisition draft must not be a symlink")
        raw = path.read_text()
        stored = json.loads(raw)
        if not isinstance(stored, dict) or set(stored) - {"identifiers", "years", "pairs"}:
            raise ValueError("invalid persisted acquisition draft")
        identifiers = stored.get("identifiers")
        years = stored.get("years")
        if (
            not isinstance(identifiers, list)
            or not all(isinstance(v, str) for v in identifiers)
            or not isinstance(years, list)
            or not all(type(v) is int and 1900 <= v <= 2100 for v in years)
        ):
            raise ValueError("invalid persisted acquisition draft")
        if identifiers and years:
            pairs = stored.get(
                "pairs",
                [
                    {"registry": company.registry, "issuer": company.issuer, "year": year}
                    for company in ACQUISITION_COMPANIES
                    if company.issuer in identifiers
                    for year in years
                ],
            )
            if not isinstance(pairs, list) or any(
                not isinstance(p, dict)
                or set(p) != {"registry", "issuer", "year"}
                or not isinstance(p["issuer"], str)
                or not approved_company(p["registry"], p["issuer"])
                or type(p["year"]) is not int
                or not 1900 <= p["year"] <= 2100
                for p in pairs
            ):
                raise ValueError("invalid persisted acquisition pairs")
            value = {"identifiers": identifiers, "years": years, "pairs": pairs}
        revision = hashlib.sha256(f"{path.stat().st_mtime_ns}:{raw}".encode()).hexdigest()[:24]
    return {**value, "revision": revision}


def record_selection(
    root: Path, identifiers: tuple[str, ...], years: tuple[int, ...]
) -> tuple[str, str]:
    """Persist one immutable selection, rejecting missing or ambiguous acquired sources."""
    if not identifiers or not years:
        raise ValueError("Choose companies and fiscal years in Filings first.")
    identities = {value.upper() for value in identifiers}
    requested = {(issuer, year) for issuer in identities for year in years}
    found = set()
    documents = {}
    artifacts = {}
    corpus = None
    manifest = acquired_catalog(root)
    if manifest is None:
        raise ValueError("Download missing sources in Filings: no acquisition manifest.json")
    for document in manifest.documents:
        key = (document.issuer.upper(), document.fiscal_year)
        if key not in requested:
            continue
        if not approved_company(document.registry, document.issuer):
            raise ValueError(f"Unsupported acquisition company: {document.issuer}")
        artifact = resolve_primary(manifest, document.document_id, root)
        if key in found:
            raise ValueError(
                f"Ambiguous filing identity: {document.issuer} FY{document.fiscal_year}. "
                "Inspect manifest.json before parsing."
            )
        corpus = manifest.corpus
        documents[document.document_id] = document
        artifacts[artifact.artifact_id] = artifact
        found.add(key)
    missing = requested - found
    if missing or corpus is None:
        raise ValueError(
            "Download missing sources in Filings: "
            + ", ".join(f"{issuer} FY{year}" for issuer, year in sorted(missing))
        )
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
