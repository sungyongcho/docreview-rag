"""Discover SEC filings and acquire verified artifacts into the common corpus manifest.

SEC HTTP rows become normalized document references before acquisition. Complete
source bytes are published atomically and identified by content hash; one named
selection records exactly the acquired artifacts requested by this operation.

Two things separate a stored document from a stored response. SEC requires a
declared contact in ``User-Agent`` and throttles clients that omit one, so the
address is configuration rather than a value edited into a snippet. And EDGAR
answers automation it considers undeclared with an interstitial page that can
arrive with HTTP 200 — writing that page would turn a fetch problem into a parse
failure twenty steps downstream, so the body is checked before it reaches disk.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Collection, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import httpx

from app.ingestion.acquisition import (
    AcquiredFiling,
    current_primary,
    read_catalog,
    selection_identity,
)
from app.ingestion.manifest import (
    Acquisition,
    DocumentReference,
    Manifest,
    SecMetadata,
    SourceArtifact,
)
from app.ingestion.progress import ByteProgress, OperationProgress, OperationProgressCallback
from app.ingestion.source_publication import fixed_path, publish_acquired

DEFAULT_MANIFEST: Final[Path] = Path("data/corpus/manifest.json")
CORPUS_ROOT: Final[Path] = Path("data/corpus")
TICKERS_URL: Final[str] = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL: Final[str] = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_PAGE_URL: Final[str] = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL: Final[str] = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
# Exact match only. A 10-K/A amends a year the original already covers, and the two
# would land on one doc_id.
ANNUAL_REPORT_FORM: Final[str] = "10-K"
# The columns of a submissions page. SEC serves filing history column-wise, one array
# per field, joined by position.
FILING_COLUMNS: Final[tuple[str, ...]] = (
    "form",
    "accessionNumber",
    "filingDate",
    "reportDate",
    "primaryDocument",
)

DEFAULT_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(
    connect=10.0, read=120.0, write=30.0, pool=10.0
)
# A 10-K measures a few megabytes; the ceiling only stops a runaway response.
MAX_DOCUMENT_BYTES: Final[int] = 64 * 1024 * 1024
TRANSPORT_ATTEMPTS: Final[int] = 3
RETRY_BACKOFF_SECONDS: Final[float] = 1.0
# SEC publishes a ten-requests-per-second ceiling. A corpus build is not in a hurry,
# so it waits this long between requests and stays far below the limit.
REQUEST_INTERVAL_SECONDS: Final[float] = 0.5
# The interstitial EDGAR serves to clients it considers undeclared automation. It can
# carry HTTP 200, so the status alone does not prove the body is a filing.
BLOCK_PAGE_MARKER: Final[bytes] = b"Undeclared Automated Tool"
# SEC rejects a User-Agent that names no way to reach the operator.
CONTACT_MARKER: Final[str] = "@"
PARTIAL_SUFFIX: Final[str] = ".part"

# Opens the display for one entry's download. The library calls it and passes the
# hook on; only the command knows that the hook is drawn as a bar.
ProgressFactory = Callable[[DocumentReference], AbstractContextManager[ByteProgress | None]]


@dataclass(frozen=True, slots=True)
class EdgarAcquisitionResult:
    """Observable files and manifest growth from one acquisition run."""

    manifest_entries: int
    added: tuple[DocumentReference, ...]
    fetched: tuple[tuple[Path, int], ...]
    dry_run: bool = False
    manifest: str = "manifest.json"
    selection_id: str = ""


class EdgarApiError(RuntimeError):
    """One EDGAR request failed or answered with something other than the filing.

    The URL belongs in the message here: EDGAR archive URLs are public and carry no
    credential, and the accession they name is what identifies the failed document.
    """

    def __init__(self, url: str, reason: str, *, status: int | None = None) -> None:
        detail = f"{url}: {reason}"
        if status is not None:
            detail = f"{detail} (http {status})"
        super().__init__(detail)
        self.url = url
        self.reason = reason
        self.status = status


def require_user_agent(declared: str | None) -> str:
    """Return the SEC contact string to declare, or raise when it cannot be used.

    Raises
    ------
    ValueError
        If the value is missing, blank, or names no contact address.
    """
    value = (declared or "").strip()
    if not value:
        raise ValueError("SEC_USER_AGENT is not configured; add it to .env")
    if CONTACT_MARKER not in value:
        raise ValueError(
            "SEC_USER_AGENT must carry a contact address, e.g. 'Jane Doe jane@example.com'"
        )
    return value


def parse_years(text: str) -> range:
    """Return the inclusive fiscal-year range a ``--years`` argument names.

    Accepts ``2024`` for one year and ``2015-2024`` for a span. The year is the one
    in ``report_date``, which is the field ``doc_id`` reads, so what is asked for and
    what the corpus is labelled with cannot drift apart.

    Raises
    ------
    ValueError
        If either bound is not a four-digit year, or the span runs backwards.
    """
    first, separator, last = text.partition("-")
    bounds = (first, last if separator else first)
    if not all(bound.isdigit() and len(bound) == 4 for bound in bounds):
        raise ValueError(f"--years takes YYYY or YYYY-YYYY, not {text!r}")
    start, end = int(bounds[0]), int(bounds[1])
    if start > end:
        raise ValueError(f"--years runs backwards: {text!r}")
    return range(start, end + 1)


# --- manifest ---


def merge_entries(
    existing: Sequence[DocumentReference], discovered: Sequence[DocumentReference]
) -> tuple[list[DocumentReference], list[DocumentReference]]:
    """Merge exact filing identities, preserving established document IDs and aliases."""
    merged = list(existing)
    identities = {(document.registry, document.filing_id) for document in merged}
    added: list[DocumentReference] = []
    for document in sorted(discovered, key=lambda document: document.document_id):
        identity = (document.registry, document.filing_id)
        if identity in identities:
            continue
        identities.add(identity)
        merged.append(document)
        added.append(document)
    return merged, added


def pending(
    entries: Sequence[DocumentReference],
    *,
    manifest: Manifest,
    corpus_root: Path,
    force: bool = False,
    tickers: Collection[str] = (),
) -> list[DocumentReference]:
    """Return selected filings lacking a verified acquired artifact."""
    wanted = {ticker.upper() for ticker in tickers}
    return [
        document
        for document in entries
        if document.registry == "sec"
        and (not wanted or document.issuer.upper() in wanted)
        and (force or current_primary(manifest, document.document_id, corpus_root) is None)
    ]


# --- transport ---


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
    url: str,
    *,
    user_agent: str,
    on_progress: ByteProgress | None,
) -> bytes:
    """Stream one response, applying the status and size checks as the body arrives."""
    async with client.stream(
        "GET", url, headers={"User-Agent": user_agent}, timeout=DEFAULT_TIMEOUT
    ) as response:
        if response.status_code != 200:
            raise EdgarApiError(url, "unexpected http status", status=response.status_code)
        total = _declared_length(response)
        if on_progress is not None:
            on_progress(0, total)
        chunks: list[bytes] = []
        held = 0
        async for chunk in response.aiter_bytes():
            held += len(chunk)
            if held > MAX_DOCUMENT_BYTES:
                raise EdgarApiError(url, f"response exceeds {MAX_DOCUMENT_BYTES} bytes")
            chunks.append(chunk)
            if on_progress is not None:
                on_progress(held, total)
    return b"".join(chunks)


async def _get(
    client: httpx.AsyncClient,
    url: str,
    *,
    user_agent: str,
    on_progress: ByteProgress | None = None,
) -> bytes:
    """Return one response body, retrying transport failures and nothing else.

    The body is streamed rather than buffered whole by ``httpx`` so a caller can
    watch it arrive. An HTTP status is an answer, and repeating the request would
    not change it.

    Raises
    ------
    EdgarApiError
        If every attempt fails on transport, the status is not 200, or the body is
        larger than the ceiling.
    """
    failure = ""
    for attempt in range(TRANSPORT_ATTEMPTS):
        try:
            return await _read_body(client, url, user_agent=user_agent, on_progress=on_progress)
        except httpx.RequestError as exc:
            failure = type(exc).__name__
            if attempt + 1 < TRANSPORT_ATTEMPTS:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise EdgarApiError(url, f"request failed after {TRANSPORT_ATTEMPTS} attempts ({failure})")


def _reject_interstitial(url: str, body: bytes) -> None:
    """Raise when SEC answered with its undeclared-automation page instead of content."""
    if BLOCK_PAGE_MARKER in body:
        raise EdgarApiError(url, "SEC refused the request as undeclared automation")


async def fetch_document(
    client: httpx.AsyncClient,
    url: str,
    *,
    user_agent: str,
    on_progress: ByteProgress | None = None,
) -> bytes:
    """Return one filing's bytes, or raise rather than hand back a non-filing body.

    Raises
    ------
    EdgarApiError
        If the request fails, or the body is the undeclared-automation interstitial
        or empty.
    """
    body = await _get(client, url, user_agent=user_agent, on_progress=on_progress)
    _reject_interstitial(url, body)
    if not body:
        raise EdgarApiError(url, "response body is empty")
    return body


async def fetch_json(client: httpx.AsyncClient, url: str, *, user_agent: str) -> object:
    """Return one SEC JSON document, refusing the interstitial the same way.

    The result is deliberately untyped: SEC's shapes differ per endpoint, and each
    caller narrows what it needs rather than trusting a declaration made here.

    Raises
    ------
    EdgarApiError
        If the request fails, the body is the interstitial, or it is not JSON.
    """
    body = await _get(client, url, user_agent=user_agent)
    _reject_interstitial(url, body)
    try:
        return json.loads(body)
    except ValueError:
        raise EdgarApiError(url, "response is not JSON") from None


# --- discovery ---


async def resolve_ciks(
    client: httpx.AsyncClient, tickers: Sequence[str], *, user_agent: str
) -> dict[str, int]:
    """Map each requested ticker to the CIK SEC files it under.

    Raises
    ------
    EdgarApiError
        If the listing cannot be read, or any requested ticker is not in it. A
        missing ticker is refused rather than skipped: silently building a smaller
        corpus than was asked for is the failure that goes unnoticed.
    """
    payload = await fetch_json(client, TICKERS_URL, user_agent=user_agent)
    rows = payload.values() if isinstance(payload, Mapping) else payload
    if not isinstance(rows, Collection):
        raise EdgarApiError(TICKERS_URL, "listing carries no company rows")

    listed: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("ticker", "")).upper()
        try:
            listed[symbol] = int(row["cik_str"])
        except KeyError, TypeError, ValueError:
            continue

    wanted = [ticker.upper() for ticker in tickers]
    missing = [ticker for ticker in wanted if ticker not in listed]
    if missing:
        raise EdgarApiError(TICKERS_URL, f"tickers are not listed: {', '.join(missing)}")
    return {ticker: listed[ticker] for ticker in wanted}


def submission_rows(columns: Mapping[str, Any]) -> list[dict[str, str]]:
    """Join one submissions page's parallel column arrays into filing rows.

    Raises
    ------
    ValueError
        If a column this module reads is absent or is not an array.
    """
    arrays = []
    for name in FILING_COLUMNS:
        column = columns.get(name)
        if not isinstance(column, list):
            raise ValueError(f"submissions page has no {name!r} column")
        arrays.append(column)
    # Ragged columns would silently pair a form with another filing's accession.
    length = min(len(array) for array in arrays)
    return [
        {name: str(array[index]) for name, array in zip(FILING_COLUMNS, arrays, strict=True)}
        for index in range(length)
    ]


async def fetch_filing_rows(
    client: httpx.AsyncClient, cik: int, *, user_agent: str
) -> list[dict[str, str]]:
    """Return every filing SEC lists for one issuer, recent page and archived pages.

    SEC keeps a rolling window in ``filings.recent`` and moves everything older into
    separate pages, so a corpus that reaches back more than a few years has to follow
    them.

    Raises
    ------
    EdgarApiError
        If the submissions document has no filings, or a page cannot be joined.
    """
    url = SUBMISSIONS_URL.format(cik=cik)
    payload = await fetch_json(client, url, user_agent=user_agent)
    if not isinstance(payload, Mapping):
        raise EdgarApiError(url, "submissions carry no filings")
    filings = payload.get("filings")
    if not isinstance(filings, Mapping):
        raise EdgarApiError(url, "submissions carry no filings")

    try:
        rows = submission_rows(filings.get("recent") or {})
    except ValueError as error:
        raise EdgarApiError(url, str(error)) from None

    pages = filings.get("files")
    for page in pages if isinstance(pages, list) else []:
        name = page.get("name") if isinstance(page, Mapping) else None
        if not name:
            continue
        page_url = SUBMISSIONS_PAGE_URL.format(name=name)
        await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        older = await fetch_json(client, page_url, user_agent=user_agent)
        if not isinstance(older, Mapping):
            raise EdgarApiError(page_url, "archived submissions page is not an object")
        try:
            rows.extend(submission_rows(older))
        except ValueError as error:
            raise EdgarApiError(page_url, str(error)) from None
    company_name = payload.get("name")
    if isinstance(company_name, str) and company_name.strip():
        for row in rows:
            row["companyName"] = company_name.strip()
    return rows


def manifest_entry(ticker: str, cik: int, row: Mapping[str, str]) -> DocumentReference:
    """Normalize an SEC discovery row into the common filing identity."""
    accession = row["accessionNumber"]
    company_name = row.get("companyName", "").strip()
    return DocumentReference(
        document_id=f"sec-{accession}",
        registry="sec",
        language="en",
        issuer=ticker,
        issuer_id=f"{cik:010d}",
        aliases=tuple(dict.fromkeys(value for value in (ticker, company_name) if value)),
        filing_id=accession,
        fiscal_year=int(row["reportDate"][:4]),
        form=ANNUAL_REPORT_FORM,
        filing_date=date.fromisoformat(row["filingDate"]),
        report_period=date.fromisoformat(row["reportDate"]),
        source_url=ARCHIVE_URL.format(
            cik=cik, accession=accession.replace("-", ""), document=row["primaryDocument"]
        ),
        sec=SecMetadata(
            cik=f"{cik:010d}", accession=accession, primary_document=row["primaryDocument"]
        ),
    )


def annual_reports(
    rows: Sequence[Mapping[str, str]], *, ticker: str, cik: int, years: Collection[int]
) -> list[DocumentReference]:
    """Return manifest entries for the 10-K rows whose fiscal year is in range."""
    entries = []
    for row in rows:
        if row.get("form") != ANNUAL_REPORT_FORM:
            continue
        report_date = row.get("reportDate", "")
        year = report_date[:4]
        if not year.isdigit() or int(year) not in years:
            continue
        if not row.get("primaryDocument") or not row.get("accessionNumber"):
            continue
        entries.append(manifest_entry(ticker, cik, row))
    return entries


async def discover(
    client: httpx.AsyncClient,
    *,
    tickers: Sequence[str],
    years: Collection[int],
    user_agent: str,
    on_progress: OperationProgressCallback | None = None,
) -> list[DocumentReference]:
    """Return filings while reporting the company and requested years being searched."""
    ciks = await resolve_ciks(client, tickers, user_agent=user_agent)
    entries: list[DocumentReference] = []
    for position, (ticker, cik) in enumerate(ciks.items()):
        if position:
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        label = f"{ticker} · " + ", ".join(f"FY{year}" for year in sorted(years))
        if on_progress is not None:
            on_progress(OperationProgress("discover", position, len(ciks), label))
        rows = await fetch_filing_rows(client, cik, user_agent=user_agent)
        entries.extend(annual_reports(rows, ticker=ticker, cik=cik, years=years))
        if on_progress is not None:
            on_progress(OperationProgress("discover", position + 1, len(ciks), label))
    return entries


# --- fetching ---


def _no_progress(document: DocumentReference) -> AbstractContextManager[ByteProgress | None]:
    """Provide a no-op byte progress scope."""
    return nullcontext(None)


async def download_pending(
    client: httpx.AsyncClient,
    entries: Sequence[DocumentReference],
    *,
    corpus_root: Path,
    user_agent: str,
    progress: ProgressFactory | None = None,
) -> AsyncIterator[AcquiredFiling]:
    """Download and validate complete bytes before transactional publication."""
    open_progress = progress or _no_progress
    for index, document in enumerate(entries):
        if index:
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        with open_progress(document) as on_progress:
            body = await fetch_document(
                client, document.source_url, user_agent=user_agent, on_progress=on_progress
            )
        body.decode("utf-8", errors="strict")
        digest = hashlib.sha256(body).hexdigest()
        path = fixed_path("sec", document.issuer, document.filing_id, "primary")
        artifact = SourceArtifact(
            artifact_id=f"{document.document_id}:primary:{digest}",
            document_id=document.document_id,
            role="primary",
            path=path,
            sha256=digest,
            byte_length=len(body),
            encoding="utf-8",
            acquisition=Acquisition(
                acquired_at=datetime.now(UTC),
                url=document.source_url,
                media_type="text/html",
                original_encoding="utf-8",
            ),
        )
        yield AcquiredFiling(document, (artifact,), (body,))


def _entry_label(document: DocumentReference) -> str:
    """Name one typed filing for terminal and administrative progress."""
    return f"{document.issuer} FY{document.fiscal_year} · {document.filing_id}"


async def acquire_edgar(
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    tickers: Sequence[str] = (),
    years: Collection[int] | None = None,
    user_agent: str,
    force: bool = False,
    dry_run: bool = False,
    on_progress: OperationProgressCallback | None = None,
    progress_factory: ProgressFactory | None = None,
) -> EdgarAcquisitionResult:
    """Acquire explicit SEC filing scope into the shared manifest and named selection."""
    declared = require_user_agent(user_agent)
    catalog = read_catalog(manifest_path)
    documents = list(catalog.documents)
    added: list[DocumentReference] = []
    wanted = tuple(sorted({ticker.upper() for ticker in tickers})) or tuple(
        sorted({document.issuer for document in documents if document.registry == "sec"})
    )
    if years is not None:
        if not wanted:
            raise ValueError("--years needs --ticker when the manifest names no issuer")
        if on_progress is not None:
            on_progress(OperationProgress("discover", 0, len(wanted), "Discovering EDGAR filings"))
        async with httpx.AsyncClient(follow_redirects=True) as client:
            discovered = await discover(
                client, tickers=wanted, years=years, user_agent=declared, on_progress=on_progress
            )
        documents, added = merge_entries(documents, discovered)
    selected = [
        document
        for document in documents
        if document.registry == "sec"
        and (not wanted or document.issuer in wanted)
        and (years is None or document.fiscal_year in years)
    ]
    selection_id = selection_identity("sec", wanted, tuple(years or ()))
    if dry_run:
        return EdgarAcquisitionResult(
            len(documents), tuple(added), (), True, selection_id=selection_id
        )
    if not selected:
        raise ValueError("acquisition scope contains no SEC filings")
    targets = pending(selected, manifest=catalog, corpus_root=manifest_path.parent, force=force)
    fetched: list[tuple[Path, int]] = []

    def administrative_progress(
        document: DocumentReference,
    ) -> AbstractContextManager[ByteProgress | None]:
        """Bridge source byte progress without exposing transport details to callers."""
        if progress_factory is not None:
            return progress_factory(document)
        publish = on_progress
        if publish is None:
            return nullcontext(None)

        @contextmanager
        def bridge() -> Iterator[ByteProgress]:
            """Yield a callback scoped to this filing download."""

            def report(read: int, total: int | None) -> None:
                """Publish bounded byte progress."""
                publish(
                    OperationProgress(
                        "download", len(fetched), len(targets), _entry_label(document), read, total
                    )
                )

            yield report

        return bridge()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        async for acquired in download_pending(
            client,
            targets,
            corpus_root=manifest_path.parent,
            user_agent=declared,
            progress=administrative_progress,
        ):
            catalog = publish_acquired(
                manifest_path,
                [acquired],
                selection_id=selection_id,
                selected_document_ids=[document.document_id for document in selected],
            )
            fetched.append(
                (manifest_path.parent / acquired.primary.path, acquired.primary.byte_length)
            )
            if on_progress is not None:
                on_progress(
                    OperationProgress(
                        "download", len(fetched), len(targets), _entry_label(acquired.document)
                    )
                )
    catalog = publish_acquired(
        manifest_path,
        [],
        selection_id=selection_id,
        selected_document_ids=[document.document_id for document in selected],
    )
    if not targets and on_progress is not None:
        on_progress(OperationProgress("download", 0, 0, "Every selected filing is valid"))
    return EdgarAcquisitionResult(
        len(catalog.documents), tuple(added), tuple(fetched), selection_id=selection_id
    )


if __name__ == "__main__":  # pragma: no cover - corpus acquisition helper
    import argparse

    from app.config import get_settings
    from app.ingestion.progress import byte_bar, overall_bar

    async def _download(
        manifest_path: Path,
        tickers: tuple[str, ...],
        years: range | None,
        force: bool,
        dry_run: bool,
    ) -> None:
        """Run the reusable acquisition boundary with terminal progress."""
        try:
            user_agent = require_user_agent(get_settings().sec_user_agent)
        except ValueError as error:
            raise SystemExit(str(error)) from None
        if years is not None:
            wanted = tickers or tuple(
                dict.fromkeys(
                    entry.issuer
                    for entry in read_catalog(manifest_path).documents
                    if entry.registry == "sec"
                )
            )
            if not wanted:
                raise SystemExit("--years needs --ticker when the manifest names no issuer")
            print(
                f"discovering {ANNUAL_REPORT_FORM}s for {', '.join(wanted)} "
                f"in {years.start}-{years.stop - 1}"
            )

        def open_bar(entry: DocumentReference) -> AbstractContextManager[ByteProgress]:
            """Open a byte progress bar for one manifest entry."""
            return byte_bar(_entry_label(entry))

        try:
            result = await acquire_edgar(
                manifest_path,
                tickers=tickers,
                years=years,
                user_agent=user_agent,
                force=force,
                dry_run=dry_run,
                progress_factory=open_bar,
            )
        except ValueError as error:
            raise SystemExit(str(error)) from None
        for entry in result.added:
            print(f"  + {entry.document_id}  {entry.filing_id}  {entry.source_url}")
        if years is not None:
            print(f"{len(result.added)} new filing(s), {result.manifest_entries} in the manifest")
        if result.dry_run:
            print("dry run: neither the manifest nor any document was written")
            return
        if not result.fetched:
            print(f"nothing to fetch; every selected entry of {manifest_path} is on disk")
            return
        with overall_bar(len(result.fetched), unit="doc", description="EDGAR") as overall:
            for path, size in result.fetched:
                overall.advance(path.stem)
                overall.write(f"{path} ({size:,} bytes)")
        print(f"fetched {len(result.fetched)} document(s)")

    ap = argparse.ArgumentParser(
        description="Discover and download the EDGAR filings a manifest names."
    )
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--ticker", nargs="+", default=[], help="restrict to these tickers")
    ap.add_argument(
        "--years",
        help="widen the manifest to every 10-K in this fiscal-year range (YYYY or YYYY-YYYY); "
        "without --ticker it widens the issuers the manifest already names",
    )
    ap.add_argument("--force", action="store_true", help="re-fetch documents already on disk")
    ap.add_argument(
        "--dry-run", action="store_true", help="report what --years would add, and write nothing"
    )
    args = ap.parse_args()

    try:
        requested_years = parse_years(args.years) if args.years else None
    except ValueError as error:
        raise SystemExit(str(error)) from None

    asyncio.run(
        _download(args.manifest, tuple(args.ticker), requested_years, args.force, args.dry_run)
    )
