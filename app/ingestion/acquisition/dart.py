"""Fetch and archive Open DART filings as UTF-8 sources the parser can cite.

Network selection and bounded transport produce original archives. The archive
module decodes and records the source bytes that downstream parsing can cite.

The credential is always supplied by the caller and always travels as a query
parameter, never as part of a URL this module builds. Every transport failure is
re-raised outside the ``except`` block with ``from None`` because ``httpx`` exceptions
carry the request URL — and therefore the key — in their message and in the implicit
exception context.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any, Final
import xml.etree.ElementTree as ElementTree
import zipfile

import httpx

from app.ingestion.acquisition.dart_archive import (
    ANNUAL_REPORT_FORM,
    DART_BASE,
    AnnualReport,
    CorpCode,
    DartArchiveError,
    DocumentArchive,
    archive_document,
)
from app.ingestion.acquisition.http import AcquisitionHttpError, fetch_bytes
from app.ingestion.progress import (
    ByteProgress,
    OperationProgress,
    OperationProgressCallback,
    byte_progress as stream_progress,
)
from app.ingestion.sources.catalog import read_catalog
from app.ingestion.sources.models import (
    AcquiredFiling,
    DocumentReference,
    Manifest,
)
from app.ingestion.sources.publication import publish_acquired
from app.ingestion.sources.selection import (
    SourceDownloadRequiredError,
    resolve_primary,
    selection_identity,
)

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

# ``pblntf_detail_ty=A001`` is accepted but not applied: the observed response also
# carries 반기보고서 and 분기보고서 rows. The period in ``report_nm`` is what actually
# identifies the annual report, so the selection below filters on it.
REPORT_PERIOD_TEMPLATE: Final[str] = "({year}.12)"

RCEPT_NO_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]{14}$")
CORP_CODE_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]{8}$")


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


@dataclass(frozen=True, slots=True)
class DartAcquisitionResult:
    """Observable manifest and source-file outcome from one DART run."""

    archived: tuple[AcquiredFiling, ...]
    added: tuple[DocumentReference, ...]
    manifest_entries: int
    manifest: str = "manifest.json"
    selection_id: str = ""


async def _get(
    client: httpx.AsyncClient,
    endpoint: str,
    *,
    api_key: str,
    on_progress: ByteProgress | None = None,
    **params: str,
) -> bytes:
    """Fetch one bounded response without leaking the query credential in errors."""
    failure = None
    try:
        return await fetch_bytes(
            client,
            f"{DART_BASE}/{endpoint}",
            timeout=DEFAULT_TIMEOUT,
            max_bytes=MAX_ARCHIVE_BYTES,
            attempts=TRANSPORT_ATTEMPTS,
            backoff_seconds=RETRY_BACKOFF_SECONDS,
            params={"crtfc_key": api_key, **params},
            on_progress=on_progress,
        )
    except AcquisitionHttpError as error:
        failure = DartApiError(endpoint, str(error), status=error.status)
    raise failure from None


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


def _dart_source_ready(manifest: Manifest, document_id: str, root: Path) -> bool:
    """Permit exact-receipt recovery only for an unambiguous incomplete source bundle."""
    try:
        resolve_primary(manifest, document_id, root)
    except SourceDownloadRequiredError:
        return False
    return True


def pending_dart_targets(
    existing: Manifest,
    *,
    stock_codes: Sequence[str],
    fiscal_years: Sequence[int],
    corpus_dir: Path,
) -> list[tuple[str, int]]:
    """Find requested issuer-years lacking a verified primary and registered archive."""
    readiness: dict[tuple[str, int], bool] = {}
    for document in existing.documents:
        if (
            document.registry == "dart"
            and document.issuer in stock_codes
            and document.fiscal_year in fiscal_years
        ):
            key = (document.issuer, document.fiscal_year)
            ready = _dart_source_ready(existing, document.document_id, corpus_dir)
            readiness[key] = readiness.get(key, True) and ready
    return [
        (stock_code, fiscal_year)
        for stock_code in dict.fromkeys(stock_codes)
        for fiscal_year in dict.fromkeys(fiscal_years)
        if not readiness.get((stock_code, fiscal_year), False)
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
) -> DartAcquisitionResult:
    """Download and archive requested DART filings without parsing or ingesting them."""
    manifest_path = corpus_dir / DEFAULT_MANIFEST_NAME
    existing = read_catalog(manifest_path)
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
        existing = publish_acquired(
            manifest_path,
            [],
            selection_id=selection_id,
            selected_document_ids=selected,
        )
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
        """Bridge one byte stream onto administrative progress."""
        return nullcontext(
            stream_progress(on_progress, OperationProgress(stage, current, total, label))
        )

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

        work: list[tuple[str, int, DocumentReference | None]] = []
        for stock_code, fiscal_year in targets:
            missing = [
                known
                for known in existing.documents
                if known.registry == "dart"
                and known.issuer == stock_code
                and known.fiscal_year == fiscal_year
                and not _dart_source_ready(existing, known.document_id, corpus_dir)
            ]
            work.extend((stock_code, fiscal_year, known) for known in missing or [None])
        for index, (stock_code, fiscal_year, known_target) in enumerate(work):
            issuer = issuers[stock_code]
            label = f"{issuer.corp_name} ({stock_code}) FY{fiscal_year}"
            if on_progress is not None:
                on_progress(OperationProgress("select", index, len(work), label))
            if known_target is not None:
                assert known_target.dart is not None
                report = AnnualReport(
                    known_target.filing_id,
                    issuer.corp_code,
                    issuer.corp_name,
                    known_target.dart.report_name,
                    known_target.filing_date.isoformat(),
                )
            else:
                rows = await fetch_annual_report_rows(
                    client,
                    api_key=api_key,
                    corp_code=issuer.corp_code,
                    filing_year=fiscal_year + 1,
                )
                report = select_annual_report(
                    rows, corp_code=issuer.corp_code, fiscal_year=fiscal_year
                )
            if report.corp_name:
                issuer = CorpCode(issuer.corp_code, report.corp_name, stock_code)
                label = f"{issuer.corp_name} ({stock_code}) FY{fiscal_year}"
            with byte_progress(
                label,
                stage="download",
                current=index,
                total=len(work),
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
            existing = publish_acquired(
                manifest_path,
                [entry],
                selection_id=selection_id,
                selected_document_ids=selected,
            )
            if on_progress is not None:
                on_progress(OperationProgress("download", index + 1, len(work), label))

    added = tuple(
        entry.document for entry in archived if entry.document.document_id not in prior_ids
    )
    return DartAcquisitionResult(
        tuple(archived), added, len(existing.documents), selection_id=selection_id
    )
