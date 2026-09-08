"""EDGAR corpus acquisition: request hygiene, non-filing bodies, and safe stores."""

from contextlib import contextmanager
import gzip
import hashlib
import json
from pathlib import Path

import httpx
import pytest

import app.ingestion.acquisition as acquisition
import app.ingestion.edgar_api as edgar_api
from app.ingestion.edgar_api import (
    EdgarApiError,
    acquire_edgar,
    annual_reports,
    download_pending,
    fetch_document,
    fetch_filing_rows,
    merge_entries,
    parse_years,
    pending,
    read_manifest,
    require_user_agent,
    resolve_ciks,
    store_document,
    submission_rows,
)
from app.ingestion.manifest import CorpusIdentity, Manifest
from tests.ingestion.support import client_returning, filing_document, filing_source, run

USER_AGENT = "Jane Doe jane@example.com"
URL = "https://www.sec.gov/Archives/edgar/data/1/one.htm"
FILING = b"<html><body>Item 1. Business</body></html>"


def fetch(handler):
    """Fetch the fixed test URL through one mock handler."""
    return run(fetch_document(client_returning(handler), URL, user_agent=USER_AGENT))


def entry(ticker: str, name: str):
    """Build valid shared document metadata for one mocked download."""
    suffix = int(hashlib.sha256(f"{ticker}:{name}".encode()).hexdigest()[:8], 16) % 1_000_000
    return filing_document(
        issuer=ticker, filing_id=f"0001045810-24-{suffix:06d}", document_id=f"{ticker}-{name}"
    ).model_copy(update={"source_url": f"https://www.sec.gov/Archives/edgar/data/1/{name}.htm"})


def write_manifest(tmp_path, documents):
    """Write a typed catalog containing the requested test documents."""
    path = tmp_path / "manifest.json"
    Manifest(
        corpus=CorpusIdentity(corpus_id="test", name="Test"), documents=tuple(documents)
    ).write(path)
    return path


async def collect(client, entries):
    """Collect every pending download from the asynchronous iterator."""
    return [
        item
        async for item in download_pending(
            client, entries, user_agent=USER_AGENT, corpus_root=Path.cwd()
        )
    ]


async def collect_with(client, entries, *, progress):
    """Collect pending downloads while injecting a progress factory."""
    downloads = download_pending(
        client, entries, user_agent=USER_AGENT, progress=progress, corpus_root=Path.cwd()
    )
    return [item async for item in downloads]


# --- declared contact ---


@pytest.mark.parametrize("declared", [None, "", "   "])
def test_missing_user_agent_is_rejected(declared):
    """An unset contact fails before any request rather than earning a 403."""
    with pytest.raises(ValueError, match="SEC_USER_AGENT is not configured"):
        require_user_agent(declared)


def test_user_agent_without_a_contact_address_is_rejected():
    """SEC requires a reachable operator, so a bare name is not a declaration."""
    with pytest.raises(ValueError, match="contact address"):
        require_user_agent("docreview-rag-agent")


def test_user_agent_is_returned_stripped():
    """Surrounding whitespace never reaches the header."""
    assert require_user_agent(f"  {USER_AGENT}  ") == USER_AGENT


# --- manifest reading ---


def test_missing_canonical_manifest_starts_a_new_corpus(tmp_path):
    """Allow first acquisition while refusing an alternate catalog filename."""
    assert read_manifest(tmp_path / "manifest.json").documents == ()
    with pytest.raises(ValueError, match="canonical manifest.json"):
        read_manifest(tmp_path / "other.json")


def test_broken_manifest_json_names_the_position(tmp_path):
    """Keep common-validator JSON location evidence."""
    path = tmp_path / "manifest.json"
    path.write_text("[{")
    with pytest.raises(ValueError, match="line 1"):
        read_manifest(path)


def test_manifest_refuses_legacy_lists(tmp_path):
    """Never accept the removed registry-specific list format."""
    path = tmp_path / "manifest.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="object"):
        read_manifest(path)


@pytest.mark.parametrize("missing", ["source_url", "filing_id"])
def test_document_without_required_identity_is_rejected(tmp_path, missing):
    """Validate common filing fields before starting network work."""
    path = write_manifest(tmp_path, [entry("NVDA", "one")])
    payload = json.loads(path.read_text())
    del payload["documents"][0][missing]
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match=missing):
        read_manifest(path)


def test_valid_manifest_is_returned_in_order(tmp_path):
    """Preserve common document order through serialization."""
    documents = [entry("NVDA", "one"), entry("AMD", "two")]
    assert list(read_manifest(write_manifest(tmp_path, documents)).documents) == documents


# --- selection ---


def test_documents_already_on_disk_are_skipped(tmp_path):
    """Only verified manifest artifact bytes qualify as already acquired."""
    documents = [entry("NVDA", "one"), entry("AMD", "two")]
    path = tmp_path / "source.html"
    path.write_bytes(FILING)
    source = filing_source(path, document=documents[0])
    catalog = Manifest(
        corpus=source.corpus, documents=tuple(documents), artifacts=(source.artifact,)
    )
    assert pending(documents, manifest=catalog, corpus_root=tmp_path) == [documents[1]]
    assert pending(documents, manifest=catalog, corpus_root=tmp_path, force=True) == documents
    path.write_bytes(b"tampered")
    assert pending(documents, manifest=catalog, corpus_root=tmp_path) == documents


def test_ticker_filter_is_case_insensitive(tmp_path):
    """Normalize requested ticker spelling without changing document identity."""
    documents = [entry("NVDA", "one"), entry("AMD", "two")]
    catalog = read_manifest(tmp_path / "manifest.json")
    assert pending(documents, manifest=catalog, corpus_root=tmp_path, tickers=["amd"]) == [
        documents[1]
    ]


# --- transport ---


def test_transport_failure_is_retried_then_reported(monkeypatch):
    """A dropped connection is retried, but a persistent one fails the run."""
    monkeypatch.setattr(edgar_api, "RETRY_BACKOFF_SECONDS", 0.0)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Always fail the request with a connection error."""
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(EdgarApiError, match="ConnectError") as error:
        fetch(handler)

    assert attempts == edgar_api.TRANSPORT_ATTEMPTS
    assert error.value.status is None


def test_transport_failure_recovers_within_the_attempt_budget(monkeypatch):
    """A dropped connection is retried; a later success completes the request."""
    monkeypatch.setattr(edgar_api, "RETRY_BACKOFF_SECONDS", 0.0)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Fail once, then return a filing."""
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadError("boom", request=request)
        return httpx.Response(200, content=FILING)

    assert fetch(handler) == FILING


def test_unexpected_status_carries_the_status():
    """The status EDGAR answered with survives on the error."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the requested HTTP error."""
        return httpx.Response(404, content=b"not found")

    with pytest.raises(EdgarApiError, match=r"http 404") as error:
        fetch(handler)
    assert error.value.status == 404


def test_declared_contact_travels_on_every_request():
    """Every request declares the configured contact."""
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the user agent and return a filing."""
        seen.append(request.headers.get("User-Agent"))
        return httpx.Response(200, content=FILING)

    fetch(handler)
    assert seen == [USER_AGENT]


# --- non-filing bodies ---


def test_block_page_is_refused_even_with_status_200():
    """The interstitial must fail here, not silently become an unparsable filing."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Return an automation block page with HTTP 200."""
        return httpx.Response(
            200, content=b"<h1>Your Request Originated from an Undeclared Automated Tool</h1>"
        )

    with pytest.raises(EdgarApiError, match="undeclared automation"):
        fetch(handler)


def test_empty_body_is_refused():
    """An empty response is not a filing, so nothing is stored."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Return an empty successful response."""
        return httpx.Response(200, content=b"")

    with pytest.raises(EdgarApiError, match="empty"):
        fetch(handler)


def test_oversized_body_is_refused(monkeypatch):
    """The ceiling stops a runaway response before it reaches memory twice."""
    monkeypatch.setattr(edgar_api, "MAX_DOCUMENT_BYTES", 4)

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a filing larger than the configured ceiling."""
        return httpx.Response(200, content=FILING)

    with pytest.raises(EdgarApiError, match="exceeds 4 bytes"):
        fetch(handler)


# --- storing ---


def test_store_creates_the_issuer_directory_and_leaves_no_partial(tmp_path):
    """The issuer directory is created and the staging file does not survive the write."""
    target = tmp_path / "NVDA" / "one.html"
    store_document(tmp_path, "NVDA/one.html", FILING)

    assert target.read_bytes() == FILING
    assert list(target.parent.iterdir()) == [target]


def test_failed_write_leaves_no_partial_file(tmp_path, monkeypatch):
    """A failed atomic publication preserves prior bytes and removes temporary files."""
    target = tmp_path / "NVDA/one.html"
    store_document(tmp_path, "NVDA/one.html", b"previous")

    def explode(*args):
        """Fail the final atomic publication."""
        raise OSError("disk full")

    monkeypatch.setattr(acquisition.os, "replace", explode)
    with pytest.raises(OSError, match="disk full"):
        store_document(tmp_path, "NVDA/one.html", FILING)
    assert target.read_bytes() == b"previous"
    assert list(target.parent.iterdir()) == [target]


# --- the loop ---


def test_download_stages_every_entry_and_paces_the_requests(tmp_path, monkeypatch):
    """Validated bytes await publication, and SEC requests retain their required spacing."""
    monkeypatch.chdir(tmp_path)
    waits: list[float] = []

    async def record(seconds: float) -> None:
        """Record one inter-request sleep duration."""
        waits.append(seconds)

    monkeypatch.setattr(edgar_api.asyncio, "sleep", record)

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a filing for every manifest entry."""
        return httpx.Response(200, content=FILING)

    entries = [entry("NVDA", "one"), entry("AMD", "two")]
    stored = run(collect(client_returning(handler), entries))

    assert [filing.document for filing in stored] == entries
    assert all(filing.payloads == (FILING,) for filing in stored)
    assert not list(tmp_path.rglob("*.html"))
    assert waits == [edgar_api.REQUEST_INTERVAL_SECONDS]


def test_a_failed_document_keeps_the_documents_already_fetched(tmp_path, monkeypatch):
    """A mid-run failure stops the run without discarding or truncating earlier work."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(edgar_api, "REQUEST_INTERVAL_SECONDS", 0.0)
    entries = [entry("NVDA", "one"), entry("AMD", "two")]

    def handler(request: httpx.Request) -> httpx.Response:
        """Fail the second filing while serving the first."""
        if request.url.path.endswith("two.htm"):
            return httpx.Response(500, content=b"server error")
        return httpx.Response(200, content=FILING)

    manifest = write_manifest(tmp_path, entries)
    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        edgar_api.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(EdgarApiError, match="http 500"):
        run(acquire_edgar(manifest, tickers=("NVDA", "AMD"), user_agent=USER_AGENT))

    assert len(list(tmp_path.rglob("*.html"))) == 1
    assert next(tmp_path.rglob("*.html")).read_bytes() == FILING


def test_reusable_acquisition_downloads_missing_files_and_reports_progress(tmp_path, monkeypatch):
    """Drive the CLI-independent acquisition boundary without parsing or subprocesses."""
    monkeypatch.chdir(tmp_path)
    manifest = write_manifest(tmp_path, [entry("NVDA", "one")])
    updates = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Return one filing through the injected transport."""
        return httpx.Response(200, content=FILING)

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        edgar_api.httpx,
        "AsyncClient",
        lambda **_kwargs: client_class(transport=httpx.MockTransport(handler)),
    )

    result = run(
        acquire_edgar(
            manifest,
            tickers=("NVDA",),
            user_agent=USER_AGENT,
            on_progress=updates.append,
        )
    )

    assert result.manifest_entries == 1
    assert len(result.fetched) == 1
    assert result.manifest == "manifest.json"
    assert (
        read_manifest(manifest).selected_sources(result.selection_id, tmp_path)[0].read()
        == FILING.decode()
    )
    assert updates[-1].current == updates[-1].total == 1


# --- year range ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2024", [2024]), ("2020-2022", [2020, 2021, 2022])],
)
def test_year_range_covers_both_bounds(text, expected):
    """A single year and a span both resolve to an inclusive range."""
    assert list(parse_years(text)) == expected


@pytest.mark.parametrize("text", ["", "24", "2020-", "2020-20", "twenty", "2024-2020"])
def test_unusable_year_range_is_rejected(text):
    """A malformed or backwards span fails before any request is made."""
    with pytest.raises(ValueError, match="--years"):
        parse_years(text)


# --- discovery ---


def submissions_payload(rows, *, pages=()):
    """Build a submissions document in SEC's column-wise shape."""
    columns = {
        name: [row[index] for row in rows] for index, name in enumerate(edgar_api.FILING_COLUMNS)
    }
    return {"filings": {"recent": columns, "files": [{"name": name} for name in pages]}}


TEN_K = ("10-K", "0001045810-24-000029", "2024-02-21", "2024-01-28", "nvda-20240128.htm")
TEN_K_OLD = ("10-K", "0001045810-19-000018", "2019-02-21", "2019-01-27", "nvda-2019.htm")
TEN_Q = ("10-Q", "0001045810-24-000100", "2024-05-24", "2024-04-28", "nvda-q1.htm")
AMENDED = ("10-K/A", "0001045810-24-000030", "2024-03-01", "2024-01-28", "nvda-a.htm")


def test_tickers_resolve_to_the_cik_sec_files_them_under():
    """The public ticker listing is the only place a CIK is looked up."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the public ticker-to-CIK listing."""
        payload = {
            "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA"},
            "1": {"cik_str": 2488, "ticker": "AMD", "title": "AMD"},
        }
        return httpx.Response(200, json=payload)

    resolved = run(resolve_ciks(client_returning(handler), ["nvda"], user_agent=USER_AGENT))
    assert resolved == {"NVDA": 1045810}


def test_unlisted_ticker_fails_instead_of_shrinking_the_corpus():
    """Skipping an unknown ticker would build less than was asked for, silently."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a listing that omits NVDA."""
        return httpx.Response(200, json={"0": {"cik_str": 2488, "ticker": "AMD"}})

    with pytest.raises(EdgarApiError, match="not listed: NVDA"):
        run(resolve_ciks(client_returning(handler), ["NVDA", "AMD"], user_agent=USER_AGENT))


def test_submission_columns_join_by_position():
    """Filing history arrives column-wise and is only meaningful joined by index."""
    columns = submissions_payload([TEN_K, TEN_Q])["filings"]["recent"]
    rows = submission_rows(columns)
    assert [row["form"] for row in rows] == ["10-K", "10-Q"]
    assert rows[0]["primaryDocument"] == "nvda-20240128.htm"


def test_discovered_filings_preserve_company_names_without_an_extra_request():
    """Use the submissions issuer name as a display alias for newly acquired filings."""
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a filing and its SEC-provided company name in one response."""
        requests.append(request)
        payload = submissions_payload([TEN_K])
        payload["name"] = "NVIDIA Corporation"
        return httpx.Response(200, json=payload)

    rows = run(fetch_filing_rows(client_returning(handler), 1045810, user_agent=USER_AGENT))
    entries = annual_reports(rows, ticker="NVDA", cik=1045810, years=[2024])
    assert entries[0].aliases == ("NVDA", "NVIDIA Corporation")
    assert len(requests) == 1


def test_ragged_columns_never_pair_one_filing_with_another():
    """A short column truncates the join rather than mixing two filings' fields."""
    columns = submissions_payload([TEN_K, TEN_Q])["filings"]["recent"]
    columns["reportDate"] = columns["reportDate"][:1]
    assert len(submission_rows(columns)) == 1


def test_missing_column_is_a_typed_failure():
    """A page without a column this module reads cannot be joined at all."""
    columns = submissions_payload([TEN_K])["filings"]["recent"]
    del columns["primaryDocument"]
    with pytest.raises(ValueError, match="primaryDocument"):
        submission_rows(columns)


def test_archived_submission_pages_are_followed(monkeypatch):
    """SEC moves older filings off the recent page, so the pages are followed."""
    monkeypatch.setattr(edgar_api, "REQUEST_INTERVAL_SECONDS", 0.0)
    older = {name: [TEN_K_OLD[index]] for index, name in enumerate(edgar_api.FILING_COLUMNS)}

    def handler(request: httpx.Request) -> httpx.Response:
        """Return recent submissions first and archived rows second."""
        if request.url.path.endswith("CIK0001045810.json"):
            return httpx.Response(200, json=submissions_payload([TEN_K], pages=["page-1.json"]))
        return httpx.Response(200, json=older)

    rows = run(fetch_filing_rows(client_returning(handler), 1045810, user_agent=USER_AGENT))
    assert [row["accessionNumber"] for row in rows] == [TEN_K[1], TEN_K_OLD[1]]


def test_only_unamended_annual_reports_inside_the_range_are_selected():
    """A 10-Q, an amendment, and an out-of-range year are all left out."""
    columns = submissions_payload([TEN_K, TEN_Q, AMENDED, TEN_K_OLD])["filings"]["recent"]
    entries = annual_reports(
        submission_rows(columns), ticker="NVDA", cik=1045810, years=range(2024, 2025)
    )
    assert [item.filing_id for item in entries] == [TEN_K[1]]


def test_discovered_entry_uses_common_normalized_metadata():
    """Normalize SEC dates and padded identifiers without storing a source path early."""
    built = annual_reports(
        submission_rows(submissions_payload([TEN_K])["filings"]["recent"]),
        ticker="NVDA",
        cik=1045810,
        years=(2024,),
    )[0]
    assert built.registry == "sec" and built.language == "en"
    assert built.issuer_id == "0001045810"
    assert built.filing_id == TEN_K[1]
    assert built.fiscal_year == 2024
    assert built.sec.primary_document == "nvda-20240128.htm"
    assert not hasattr(built, "file")


# --- merging ---


def manifest_item(ticker: str, year: str, accession: str):
    """Create distinct valid filing identities for catalog merge checks."""
    document = entry(ticker, accession)
    return document.model_copy(update={"fiscal_year": int(year)})


def test_existing_entries_keep_their_order_and_new_ones_follow():
    """Preserve existing identities and append deterministic newly discovered filings."""
    existing = [manifest_item("NVDA", "2024", "a"), manifest_item("AMD", "2023", "b")]
    discovered = [manifest_item("NVDA", "2020", "d"), manifest_item("AMD", "2019", "c")]
    merged, added = merge_entries(existing, discovered)
    assert merged[:2] == existing
    assert added == sorted(discovered, key=lambda document: document.document_id)
    assert merged[2:] == added


def test_a_filing_already_in_the_manifest_is_not_added_twice():
    """Re-running discovery over the same range changes nothing."""
    existing = [manifest_item("NVDA", "2024", "a")]
    merged, added = merge_entries(existing, [manifest_item("NVDA", "2024", "a")])
    assert added == []
    assert len(merged) == 1


def test_distinct_filings_for_one_fiscal_year_keep_distinct_identities():
    """Do not collapse different SEC accessions into an issuer-year database key."""
    existing = [manifest_item("NVDA", "2024", "a")]
    merged, added = merge_entries(existing, [manifest_item("NVDA", "2024", "other")])
    assert len(merged) == 2 and len(added) == 1
    assert merged[0].document_id != merged[1].document_id


def test_manifest_round_trips_through_the_writer(tmp_path):
    """Publish and read the exact common contract."""
    path = write_manifest(tmp_path, [entry("NVDA", "one")])
    catalog = read_manifest(path)
    edgar_api.write_manifest(path, catalog)
    assert read_manifest(path) == catalog


# --- progress plumbing ---


def test_each_download_opens_and_closes_its_own_progress(tmp_path, monkeypatch):
    """The library reports bytes per entry without knowing what draws them."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(edgar_api, "REQUEST_INTERVAL_SECONDS", 0.0)
    opened: list[str] = []
    seen: list[tuple[int, int | None]] = []

    @contextmanager
    def factory(item):
        """Record the entry and expose its byte-progress hook."""
        opened.append(item.document_id)
        yield lambda read, total: seen.append((read, total))

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a filing for the progress callback test."""
        return httpx.Response(200, content=FILING)

    entries = [entry("NVDA", "one"), entry("AMD", "two")]
    stored = run(collect_with(client_returning(handler), entries, progress=factory))

    assert len(stored) == 2
    assert opened == [item.document_id for item in entries]
    assert seen[0] == (0, len(FILING))
    assert (len(FILING), len(FILING)) in seen


def test_a_compressed_response_reports_bytes_without_a_false_total():
    """Content-Length describes encoded bytes, so a decoded count has no percentage."""
    seen: list[tuple[int, int | None]] = []

    compressed = gzip.compress(FILING)

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a gzip-encoded filing with its encoded length."""
        return httpx.Response(
            200,
            content=compressed,
            headers={"content-encoding": "gzip", "content-length": str(len(compressed))},
        )

    run(
        fetch_document(
            client_returning(handler),
            URL,
            user_agent=USER_AGENT,
            on_progress=lambda read, total: seen.append((read, total)),
        )
    )
    assert seen[-1] == (len(FILING), None)


def test_an_uncompressed_response_keeps_its_declared_total():
    """An identity-encoded body is counted against the length it declared."""
    seen: list[tuple[int, int | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Return an identity-encoded filing."""
        return httpx.Response(200, content=FILING)

    run(
        fetch_document(
            client_returning(handler),
            URL,
            user_agent=USER_AGENT,
            on_progress=lambda read, total: seen.append((read, total)),
        )
    )
    assert seen == [(0, len(FILING)), (len(FILING), len(FILING))]


def test_year_scope_does_not_download_other_catalog_years(tmp_path, monkeypatch):
    """A fresh clone requests only the selected fiscal year even when its catalog is broad."""
    monkeypatch.chdir(tmp_path)
    current = entry("NVDA", "current")
    old = entry("NVDA", "old").model_copy(update={"fiscal_year": 2023})
    manifest = write_manifest(tmp_path, [current, old])
    requested = []

    async def discover(*args, **kwargs):
        """Keep the already-listed selected filing without making discovery requests."""
        return [current]

    def handler(request):
        """Serve a filing and retain the actual requested URL."""
        requested.append(str(request.url))
        return httpx.Response(200, content=FILING)

    original = httpx.AsyncClient
    monkeypatch.setattr(edgar_api, "discover", discover)
    monkeypatch.setattr(
        edgar_api.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler)),
    )
    result = run(acquire_edgar(manifest, tickers=("NVDA",), years=(2024,), user_agent=USER_AGENT))
    assert len(result.fetched) == 1
    assert requested == [current.source_url]
    catalog = read_manifest(manifest)
    assert list(catalog.documents) == [current, old]
    assert [
        source.document for source in catalog.selected_sources(result.selection_id, tmp_path)
    ] == [current]
