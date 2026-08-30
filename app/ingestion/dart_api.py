"""Fetch and archive Open DART filings as UTF-8 sources the parser can cite.

Network access, archive selection, and decoding live together because they form one
boundary: getting a registry's original document onto disk in the exact form
``read_source`` will later decode and ``source_digest`` will later hash. The parser
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
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any, Final
import xml.etree.ElementTree as ElementTree
import zipfile

import httpx

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


async def _get(
    client: httpx.AsyncClient, endpoint: str, *, api_key: str, **params: str
) -> httpx.Response:
    """Issue one request, keeping the credential out of every failure path.

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
    response: httpx.Response | None = None
    for attempt in range(TRANSPORT_ATTEMPTS):
        try:
            response = await client.get(
                f"{DART_BASE}/{endpoint}",
                params={"crtfc_key": api_key, **params},
                timeout=DEFAULT_TIMEOUT,
            )
            break
        except httpx.RequestError as exc:
            # Only the class name is safe to keep: the message and __cause__ of an
            # httpx error carry the request URL, and the URL carries crtfc_key.
            failure = type(exc).__name__
            if attempt + 1 < TRANSPORT_ATTEMPTS:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    if response is None:
        raise DartApiError(
            endpoint, f"request failed after {TRANSPORT_ATTEMPTS} attempts ({failure})"
        ) from None
    if response.status_code != 200:
        raise DartApiError(endpoint, "unexpected http status", status=response.status_code)
    if len(response.content) > MAX_ARCHIVE_BYTES:
        raise DartApiError(endpoint, f"response exceeds {MAX_ARCHIVE_BYTES} bytes")
    return response


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


async def fetch_corp_code_archive(client: httpx.AsyncClient, *, api_key: str) -> bytes:
    """Download the ZIP holding every registered issuer's ``corp_code``."""
    response = await _get(client, "corpCode.xml", api_key=api_key)
    return _require_zip("corpCode.xml", response.content)


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
    response = await _get(
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
        payload = response.json()
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
    client: httpx.AsyncClient, *, api_key: str, rcept_no: str
) -> DocumentArchive:
    """Download one disclosure's original archive and hash exactly what was served.

    The returned digest proves the upstream bytes, which is a different claim from
    the source digest the parser cites; neither is derivable from the other.
    """
    if RCEPT_NO_RE.fullmatch(rcept_no) is None:
        raise ValueError("rcept_no must be fourteen digits")
    response = await _get(client, "document.xml", api_key=api_key, rcept_no=rcept_no)
    body = _require_zip("document.xml", response.content)
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
) -> dict[str, Any]:
    """Write one canonical UTF-8 source and return its registry-neutral manifest entry.

    Parameters
    ----------
    document : DocumentArchive
        Archive as served, already hashed.
    report : AnnualReport
        The selected disclosure row.
    issuer : CorpCode
        Issuer identity, whose stock code becomes the neutral ``issuer`` symbol.
    fiscal_year : int
        Year the report covers.
    corpus_dir : Path
        Corpus root; the source lands under ``dart/{stock_code}/{rcept_no}.xml``.
    fetched_at : datetime | None
        Timezone-aware retrieval moment recorded in the entry.

    Returns
    -------
    dict[str, Any]
        Manifest entry whose ``source_length`` and ``source_sha256`` describe the file
        on disk, so a re-transcoded or truncated archive is caught before parsing.

    Raises
    ------
    DartArchiveError
        If the archive is unreadable, the report member is missing, or the member
        cannot be decoded without loss.

    Notes
    -----
    The digest is recomputed by reading the written file back rather than taken from
    the in-memory string. That is the only construction guaranteed to equal what the
    golden loader recomputes later through the same reader.
    """
    from app.ingestion.parser import read_source, source_digest

    try:
        with zipfile.ZipFile(io.BytesIO(document.zip_bytes)) as bundle:
            member = select_primary_member(bundle, rcept_no=document.rcept_no)
            raw = bundle.read(member)
    except zipfile.BadZipFile:
        raise DartArchiveError("document archive is not a readable ZIP") from None

    decoded, encoding = decode_source(raw)
    source, exotic = canonicalize(decoded)

    path = corpus_dir / "dart" / issuer.stock_code / f"{document.rcept_no}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source.encode("utf-8"))

    stored = read_source(path)
    moment = fetched_at or datetime.now(UTC)
    return {
        "registry": "dart",
        "issuer": issuer.stock_code,
        "issuer_id": issuer.corp_code,
        "filing_id": document.rcept_no,
        "form": ANNUAL_REPORT_FORM,
        "language": "ko",
        "filing_date": f"{report.rcept_dt[:4]}-{report.rcept_dt[4:6]}-{report.rcept_dt[6:8]}",
        "report_period": f"{fiscal_year}-12-31",
        "fiscal_year": fiscal_year,
        "file": str(path),
        "url": f"{DART_VIEWER}{document.rcept_no}",
        "source_length": len(stored),
        "source_sha256": source_digest(stored),
        "source_encoding": encoding,
        "archive_sha256": document.archive_sha256,
        "archive_member": member,
        "exotic_separators": exotic,
        "corp_name": issuer.corp_name,
        "report_nm": report.report_nm,
        "fetched_at": moment.isoformat().replace("+00:00", "Z"),
    }


if __name__ == "__main__":  # pragma: no cover - corpus acquisition helper
    import argparse
    import asyncio

    from app.config import get_settings

    DEFAULT_STOCK_CODES = ("005930", "000660")

    async def _download(stock_codes: tuple[str, ...], fiscal_year: int, corpus_dir: Path) -> None:
        """Fetch every requested issuer's annual report and write the DART manifest."""
        settings = get_settings()
        secret = settings.dart_api_key
        if secret is None:
            raise SystemExit("DART_API_KEY is not configured; add it to .env")
        api_key = secret.get_secret_value()

        entries: list[dict[str, Any]] = []
        async with httpx.AsyncClient(follow_redirects=True) as client:
            bundle = await fetch_corp_code_archive(client, api_key=api_key)
            issuers = parse_corp_codes(bundle, stock_codes=stock_codes)
            for stock_code in stock_codes:
                issuer = issuers[stock_code]
                rows = await fetch_annual_report_rows(
                    client,
                    api_key=api_key,
                    corp_code=issuer.corp_code,
                    filing_year=fiscal_year + 1,
                )
                report = select_annual_report(
                    rows, corp_code=issuer.corp_code, fiscal_year=fiscal_year
                )
                document = await fetch_document_archive(
                    client, api_key=api_key, rcept_no=report.rcept_no
                )
                entry = archive_document(
                    document,
                    report,
                    issuer,
                    fiscal_year=fiscal_year,
                    corpus_dir=corpus_dir,
                )
                entries.append(entry)
                print(
                    f"{stock_code} {issuer.corp_name}: {entry['file']} "
                    f"({entry['source_length']:,} chars)"
                )

        manifest = corpus_dir / "dart-manifest.json"
        manifest.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {manifest}")

    ap = argparse.ArgumentParser(description="Download and archive DART annual reports.")
    ap.add_argument("--stock-codes", nargs="+", default=list(DEFAULT_STOCK_CODES))
    ap.add_argument("--fiscal-year", type=int, default=2024)
    ap.add_argument("--corpus-dir", type=Path, default=None)
    args = ap.parse_args()

    target = args.corpus_dir or get_settings().corpus_dir
    asyncio.run(_download(tuple(args.stock_codes), args.fiscal_year, target))
