"""Resolve the acquisition draft against exact downloaded primary artifacts."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from app.ingestion.manifest import Manifest, ProcessingSelection

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


def source_inventory(root: Path) -> tuple[SourceInventory, ...]:
    """List every registered document once per catalog with primary-file presence."""
    rows = []
    for path, manifest in catalogs(root, strict=False):
        for document in manifest.documents:
            primary = [
                a
                for a in manifest.artifacts
                if a.document_id == document.document_id and a.role == "primary"
            ]
            present = any(
                (root / a.path).resolve().is_relative_to(root.resolve())
                and (root / a.path).is_file()
                for a in primary
            )
            rows.append(
                SourceInventory(
                    path.name,
                    document.document_id,
                    document.registry,
                    document.issuer,
                    next((a for a in document.aliases if a != document.issuer), document.issuer),
                    document.fiscal_year,
                    present,
                )
            )
    return tuple(rows)


def acquisition_draft(root: Path, sources: tuple[SourceInventory, ...]) -> dict[str, list]:
    """Initialize from actual sources, falling back to an explicit clean-start preset."""
    present = [row for row in sources if row.on_disk]
    if present:
        return {
            "identifiers": sorted({row.issuer for row in present}),
            "years": sorted({row.fiscal_year for row in present}),
        }
    path = root / DRAFT_NAME
    if not path.exists():
        return {"identifiers": [], "years": []}
    if path.is_symlink():
        raise ValueError("acquisition draft must not be a symlink")
    value = json.loads(path.read_text())
    if (
        not isinstance(value, dict)
        or set(value) != {"identifiers", "years"}
        or not isinstance(value["identifiers"], list)
        or not all(isinstance(v, str) for v in value["identifiers"])
        or not isinstance(value["years"], list)
        or not all(type(v) is int and 1900 <= v <= 2100 for v in value["years"])
    ):
        raise ValueError("invalid persisted acquisition draft")
    return value


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
    for _, manifest in catalogs(root):
        for document in manifest.documents:
            key = (document.issuer.upper(), document.fiscal_year)
            if key not in requested:
                continue
            primary = [
                a
                for a in manifest.artifacts
                if a.document_id == document.document_id and a.role == "primary"
            ]
            if len(primary) != 1:
                raise ValueError(
                    f"Missing or ambiguous primary source: {document.issuer} "
                    f"FY{document.fiscal_year}"
                )
            artifact = primary[0]
            try:
                artifact.read_bytes(root)
            except OSError as error:
                raise ValueError(
                    f"Missing source: {document.issuer} FY{document.fiscal_year}. "
                    "Return to Filings."
                ) from error
            if corpus is not None and corpus != manifest.corpus:
                raise ValueError(
                    "Selected sources span different corpora; use Advanced selections."
                )
            corpus = manifest.corpus
            if document.document_id in documents and (
                documents[document.document_id] != document
                or artifacts.get(artifact.artifact_id) != artifact
            ):
                raise ValueError("Selected source catalogs disagree; use Advanced selections.")
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
