"""Discover EDGAR 10-K filings and fetch them onto the paths a manifest names.

The manifest stays the contract between this module and everything downstream: an
entry carries the SEC ``url`` and the repository-relative ``file`` the parser will
later read. Fetching only makes the working tree agree with what the manifest says,
which is what lets raw filings stay untracked. Discovery is the other half — it
writes entries for filings the manifest does not name yet, in exactly the shape the
committed corpus already uses, and never rewrites an entry that is already there.

Two things separate a stored document from a stored response. SEC requires a
declared contact in ``User-Agent`` and throttles clients that omit one, so the
address is configuration rather than a value edited into a snippet. And EDGAR
answers automation it considers undeclared with an interstitial page that can
arrive with HTTP 200 — writing that page would turn a fetch problem into a parse
failure twenty steps downstream, so the body is checked before it reaches disk.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Collection, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
import json
from pathlib import Path
from typing import Any, Final

import httpx

from app.ingestion.edgar import doc_id, edgar_sort_key
from app.ingestion.progress import ByteProgress

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
ProgressFactory = Callable[[Mapping[str, Any]], AbstractContextManager[ByteProgress | None]]


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


def read_manifest(path: Path) -> list[dict[str, Any]]:
    """Return the manifest entries needed to fetch, checking only what fetching needs.

    Ingestion validates a manifest through ``load_seed_batch``, which parses each
    filing and therefore requires the very files this command has not downloaded yet.
    So the check here is deliberately weaker: a list of entries that each name a URL
    and a destination.

    Raises
    ------
    ValueError
        If the file is missing, is not UTF-8 JSON, or holds an entry without a
        nonblank ``url`` and ``file``.
    """
    if not path.is_file():
        raise ValueError(f"manifest was not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise ValueError(f"manifest must be UTF-8 text: {path}") from None
    except json.JSONDecodeError as error:
        raise ValueError(
            f"manifest is not valid JSON at line {error.lineno} column {error.colno}: {path}"
        ) from None
    if not isinstance(payload, list):
        raise ValueError(f"manifest must hold a list of entries: {path}")
    for index, entry in enumerate(payload):
        if not isinstance(entry, Mapping):
            raise ValueError(f"manifest entry {index} is not an object")
        for key in ("url", "file"):
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"manifest entry {index} has no nonblank {key!r}")
    return list(payload)


def write_manifest(path: Path, entries: Sequence[Mapping[str, Any]]) -> None:
    """Write the manifest back with the same shape and indentation it is kept in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([dict(entry) for entry in entries], indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")


def merge_entries(
    existing: Sequence[Mapping[str, Any]], discovered: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the manifest with new filings appended, and the filings that were new.

    Existing entries keep their identity and their position: a corpus that has been
    measured against should not shuffle because someone widened it, and a diff that
    shows only additions is one a reader can check. New entries land after them,
    ordered by the registry's own key.

    A filing is new when neither its accession nor its ``doc_id`` is already present.
    The second test matters because ``doc_id`` is the database key — two filings that
    report the same fiscal year would collapse into one row on ingest.
    """
    merged = [dict(entry) for entry in existing]
    accessions = {str(entry.get("accession", "")) for entry in merged}
    documents = {doc_id(entry) for entry in merged}

    added: list[dict[str, Any]] = []
    for entry in sorted((dict(item) for item in discovered), key=edgar_sort_key):
        if str(entry["accession"]) in accessions or doc_id(entry) in documents:
            continue
        accessions.add(str(entry["accession"]))
        documents.add(doc_id(entry))
        added.append(entry)
    return merged + added, added


def pending(
    entries: Sequence[Mapping[str, Any]],
    *,
    force: bool = False,
    tickers: Collection[str] = (),
) -> list[dict[str, Any]]:
    """Return the entries still to fetch, in manifest order.

    An entry already on disk is skipped unless ``force`` is set, which is what makes
    the command safe to re-run after an interrupted download.
    """
    wanted = {ticker.upper() for ticker in tickers}
    selected = []
    for entry in entries:
        if wanted and str(entry.get("ticker", "")).upper() not in wanted:
            continue
        if not force and Path(entry["file"]).exists():
            continue
        selected.append(dict(entry))
    return selected


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
    filings = payload.get("filings") if isinstance(payload, Mapping) else None
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
    return rows


def manifest_entry(ticker: str, cik: int, row: Mapping[str, str]) -> dict[str, Any]:
    """Build one manifest entry in the shape the committed corpus already uses."""
    accession = row["accessionNumber"]
    return {
        "ticker": ticker,
        "cik": cik,
        "accession": accession,
        "filing_date": row["filingDate"],
        "report_date": row["reportDate"],
        "primary_doc": row["primaryDocument"],
        "file": str(CORPUS_ROOT / ticker / f"{row['filingDate']}_{accession}.html"),
        "url": ARCHIVE_URL.format(
            cik=cik, accession=accession.replace("-", ""), document=row["primaryDocument"]
        ),
    }


def annual_reports(
    rows: Sequence[Mapping[str, str]], *, ticker: str, cik: int, years: Collection[int]
) -> list[dict[str, Any]]:
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
) -> list[dict[str, Any]]:
    """Return manifest entries for every requested issuer's 10-K filings in range."""
    ciks = await resolve_ciks(client, tickers, user_agent=user_agent)
    entries: list[dict[str, Any]] = []
    for position, (ticker, cik) in enumerate(ciks.items()):
        if position:
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        rows = await fetch_filing_rows(client, cik, user_agent=user_agent)
        entries.extend(annual_reports(rows, ticker=ticker, cik=cik, years=years))
    return entries


# --- fetching ---


def store_document(path: Path, body: bytes) -> None:
    """Write one filing to its manifest path, never leaving a partial file behind.

    The bytes land beside the target first and are renamed into place, so an
    interrupted run leaves the destination either absent or complete — never a
    truncated file that the next run would skip as already fetched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + PARTIAL_SUFFIX)
    try:
        partial.write_bytes(body)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def _no_progress(entry: Mapping[str, Any]) -> AbstractContextManager[ByteProgress | None]:
    """Report nothing for one entry, for callers that only want the documents."""
    return nullcontext(None)


async def download_pending(
    client: httpx.AsyncClient,
    entries: Sequence[Mapping[str, Any]],
    *,
    user_agent: str,
    progress: ProgressFactory | None = None,
) -> AsyncIterator[tuple[Path, int]]:
    """Fetch and store each entry, yielding what landed as it lands.

    Results are yielded rather than printed so the pacing and the reporting stay in
    different places: this loop owns the interval SEC asks for, the caller owns the
    display it opens through ``progress``.
    """
    open_progress = progress or _no_progress
    for index, entry in enumerate(entries):
        if index:
            await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        with open_progress(entry) as on_progress:
            body = await fetch_document(
                client, entry["url"], user_agent=user_agent, on_progress=on_progress
            )
        path = Path(entry["file"])
        store_document(path, body)
        yield path, len(body)


if __name__ == "__main__":  # pragma: no cover - corpus acquisition helper
    import argparse

    from app.config import get_settings
    from app.ingestion.progress import byte_bar, overall_bar

    def _label(entry: Mapping[str, Any]) -> str:
        """Name one entry the way a person reading the bar would name it."""
        document = entry.get("primary_doc") or Path(entry["file"]).name
        return f"{doc_id(dict(entry))} · {document}"

    async def _widen(
        manifest_path: Path,
        entries: list[dict[str, Any]],
        *,
        tickers: tuple[str, ...],
        years: range,
        user_agent: str,
        dry_run: bool,
    ) -> list[dict[str, Any]]:
        """Discover filings in range and record the ones the manifest does not name."""
        wanted = tickers or tuple(
            dict.fromkeys(str(entry["ticker"]) for entry in entries if entry.get("ticker"))
        )
        if not wanted:
            raise SystemExit("--years needs --ticker when the manifest names no issuer")

        print(
            f"discovering {ANNUAL_REPORT_FORM}s for {', '.join(wanted)} "
            f"in {years.start}-{years.stop - 1}"
        )
        async with httpx.AsyncClient(follow_redirects=True) as client:
            discovered = await discover(client, tickers=wanted, years=years, user_agent=user_agent)
        merged, added = merge_entries(entries, discovered)
        for entry in added:
            print(f"  + {doc_id(entry)}  {entry['accession']}  {entry['url']}")
        print(f"{len(added)} new filing(s), {len(merged)} in the manifest")

        if dry_run:
            print("dry run: neither the manifest nor any document was written")
            return []
        if added:
            write_manifest(manifest_path, merged)
        return merged

    async def _download(
        manifest_path: Path,
        tickers: tuple[str, ...],
        years: range | None,
        force: bool,
        dry_run: bool,
    ) -> None:
        """Widen the manifest when asked, then fetch everything it names that is missing."""
        try:
            user_agent = require_user_agent(get_settings().sec_user_agent)
            entries = read_manifest(manifest_path)
        except ValueError as error:
            raise SystemExit(str(error)) from None

        if years is not None:
            entries = await _widen(
                manifest_path,
                entries,
                tickers=tickers,
                years=years,
                user_agent=user_agent,
                dry_run=dry_run,
            )
            if not entries:
                return

        targets = pending(entries, force=force, tickers=tickers)
        if not targets:
            print(f"nothing to fetch; every selected entry of {manifest_path} is on disk")
            return

        stored = 0
        async with httpx.AsyncClient(follow_redirects=True) as client:
            with overall_bar(len(targets), unit="doc", description="EDGAR") as overall:

                def open_bar(entry: Mapping[str, Any]) -> AbstractContextManager[ByteProgress]:
                    """Open a byte progress bar for one manifest entry."""
                    return byte_bar(_label(entry))

                downloads = download_pending(
                    client, targets, user_agent=user_agent, progress=open_bar
                )
                async for path, size in downloads:
                    stored += 1
                    overall.advance(doc_id(targets[stored - 1]))
                    overall.write(f"{path} ({size:,} bytes)")
        print(f"fetched {stored} document(s)")

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
