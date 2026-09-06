"""Fetch and archive Open DART filings as UTF-8 sources the parser can cite.

Network access, archive selection, and decoding live together because they form one
boundary: getting a registry's original document onto disk in the exact form
the selected artifact will later decode and ``source_digest`` will later hash. The parser
starts from that file and never reaches back through this module.

The credential is always supplied by the caller and always travels as a query
parameter, never as part of a URL this module builds. Every transport failure is
re-raised outside the ``except`` block with ``from None`` because ``httpx`` exceptions
carry the request URL — and therefore the key — in their message and in the implicit
exception context.
"""

from __future__ import annotations

import asyncio
import codecs
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any, Final
import xml.etree.ElementTree as ElementTree
import zipfile

import httpx

from app.ingestion.acquisition import (
    AcquiredFiling,
    current_primary,
    merge_acquired,
    publish_bytes,
    read_catalog,
    selection_identity,
)
from app.ingestion.manifest import (
    Acquisition,
    DartMetadata,
    DocumentReference,
    Manifest,
    SourceArtifact,
)
from app.ingestion.progress import ByteProgress, OperationProgress, OperationProgressCallback

DART_BASE: Final[str] = "https://opendart.fss.or.kr/api"
DART_VIEWER: Final[str] = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
DEFAULT_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(
    connect=10.0, read=180.0, write=30.0, pool=10.0
)
# One 사업보고서 measures about 6 MB; the ceiling only stops a runaway response.
MAX_ARCHIVE_BYTES: Final[int] = 64 * 1024 * 1024
ZIP_MAGIC: Final[bytes] = b"PK\x03\x04"
# The endpoint drops connections intermittently; a bounded retry keeps a correct
# corpus build from failing on transport alone.
TRANSPORT_ATTEMPTS: Final[int] = 3
RETRY_BACKOFF_SECONDS: Final[float] = 1.0
OK_STATUS: Final[str] = "000"
NO_DATA_STATUS: Final[str] = "013"

DEFAULT_MANIFEST_NAME: Final[str] = "manifest.json"

ByteProgressFactory = Callable[[str], AbstractContextManager[ByteProgress | None]]

ANNUAL_REPORT_FORM: Final[str] = "사업보고서"
# ``pblntf_detail_ty=A001`` is accepted but not applied: the observed response also
# carries 반기보고서 and 분기보고서 rows. The period in ``report_nm`` is what actually
# identifies the annual report, so the selection below filters on it.
REPORT_PERIOD_TEMPLATE: Final[str] = "({year}.12)"

RCEPT_NO_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]{14}$")
CORP_CODE_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]{8}$")
XML_DECLARATION_RE: Final[re.Pattern[str]] = re.compile(
    r"(<\?xml[^>]*?encoding\s*=\s*[\"'])([^\"']+)([\"'])", re.I
)
# Normalized codec names (``codecs.lookup(...).name``) a declaration is trusted to
# claim — the UTF-8 and EUC-KR/CP949 families DART actually serves. A permissive
# single-byte codec such as ISO-8859-1 decodes any byte sequence without error, so
# honoring an arbitrary declared name would turn EUC-KR bytes into mojibake that
# passes the strict check and gets digest-blessed as canonical.
DECLARED_ENCODINGS: Final[frozenset[str]] = frozenset({"utf-8", "utf-8-sig", "cp949", "euc_kr"})
# Separators ``str.splitlines`` breaks on but ``HTMLParser`` does not. They are counted
# rather than removed: the count belongs in the manifest as evidence that source
# offsets and line numbers still agree.
EXOTIC_SEPARATORS: Final[str] = "\x0b\x0c\x1c\x1d\x1e\x85  "


class DartApiError(RuntimeError):
    """One Open DART request failed or answered with something other than a document.

    The message names the endpoint by its constant, never by URL, so the credential
    cannot reach a log, a traceback, or a persisted run report through this exception.
    """

    def __init__(
        self,
        endpoint: str,
        reason: str,
        *,
        status: int | None = None,
        dart_status: str | None = None,
    ) -> None:
        detail = f"{endpoint}: {reason}"
        if status is not None:
            detail = f"{detail} (http {status})"
        if dart_status is not None:
            detail = f"{detail} (dart status {dart_status})"
        super().__init__(detail)
        self.endpoint = endpoint
        self.reason = reason
        self.status = status
        self.dart_status = dart_status


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


@dataclass(frozen=True, slots=True)
class DartAcquisitionResult:
    """Observable manifest and source-file outcome from one DART run."""

    archived: tuple[AcquiredFiling, ...]
    added: tuple[DocumentReference, ...]
    manifest_entries: int
    manifest: str = "manifest.json"
    selection_id: str = ""


def _declared_length(response: httpx.Response) -> int | None:
    """Return the length of the body the caller will count, when it is knowable.

    ``Content-Length`` describes the *encoded* body. A compressed response is handed
    back decoded, so the header does not describe what is being counted and there is
    no total: an open-ended byte counter is honest where a percentage would run past
    100%. Counting raw bytes instead would mean trusting a client-side counter that
    quietly stays at zero on transports that do not stream.
    """
    encoding = response.headers.get("content-encoding", "").strip().lower()
    if encoding not in ("", "identity"):
        return None
    raw = response.headers.get("content-length")
    if raw is None:
        return None
    try:
        length = int(raw)
    except ValueError:
        return None
    return length if length > 0 else None


async def _read_body(
    client: httpx.AsyncClient,
    endpoint: str,
    *,
    api_key: str,
    on_progress: ByteProgress | None,
    params: Mapping[str, str],
) -> bytes:
    """Stream one response, applying the status and size checks as the body arrives."""
    async with client.stream(
        "GET",
        f"{DART_BASE}/{endpoint}",
        params={"crtfc_key": api_key, **params},
        timeout=DEFAULT_TIMEOUT,
    ) as response:
        if response.status_code != 200:
            raise DartApiError(endpoint, "unexpected http status", status=response.status_code)
        total = _declared_length(response)
        if on_progress is not None:
            on_progress(0, total)
        chunks: list[bytes] = []
        held = 0
        async for chunk in response.aiter_bytes():
            held += len(chunk)
            if held > MAX_ARCHIVE_BYTES:
                raise DartApiError(endpoint, f"response exceeds {MAX_ARCHIVE_BYTES} bytes")
            chunks.append(chunk)
            if on_progress is not None:
                on_progress(held, total)
    return b"".join(chunks)


async def _get(
    client: httpx.AsyncClient,
    endpoint: str,
    *,
    api_key: str,
    on_progress: ByteProgress | None = None,
    **params: str,
) -> bytes:
    """Issue one request, keeping the credential out of every failure path.

    The body is streamed rather than buffered whole by ``httpx`` so a caller can
    watch it arrive: ``corpCode.xml`` is tens of megabytes from a slow endpoint, and
    a command that prints nothing for a minute is indistinguishable from a hung one.
    Streaming also moves the size ceiling ahead of the allocation it guards.

    A transport failure is retried because this endpoint drops connections often
    enough to fail a corpus build that is otherwise correct — roughly one request in
    four when observed. Only transport errors are retried: an HTTP status or a DART
    status is an answer, and repeating the request would not change it.

    Raises
    ------
    DartApiError
        If every attempt fails on transport, the status is not 200, or the body is
        larger than the archive ceiling.
    """
    failure = ""
    for attempt in range(TRANSPORT_ATTEMPTS):
        try:
            return await _read_body(
                client, endpoint, api_key=api_key, on_progress=on_progress, params=params
            )
        except httpx.RequestError as exc:
            # Only the class name is safe to keep: the message and __cause__ of an
            # httpx error carry the request URL, and the URL carries crtfc_key.
            failure = type(exc).__name__
            if attempt + 1 < TRANSPORT_ATTEMPTS:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise DartApiError(
        endpoint, f"request failed after {TRANSPORT_ATTEMPTS} attempts ({failure})"
    ) from None


def _require_zip(endpoint: str, body: bytes) -> bytes:
    """Return ZIP bytes, or raise with the DART status the error body carries.

    Open DART answers a bad key or an unknown receipt number with **HTTP 200 and a
    JSON or XML error body** on the endpoints documented to return a ZIP, so the
    magic number is the only trustworthy discriminator.
    """
    if body[:4] == ZIP_MAGIC:
        return body
    status, message = _error_payload(body)
    raise DartApiError(endpoint, message or "response is not a ZIP archive", dart_status=status)


def _error_payload(body: bytes) -> tuple[str | None, str | None]:
    """Return the status and message of a DART error body, when it carries them."""
    text = body[:2000].decode("utf-8", errors="replace").strip()
    if text.startswith("{"):
        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None, None
        if isinstance(payload, Mapping):
            return _text_or_none(payload.get("status")), _text_or_none(payload.get("message"))
        return None, None
    if "<result>" in text:
        status = re.search(r"<status>([^<]*)</status>", text)
        message = re.search(r"<message>([^<]*)</message>", text)
        return (
            status.group(1) if status else None,
            message.group(1) if message else None,
        )
    return None, None


def _text_or_none(value: object) -> str | None:
    """Return a nonblank string value, or ``None``."""
    return value.strip() if isinstance(value, str) and value.strip() else None


async def fetch_corp_code_archive(
    client: httpx.AsyncClient, *, api_key: str, on_progress: ByteProgress | None = None
) -> bytes:
    """Download the ZIP holding every registered issuer's ``corp_code``."""
    body = await _get(client, "corpCode.xml", api_key=api_key, on_progress=on_progress)
    return _require_zip("corpCode.xml", body)


def parse_corp_codes(archive: bytes, *, stock_codes: Collection[str]) -> dict[str, CorpCode]:
    """Map each requested stock code to its Open DART issuer identity.

    Parameters
    ----------
    archive : bytes
        ZIP served by ``corpCode.xml``, holding one ``CORPCODE.xml`` member.
    stock_codes : Collection[str]
        Six-digit stock codes the caller needs. Every one must be present.

    Returns
    -------
    dict[str, CorpCode]
        One entry per requested stock code.

    Raises
    ------
    DartArchiveError
        If the ZIP is unreadable or carries no XML member.
    DartApiError
        If any requested stock code is absent, which means the corpus cannot be
        assembled as specified rather than that it should be assembled differently.
    """
    wanted = {code.strip() for code in stock_codes}
    if not wanted:
        raise ValueError("stock_codes must not be empty")

    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = [info for info in bundle.infolist() if info.filename.lower().endswith(".xml")]
            if not members:
                raise DartArchiveError("corpCode archive holds no XML member")
            payload = bundle.read(members[0]).decode("utf-8")
    except (zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise DartArchiveError(f"corpCode archive is unreadable: {type(exc).__name__}") from None

    found: dict[str, CorpCode] = {}
    for element in ElementTree.fromstring(payload).iter("list"):
        stock = (element.findtext("stock_code") or "").strip()
        if stock in wanted and stock not in found:
            found[stock] = CorpCode(
                corp_code=(element.findtext("corp_code") or "").strip(),
                corp_name=(element.findtext("corp_name") or "").strip(),
                stock_code=stock,
            )
    missing = sorted(wanted - set(found))
    if missing:
        raise DartApiError("corpCode.xml", f"stock codes not registered: {', '.join(missing)}")
    return found


async def fetch_annual_report_rows(
    client: httpx.AsyncClient, *, api_key: str, corp_code: str, filing_year: int
) -> tuple[dict[str, Any], ...]:
    """Return the periodic-disclosure rows one issuer filed in ``filing_year``.

    Raises
    ------
    DartApiError
        If the endpoint reports any status other than success, including the
        typed no-data status, which is a missing corpus rather than an empty list.
    """
    if CORP_CODE_RE.fullmatch(corp_code) is None:
        raise ValueError("corp_code must be eight digits")
    body = await _get(
        client,
        "list.json",
        api_key=api_key,
        corp_code=corp_code,
        bgn_de=f"{filing_year}0101",
        end_de=f"{filing_year}1231",
        last_reprt_at="Y",
        pblntf_ty="A",
        pblntf_detail_ty="A001",
        sort="date",
        sort_mth="desc",
        page_count="100",
    )
    try:
        payload = json.loads(body)
    except ValueError:
        raise DartApiError("list.json", "response is not JSON") from None
    if not isinstance(payload, Mapping):
        raise DartApiError("list.json", "response is not a JSON object")
    status = _text_or_none(payload.get("status"))
    if status != OK_STATUS:
        reason = _text_or_none(payload.get("message")) or "search failed"
        if status == NO_DATA_STATUS:
            reason = f"no periodic disclosure for corp_code={corp_code} in {filing_year}"
        raise DartApiError("list.json", reason, dart_status=status)
    rows = payload.get("list")
    if not isinstance(rows, list):
        raise DartApiError("list.json", "response carries no result list")
    return tuple(row for row in rows if isinstance(row, dict))


def select_annual_report(
    rows: Collection[Mapping[str, Any]], *, corp_code: str, fiscal_year: int
) -> AnnualReport:
    """Select the one 사업보고서 covering ``fiscal_year`` and refuse every other count.

    Parameters
    ----------
    rows : Collection[Mapping[str, Any]]
        Disclosure rows as ``list.json`` returned them.
    corp_code : str
        Issuer whose rows these are, used only in failure messages.
    fiscal_year : int
        Year the report must cover, matched against the period in ``report_nm``.

    Returns
    -------
    AnnualReport
        The single matching row.

    Raises
    ------
    DartApiError
        If no row or more than one row matches. An amended filing legitimately
        produces a second row, and picking the later one silently would move the
        corpus under golden spans that cite the first.

    Notes
    -----
    The period in ``report_nm`` decides the fiscal year, never ``rcept_dt``: an
    FY2024 annual report is filed in 2025.
    """
    period = REPORT_PERIOD_TEMPLATE.format(year=fiscal_year)
    matched = [
        row
        for row in rows
        if ANNUAL_REPORT_FORM in str(row.get("report_nm", ""))
        and period in str(row.get("report_nm", ""))
    ]
    if not matched:
        raise DartApiError(
            "list.json", f"no {ANNUAL_REPORT_FORM} {period} for corp_code={corp_code}"
        )
    if len(matched) > 1:
        candidates = "; ".join(
            f"{row.get('rcept_no')} {row.get('rcept_dt')} {row.get('report_nm')}" for row in matched
        )
        raise DartApiError(
            "list.json",
            f"{len(matched)} candidate reports for corp_code={corp_code}: {candidates}",
        )
    row = matched[0]
    rcept_no = str(row.get("rcept_no", "")).strip()
    if RCEPT_NO_RE.fullmatch(rcept_no) is None:
        raise DartApiError("list.json", f"malformed receipt number: {rcept_no!r}")
    return AnnualReport(
        rcept_no=rcept_no,
        corp_code=corp_code,
        corp_name=str(row.get("corp_name", "")).strip(),
        report_nm=str(row.get("report_nm", "")).strip(),
        rcept_dt=str(row.get("rcept_dt", "")).strip(),
    )


async def fetch_document_archive(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    rcept_no: str,
    on_progress: ByteProgress | None = None,
) -> DocumentArchive:
    """Download one disclosure's original archive and hash exactly what was served.

    The returned digest proves the upstream bytes, which is a different claim from
    the source digest the parser cites; neither is derivable from the other.
    """
    if RCEPT_NO_RE.fullmatch(rcept_no) is None:
        raise ValueError("rcept_no must be fourteen digits")
    served = await _get(
        client, "document.xml", api_key=api_key, rcept_no=rcept_no, on_progress=on_progress
    )
    body = _require_zip("document.xml", served)
    return DocumentArchive(
        rcept_no=rcept_no,
        zip_bytes=body,
        archive_sha256=hashlib.sha256(body).hexdigest(),
    )


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
    corpus_dir: Path,
    fetched_at: datetime | None = None,
    document_reference: DocumentReference | None = None,
) -> AcquiredFiling:
    """Publish original archive and canonical UTF-8 source with complete acquisition lineage."""
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
        path=f"dart/{document.rcept_no}/{document.archive_sha256}.zip",
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
        path=f"dart/{document.rcept_no}/{digest}.xml",
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
    publish_bytes(corpus_dir, archive.path, document.zip_bytes)
    publish_bytes(corpus_dir, primary.path, payload)
    return AcquiredFiling(metadata, (archive, primary))


def read_manifest(path: Path) -> Manifest:
    """Read only the common corpus manifest."""
    return read_catalog(path)


def write_manifest(path: Path, manifest: Manifest) -> None:
    """Atomically publish the validated common corpus manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest.write(path)


def pending_dart_targets(
    existing: Manifest,
    *,
    stock_codes: Sequence[str],
    fiscal_years: Sequence[int],
    corpus_dir: Path,
) -> list[tuple[str, int]]:
    """Find requested issuer-years lacking a verified acquired primary source."""
    valid = {
        (document.issuer, document.fiscal_year)
        for document in existing.documents
        if document.registry == "dart"
        and current_primary(existing, document.document_id, corpus_dir) is not None
    }
    return [
        (stock_code, fiscal_year)
        for stock_code in dict.fromkeys(stock_codes)
        for fiscal_year in dict.fromkeys(fiscal_years)
        if (stock_code, fiscal_year) not in valid
    ]


def _known_issuers(manifest: Manifest, stock_codes: Sequence[str]) -> dict[str, CorpCode]:
    """Reuse only unanimous typed issuer IDs; a stock code is not an official-name claim."""
    wanted = set(stock_codes)
    candidates: dict[str, set[str | None]] = {}
    for document in manifest.documents:
        if document.registry != "dart" or document.issuer not in wanted:
            continue
        code = (
            document.dart.corp_code
            if document.dart is not None and document.issuer_id == document.dart.corp_code
            else None
        )
        candidates.setdefault(document.issuer, set()).add(code)
    known: dict[str, CorpCode] = {}
    for stock_code, codes in candidates.items():
        if len(codes) == 1 and (code := next(iter(codes))) is not None:
            # The live annual-report row supplies its current source-provided name.
            known[stock_code] = CorpCode(code, stock_code, stock_code)
    return known


async def acquire_dart(
    *,
    stock_codes: Sequence[str],
    fiscal_years: Sequence[int],
    corpus_dir: Path,
    api_key: str,
    on_progress: OperationProgressCallback | None = None,
    progress_factory: ByteProgressFactory | None = None,
) -> DartAcquisitionResult:
    """Download and archive requested DART filings without parsing or ingesting them."""
    manifest_path = corpus_dir / DEFAULT_MANIFEST_NAME
    existing = read_manifest(manifest_path)
    if not stock_codes or not fiscal_years:
        raise ValueError("DART acquisition requires explicit issuers and fiscal years")
    selection_id = selection_identity("dart", stock_codes, fiscal_years)
    targets = pending_dart_targets(
        existing,
        stock_codes=stock_codes,
        fiscal_years=fiscal_years,
        corpus_dir=corpus_dir,
    )
    if not targets:
        if on_progress is not None:
            on_progress(OperationProgress("download", 0, 0, "Every requested filing is valid"))
        selected = [
            document.document_id
            for document in existing.documents
            if document.registry == "dart"
            and document.issuer in stock_codes
            and document.fiscal_year in fiscal_years
        ]
        existing = merge_acquired(
            existing,
            [],
            selection_id=selection_id,
            selected_document_ids=selected,
            corpus_root=corpus_dir,
        )
        write_manifest(manifest_path, existing)
        return DartAcquisitionResult((), (), len(existing.documents), selection_id=selection_id)
    if not api_key.strip():
        raise ValueError("DART_API_KEY is not configured; add it to .env")
    archived: list[AcquiredFiling] = []
    prior_ids = {document.document_id for document in existing.documents}

    def byte_progress(
        label: str,
        *,
        stage: str,
        current: int,
        total: int | None,
    ) -> AbstractContextManager[ByteProgress | None]:
        """Bridge one byte stream onto terminal or administrative progress."""
        if progress_factory is not None:
            return progress_factory(label)
        publish = on_progress
        if publish is None:
            return nullcontext(None)

        @contextmanager
        def bridge() -> Iterator[ByteProgress]:
            """Yield a byte callback that publishes administrative progress."""

            def report(read: int, length: int | None) -> None:
                """Publish byte progress for the current DART response."""
                publish(
                    OperationProgress(
                        stage,
                        current,
                        total,
                        label,
                        read,
                        length,
                    )
                )

            yield report

        return bridge()

    pending_stock_codes = tuple(dict.fromkeys(stock_code for stock_code, _ in targets))
    issuers = _known_issuers(existing, pending_stock_codes)
    unknown = tuple(stock_code for stock_code in pending_stock_codes if stock_code not in issuers)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        if unknown:
            with byte_progress(
                "corp codes",
                stage="issuer_index",
                current=0,
                total=None,
            ) as progress:
                bundle = await fetch_corp_code_archive(
                    client, api_key=api_key, on_progress=progress
                )
            issuers.update(parse_corp_codes(bundle, stock_codes=unknown))

        for index, (stock_code, fiscal_year) in enumerate(targets):
            issuer = issuers[stock_code]
            label = f"{issuer.corp_name} FY{fiscal_year}"
            if on_progress is not None:
                on_progress(OperationProgress("select", index, len(targets), label))
            rows = await fetch_annual_report_rows(
                client,
                api_key=api_key,
                corp_code=issuer.corp_code,
                filing_year=fiscal_year + 1,
            )
            report = select_annual_report(rows, corp_code=issuer.corp_code, fiscal_year=fiscal_year)
            if report.corp_name:
                issuer = CorpCode(issuer.corp_code, report.corp_name, stock_code)
                label = f"{issuer.corp_name} FY{fiscal_year}"
            with byte_progress(
                label,
                stage="download",
                current=index,
                total=len(targets),
            ) as progress:
                document = await fetch_document_archive(
                    client,
                    api_key=api_key,
                    rcept_no=report.rcept_no,
                    on_progress=progress,
                )
            entry = archive_document(
                document,
                report,
                issuer,
                fiscal_year=fiscal_year,
                corpus_dir=corpus_dir,
                document_reference=next(
                    (
                        known
                        for known in existing.documents
                        if known.registry == "dart" and known.filing_id == document.rcept_no
                    ),
                    None,
                ),
            )
            archived.append(entry)
            selected = [
                known.document_id
                for known in (*existing.documents, entry.document)
                if known.registry == "dart"
                and known.issuer in stock_codes
                and known.fiscal_year in fiscal_years
            ]
            existing = merge_acquired(
                existing,
                [entry],
                selection_id=selection_id,
                selected_document_ids=selected,
                corpus_root=corpus_dir,
            )
            write_manifest(manifest_path, existing)
            if on_progress is not None:
                on_progress(OperationProgress("download", index + 1, len(targets), label))

    added = tuple(
        entry.document for entry in archived if entry.document.document_id not in prior_ids
    )
    return DartAcquisitionResult(
        tuple(archived), added, len(existing.documents), selection_id=selection_id
    )


if __name__ == "__main__":  # pragma: no cover - corpus acquisition helper
    import argparse
    import asyncio

    from app.config import get_settings
    from app.ingestion.progress import byte_bar, overall_bar

    DEFAULT_STOCK_CODES = ("005930", "000660")
    DEFAULT_FISCAL_YEARS = (2024,)

    async def _download(
        stock_codes: tuple[str, ...], fiscal_years: tuple[int, ...], corpus_dir: Path
    ) -> None:
        """Archive every requested issuer-year and merge the result into the manifest."""
        secret = get_settings().dart_api_key
        api_key = "" if secret is None else secret.get_secret_value()

        try:
            result = await acquire_dart(
                stock_codes=stock_codes,
                fiscal_years=fiscal_years,
                corpus_dir=corpus_dir,
                api_key=api_key,
                progress_factory=byte_bar,
            )
        except ValueError as error:
            raise SystemExit(str(error)) from None
        manifest_path = corpus_dir / DEFAULT_MANIFEST_NAME
        if not result.archived:
            print(
                f"nothing to fetch; every requested entry of {manifest_path} "
                "matches its source file"
            )
            return
        with overall_bar(len(result.archived), unit="filing", description="DART") as overall:
            for entry in result.archived:
                label = f"{entry.document.issuer} FY{entry.document.fiscal_year}"
                overall.advance(label)
                overall.write(
                    f"{label}: {entry.primary.path} ({entry.primary.byte_length:,} bytes)"
                )
        print(
            f"wrote {manifest_path}: {len(result.added)} new, "
            f"{result.manifest_entries} filing(s) recorded"
        )

    ap = argparse.ArgumentParser(description="Download and archive DART annual reports.")
    ap.add_argument("--stock-codes", nargs="+", default=list(DEFAULT_STOCK_CODES))
    ap.add_argument(
        "--fiscal-year",
        nargs="+",
        type=int,
        default=list(DEFAULT_FISCAL_YEARS),
        help="fiscal years to archive; the API is queried once per issuer and year",
    )
    ap.add_argument("--corpus-dir", type=Path, default=None)
    args = ap.parse_args()

    target = args.corpus_dir or get_settings().corpus_dir
    asyncio.run(_download(tuple(args.stock_codes), tuple(args.fiscal_year), target))
