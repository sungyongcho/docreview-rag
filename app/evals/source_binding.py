"""Bind golden evidence to exact official filings without acquisition-selection aliases."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from app.evals.artifacts import read_strict_json
from app.evals.loader import (
    GOLDEN_CASES,
    GoldenDataError,
    validate_golden_sources,
    validate_unique_cases,
)
from app.evals.types import GoldenCase
from app.ingestion.manifest import FilingSource, Manifest
from app.ingestion.source_catalog import ACQUISITION_COMPANIES
from app.ingestion.source_selection import SourceDownloadRequiredError, resolve_primary

REQUIREMENTS_PATH = Path(__file__).resolve().parents[2] / "data/golden/requirements/sources.json"


class FilingRequirement(BaseModel):
    """Explicit identity for a bundled evidence document, independent of its local ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    registry: Literal["sec", "dart"]
    issuer: str
    fiscal_year: int
    filing_id: str


@dataclass(frozen=True)
class SourceCheck:
    """One evidence-document requirement and its current source validation result."""

    golden_document_id: str
    registry: str
    issuer: str
    fiscal_year: int | None
    filing_id: str | None
    document_id: str | None
    state: Literal["ready", "source_missing", "source_invalid"]
    detail: str | None = None
    company_name: str | None = None


@dataclass(frozen=True)
class BoundGolden:
    """Validated runtime IDs and source checks; original golden files remain unchanged."""

    cases: tuple[GoldenCase, ...]
    sources: tuple[SourceCheck, ...]

    @property
    def ready(self) -> bool:
        """Require every reference to match the exact original bytes and span."""
        return all(source.state == "ready" for source in self.sources)


def bind_golden(
    payload: object,
    manifest_path: Path,
    registry: str,
    *,
    requirements_path: Path = REQUIREMENTS_PATH,
) -> BoundGolden:
    """Resolve explicit filing identities and rebind answer IDs only after source verification."""
    cases = GOLDEN_CASES.validate_python(payload)
    if not cases:
        raise GoldenDataError("The golden set contains no evaluation questions.")
    validate_unique_cases(cases)
    requirements = TypeAdapter(dict[str, FilingRequirement]).validate_python(
        read_strict_json(requirements_path, error=GoldenDataError)
    )
    if manifest_path.exists():
        manifest = Manifest.read(manifest_path)
    else:
        manifest = None
    checks = []
    mapping = {}
    root = manifest_path.resolve().parent
    ids = sorted({answer.doc_id for case in cases for answer in case.answers})
    for golden_id in ids:
        requirement = requirements.get(golden_id)
        documents = () if manifest is None else manifest.documents
        if requirement is not None:
            candidates = [
                d
                for d in documents
                if d.registry == requirement.registry
                and d.filing_id == requirement.filing_id
                and d.issuer == requirement.issuer
                and d.fiscal_year == requirement.fiscal_year
            ]
        else:
            candidates = [d for d in documents if d.document_id == golden_id]
        document = candidates[0] if len(candidates) == 1 else None
        identity = requirement or document
        state = "source_missing"
        detail = "Required original is not acquired."
        if len(candidates) > 1:
            state, detail = "source_invalid", "Official filing identity is ambiguous."
        elif identity is not None and identity.registry != registry:
            state, detail = "source_invalid", "Evidence belongs to another source registry."
        elif document is not None and manifest is not None:
            try:
                artifact = resolve_primary(manifest, document.document_id, root)
                source = FilingSource(document, artifact, root, manifest.corpus)
                relevant = [
                    case.model_copy(
                        update={"answers": tuple(a for a in case.answers if a.doc_id == golden_id)}
                    )
                    for case in cases
                    if any(a.doc_id == golden_id for a in case.answers)
                ]
                validate_golden_sources(relevant, manifest_path, sources={golden_id: source})
                mapping[golden_id] = document.document_id
                state, detail = "ready", None
            except SourceDownloadRequiredError as error:
                state, detail = "source_missing", str(error)
            except (OSError, ValueError) as error:
                state, detail = "source_invalid", str(error)
        checks.append(
            SourceCheck(
                golden_id,
                identity.registry if identity else registry,
                identity.issuer if identity else golden_id,
                identity.fiscal_year if identity else None,
                identity.filing_id if identity else None,
                document.document_id if document else None,
                state,
                detail,
                next(
                    (
                        company.name
                        for company in ACQUISITION_COMPANIES
                        if identity is not None
                        and company.registry == identity.registry
                        and company.issuer == identity.issuer
                    ),
                    next(
                        (alias for alias in document.aliases if alias != document.issuer),
                        document.issuer,
                    )
                    if document
                    else None,
                ),
            )
        )
    bound = tuple(
        case.model_copy(
            update={
                "answers": tuple(
                    answer.model_copy(update={"doc_id": mapping.get(answer.doc_id, answer.doc_id)})
                    for answer in case.answers
                )
            }
        )
        for case in cases
    )
    validate_unique_cases(bound)
    return BoundGolden(bound, tuple(checks))


def matrix_scope(manifest_path: Path, registry: str) -> Manifest:
    """Freeze all registered originals of the selected registry for an isolated matrix run."""
    from app.ingestion.manifest import ProcessingSelection

    manifest = Manifest.read(manifest_path)
    documents = tuple(document for document in manifest.documents if document.registry == registry)
    primaries = tuple(
        resolve_primary(manifest, document.document_id, manifest_path.parent)
        for document in documents
    )
    if not primaries:
        raise GoldenDataError("No source documents are available for this evaluation registry.")
    ids = {document.document_id for document in documents}
    return Manifest(
        corpus=manifest.corpus,
        documents=documents,
        artifacts=tuple(artifact for artifact in manifest.artifacts if artifact.document_id in ids),
        selections=(
            ProcessingSelection(
                selection_id="evaluation-scope",
                artifact_ids=tuple(artifact.artifact_id for artifact in primaries),
            ),
        ),
    )
