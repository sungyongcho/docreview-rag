"""Decode DART archives and bind canonical source bytes to original acquisition evidence."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import io
import re
from typing import Final
import zipfile

from app.ingestion.sources.models import (
    AcquiredFiling,
    Acquisition,
    DartMetadata,
    DocumentReference,
    SourceArtifact,
)
from app.ingestion.sources.storage import fixed_path

DART_BASE: Final[str] = "https://opendart.fss.or.kr/api"


DART_VIEWER: Final[str] = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


ANNUAL_REPORT_FORM: Final[str] = "사업보고서"


XML_DECLARATION_RE: Final[re.Pattern[str]] = re.compile(
    r"(<\?xml[^>]*?encoding\s*=\s*[\"'])([^\"']+)([\"'])", re.I
)


# Accept only the UTF-8 and Korean codec families DART serves; permissive codecs can hide mojibake.
DECLARED_ENCODINGS: Final[frozenset[str]] = frozenset({"utf-8", "utf-8-sig", "cp949", "euc_kr"})


# Count separators that splitlines treats differently from HTMLParser without rewriting source text.
EXOTIC_SEPARATORS: Final[str] = "\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"


class DartArchiveError(ValueError):
    """A downloaded archive has no unambiguous UTF-8 decodable annual-report source."""


@dataclass(frozen=True, slots=True)
class CorpCode:
    """One issuer's Open DART identity, keyed in practice by its stock code."""

    corp_code: str
    corp_name: str
    stock_code: str


@dataclass(frozen=True, slots=True)
class AnnualReport:
    """One selected 사업보고서 disclosure row."""

    rcept_no: str
    corp_code: str
    corp_name: str
    report_nm: str
    rcept_dt: str


@dataclass(frozen=True, slots=True)
class DocumentArchive:
    """The original ZIP exactly as Open DART served it."""

    rcept_no: str
    zip_bytes: bytes
    archive_sha256: str


def member_names(archive: zipfile.ZipFile) -> list[str]:
    """Return member names, recovering the CP949 names a cleared UTF-8 flag mangles.

    Recovered names are for reporting and selection only. Nothing written to disk is
    named from them, so a mangled name can never reach the manifest or a citation.
    """
    names: list[str] = []
    for info in archive.infolist():
        if info.flag_bits & 0x800:
            names.append(info.filename)
            continue
        try:
            names.append(info.filename.encode("cp437").decode("cp949"))
        except UnicodeError:
            names.append(info.filename)
    return names


def select_primary_member(archive: zipfile.ZipFile, *, rcept_no: str) -> str:
    """Return the member holding the report body itself.

    An observed 사업보고서 archive carries three members: the report, named exactly
    ``{rcept_no}.xml``, and two attachments named ``{rcept_no}_NNNNN.xml``. Selecting
    by name is exact, so no content heuristic is needed and no attachment can be
    mistaken for the report.

    Raises
    ------
    DartArchiveError
        If that member is absent, listing every member that is present.
    """
    target = f"{rcept_no}.xml"
    for info in archive.infolist():
        if info.filename == target:
            return info.filename
    raise DartArchiveError(
        f"archive has no member named {target}; members: {', '.join(member_names(archive))}"
    )


def decode_source(raw: bytes) -> tuple[str, str]:
    """Decode an archived member strictly, returning the text and the encoding used.

    Candidates are tried in order: a UTF-8 BOM, the encoding the XML declaration
    names when it resolves into ``DECLARED_ENCODINGS``, UTF-8, then CP949 as a
    superset of EUC-KR. A declared encoding outside that set is skipped, not fatal —
    the remaining candidates still get their turn. Every attempt is strict — a
    replacement character would be corpus corruption that the source digest would
    then bless as canonical.

    Raises
    ------
    DartArchiveError
        If no candidate decodes the bytes without loss.
    """
    candidates: list[str] = ["utf-8-sig"] if raw[:3] == b"\xef\xbb\xbf" else []
    declared = XML_DECLARATION_RE.search(raw[:400].decode("latin-1", errors="replace"))
    if declared is not None:
        try:
            resolved = codecs.lookup(declared.group(2)).name
        except LookupError:
            resolved = None
        if resolved in DECLARED_ENCODINGS:
            candidates.append(declared.group(2))
    candidates += ["utf-8", "cp949"]

    for encoding in candidates:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise DartArchiveError("no strict decoding succeeded for the selected member")


def canonicalize(text: str) -> tuple[str, int]:
    r"""Return the exact text archived on disk and its exotic-separator count.

    Only two things change, and both are reversible in meaning rather than content:
    line endings become ``\\n``, and the document's own leading XML declaration is
    restamped as UTF-8 because after transcoding the declared encoding would otherwise
    be a lie. Nothing is whitespace-collapsed, entity-expanded, or re-serialized, so
    a character offset into this text still names what a reader sees.

    The returned count is the number of separators ``str.splitlines`` breaks on but
    ``HTMLParser`` does not; it belongs in the manifest as evidence, not as a reason
    to rewrite the source.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    # The restamp is confined to a leading declaration's own ``<?xml ...?>`` span.
    # Substituting over the whole text would hit the first declaration-shaped substring
    # anywhere in the body — quoted filing content — and silently edit it before the
    # digest is computed.
    if normalized.startswith("<?xml"):
        end = normalized.find("?>")
        if end != -1:
            head = XML_DECLARATION_RE.sub(r"\1utf-8\3", normalized[: end + 2], count=1)
            normalized = head + normalized[end + 2 :]
    exotic = sum(normalized.count(character) for character in EXOTIC_SEPARATORS)
    return normalized, exotic


def archive_document(
    document: DocumentArchive,
    report: AnnualReport,
    issuer: CorpCode,
    *,
    fiscal_year: int,
    fetched_at: datetime | None = None,
    document_reference: DocumentReference | None = None,
) -> AcquiredFiling:
    """Validate the original archive and stage canonical UTF-8 bytes with acquisition lineage."""
    if document.rcept_no != report.rcept_no or issuer.corp_code != report.corp_code:
        raise DartArchiveError("archive and selected report identities disagree")
    if hashlib.sha256(document.zip_bytes).hexdigest() != document.archive_sha256:
        raise DartArchiveError("archive bytes disagree with their recorded digest")
    try:
        with zipfile.ZipFile(io.BytesIO(document.zip_bytes)) as bundle:
            member = select_primary_member(bundle, rcept_no=document.rcept_no)
            raw = bundle.read(member)
    except zipfile.BadZipFile:
        raise DartArchiveError("document archive is not a readable ZIP") from None
    decoded, encoding = decode_source(raw)
    source, exotic = canonicalize(decoded)
    payload = source.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    metadata = document_reference or DocumentReference(
        document_id=f"dart-{document.rcept_no}",
        registry="dart",
        language="ko",
        issuer=issuer.stock_code,
        issuer_id=issuer.corp_code,
        aliases=(issuer.corp_name, issuer.stock_code),
        filing_id=document.rcept_no,
        form=ANNUAL_REPORT_FORM,
        fiscal_year=fiscal_year,
        filing_date=date.fromisoformat(report.rcept_dt),
        report_period=date(fiscal_year, 12, 31),
        source_url=f"{DART_VIEWER}{document.rcept_no}",
        dart=DartMetadata(
            corp_code=issuer.corp_code,
            receipt_number=document.rcept_no,
            report_code="11011",
            report_name=report.report_nm,
        ),
    )
    if metadata.registry != "dart" or metadata.filing_id != document.rcept_no:
        raise ValueError("archive identity disagrees with selected DART filing")
    moment = fetched_at or datetime.now(UTC)
    archive = SourceArtifact(
        artifact_id=f"{metadata.document_id}:archive:{document.archive_sha256}",
        document_id=metadata.document_id,
        role="archive",
        path=fixed_path("dart", metadata.issuer, document.rcept_no, "archive"),
        sha256=document.archive_sha256,
        byte_length=len(document.zip_bytes),
        encoding=None,
        acquisition=Acquisition(
            acquired_at=moment,
            url=f"{DART_BASE}/document.xml?rcept_no={document.rcept_no}",
            media_type="application/zip",
        ),
    )
    primary = SourceArtifact(
        artifact_id=f"{metadata.document_id}:primary:{digest}",
        document_id=metadata.document_id,
        role="primary",
        path=fixed_path("dart", metadata.issuer, document.rcept_no, "primary"),
        sha256=digest,
        byte_length=len(payload),
        encoding="utf-8",
        acquisition=Acquisition(
            acquired_at=moment,
            url=f"{DART_BASE}/document.xml?rcept_no={document.rcept_no}",
            media_type="application/xml",
            archive_sha256=document.archive_sha256,
            archive_member=member,
            original_encoding=encoding,
            normalized_separator_count=exotic,
        ),
    )
    return AcquiredFiling(metadata, (archive, primary), (document.zip_bytes, payload))
