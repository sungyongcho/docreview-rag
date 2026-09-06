"""Validated corpus identities, acquired artifacts, and processing selections."""

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Contract(BaseModel):
    """Reject undeclared fields at every manifest boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CorpusIdentity(Contract):
    """Identify a corpus independently of its filesystem location."""

    corpus_id: Identifier
    name: Annotated[str, Field(min_length=1)]


class SecMetadata(Contract):
    """Preserve SEC acquisition identifiers."""

    cik: Annotated[str, Field(pattern=r"^[0-9]{10}$")]
    accession: Annotated[str, Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")]
    primary_document: Annotated[str, Field(min_length=1)]


class DartMetadata(Contract):
    """Preserve DART acquisition identifiers and report labels."""

    corp_code: Annotated[str, Field(pattern=r"^[0-9]{8}$")]
    receipt_number: Annotated[str, Field(pattern=r"^[0-9]{14}$")]
    report_code: Annotated[str, Field(min_length=1)]
    report_name: Annotated[str, Field(min_length=1)]


class DocumentReference(Contract):
    """Describe one filing independently of acquisition and processing state."""

    document_id: Identifier
    registry: Literal["sec", "dart"]
    language: Literal["en", "ko"]
    issuer: Annotated[str, Field(min_length=1)]
    issuer_id: Identifier
    aliases: tuple[str, ...] = ()
    filing_id: Identifier
    fiscal_year: Annotated[int, Field(ge=1900, le=9999)]
    form: Annotated[str, Field(min_length=1)]
    filing_date: date
    report_period: date
    source_url: Annotated[str, Field(pattern=r"^https?://[^\s]+$")]
    sec: SecMetadata | None = None
    dart: DartMetadata | None = None

    @model_validator(mode="after")
    def validate_registry(self) -> Self:
        """Bind shared identities to exactly one source-specific structure."""
        if self.registry == "sec":
            if self.sec is None or self.dart is not None or self.language != "en":
                raise ValueError("SEC filings require only SEC metadata and English language")
            if (self.issuer_id, self.filing_id) != (self.sec.cik, self.sec.accession):
                raise ValueError("SEC identifiers disagree with shared filing metadata")
        else:
            if self.dart is None or self.sec is not None or self.language != "ko":
                raise ValueError("DART filings require only DART metadata and Korean language")
            if (self.issuer_id, self.filing_id) != (self.dart.corp_code, self.dart.receipt_number):
                raise ValueError("DART identifiers disagree with shared filing metadata")
        return self


class Acquisition(Contract):
    """Record where and when an artifact was acquired."""

    acquired_at: datetime | None
    url: Annotated[str, Field(pattern=r"^https?://[^\s]+$")]
    media_type: Annotated[str, Field(min_length=1)]
    archive_sha256: Digest | None = None
    archive_member: str | None = None
    original_encoding: str | None = None
    normalized_separator_count: Annotated[int, Field(ge=0)] = 0

    @field_validator("acquired_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        """Require an unambiguous timestamp when acquisition time is known."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acquired_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_archive(self) -> Self:
        """Require archive member provenance to identify the acquired archive."""
        if self.archive_member is not None and self.archive_sha256 is None:
            raise ValueError("archive members require the acquired archive digest")
        return self


class SourceArtifact(Contract):
    """Identify exact acquired bytes and their decoding contract."""

    artifact_id: Identifier
    document_id: Identifier
    role: Literal["primary", "archive", "attachment"]
    path: str
    sha256: Digest
    byte_length: Annotated[int, Field(gt=0)]
    encoding: Literal["utf-8", "euc-kr", "cp949"] | None
    acquisition: Acquisition

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        """Require canonical corpus-relative paths without traversal."""
        path = PurePosixPath(value)
        if (
            not value
            or "\\" in value
            or "\x00" in value
            or path.is_absolute()
            or any(part in {".", "..", ""} for part in value.split("/"))
            or ":" in value
        ):
            raise ValueError("artifact path must be a canonical corpus-relative path")
        return value

    @model_validator(mode="after")
    def validate_encoding(self) -> Self:
        """Require primary text decoding and avoid labeling binary archives as text."""
        if self.role == "primary" and self.encoding is None:
            raise ValueError("primary sources require an encoding")
        if self.role == "archive" and self.encoding is not None:
            raise ValueError("binary archives must not declare a text encoding")
        return self

    def read_bytes(self, corpus_root: Path) -> bytes:
        """Verify source confinement and exact acquired bytes."""
        root = corpus_root.resolve(strict=True)
        source = (root / self.path).resolve(strict=True)
        if not source.is_relative_to(root):
            raise ValueError("artifact resolves outside the corpus root")
        raw = source.read_bytes()
        if len(raw) != self.byte_length or hashlib.sha256(raw).hexdigest() != self.sha256:
            raise ValueError(f"artifact bytes disagree with manifest: {self.artifact_id}")
        return raw

    def read(self, corpus_root: Path) -> str:
        """Decode verified source bytes without replacing undecodable evidence."""
        if self.encoding is None:
            raise ValueError("binary artifacts cannot be decoded as source text")
        return self.read_bytes(corpus_root).decode(self.encoding, errors="strict")


class ProcessingSelection(Contract):
    """Select exact acquired artifacts for named processing work."""

    selection_id: Identifier
    artifact_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]


@dataclass(frozen=True, slots=True)
class FilingSource:
    """Bind typed filing identity to a selected artifact and its local corpus root."""

    document: DocumentReference
    artifact: SourceArtifact
    corpus_root: Path
    corpus: CorpusIdentity

    def __post_init__(self) -> None:
        """Reject a source bound to another filing or a non-primary artifact."""
        if self.artifact.document_id != self.document.document_id:
            raise ValueError("source artifact belongs to another document")
        if self.artifact.role != "primary":
            raise ValueError("filing parsing requires a primary source artifact")

    def read(self) -> str:
        """Read the exact verified source selected for parsing."""
        return self.artifact.read(self.corpus_root)


class Manifest(Contract):
    """Describe a corpus without duplicating its catalog for each processing run."""

    corpus: CorpusIdentity
    documents: tuple[DocumentReference, ...] = ()
    artifacts: tuple[SourceArtifact, ...] = ()
    selections: tuple[ProcessingSelection, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        """Reject duplicate identities and disconnected processing selections."""
        documents = {document.document_id: document for document in self.documents}
        artifacts = {artifact.artifact_id: artifact for artifact in self.artifacts}
        if len(documents) != len(self.documents) or len(artifacts) != len(self.artifacts):
            raise ValueError("manifest contains duplicate document or artifact identities")
        filing_keys = {(document.registry, document.filing_id) for document in self.documents}
        if len(filing_keys) != len(self.documents):
            raise ValueError("a filing must have exactly one document identity")
        if len({artifact.path for artifact in self.artifacts}) != len(self.artifacts):
            raise ValueError("artifact paths must be unique")
        if any(artifact.document_id not in documents for artifact in self.artifacts):
            raise ValueError("artifact references an unknown document")
        if len({selection.selection_id for selection in self.selections}) != len(self.selections):
            raise ValueError("selection identities must be unique")
        for selection in self.selections:
            if len(set(selection.artifact_ids)) != len(selection.artifact_ids):
                raise ValueError("selection contains duplicate artifacts")
            if any(identity not in artifacts for identity in selection.artifact_ids):
                raise ValueError("selection references an unknown artifact")
            selected = [artifacts[identity] for identity in selection.artifact_ids]
            if any(artifact.role != "primary" for artifact in selected):
                raise ValueError("processing selections require primary source artifacts")
            if len({artifact.document_id for artifact in selected}) != len(selected):
                raise ValueError("selection must choose one primary artifact per document")
        return self

    def selected_sources(self, selection_id: str, corpus_root: Path) -> tuple[FilingSource, ...]:
        """Resolve exactly one explicit selection in deterministic document order."""
        selection = next(
            (selection for selection in self.selections if selection.selection_id == selection_id),
            None,
        )
        if selection is None:
            raise ValueError(f"unknown processing selection: {selection_id}")
        documents = {document.document_id: document for document in self.documents}
        artifacts = {artifact.artifact_id: artifact for artifact in self.artifacts}
        selected = [artifacts[identity] for identity in selection.artifact_ids]
        return tuple(
            FilingSource(documents[artifact.document_id], artifact, corpus_root, self.corpus)
            for artifact in sorted(selected, key=lambda artifact: artifact.document_id)
        )

    @classmethod
    def read(cls, path: Path) -> Self:
        """Read only the common manifest contract."""
        return cls.model_validate_json(path.read_bytes())

    def write(self, path: Path) -> None:
        """Atomically publish a validated manifest without partial destination writes."""
        payload = self.model_dump_json(indent=2) + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                os.fchmod(output.fileno(), 0o664)
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
