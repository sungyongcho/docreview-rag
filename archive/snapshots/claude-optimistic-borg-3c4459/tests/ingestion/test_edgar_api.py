"""EDGAR corpus acquisition: request hygiene, non-filing bodies, and safe stores."""

from contextlib import contextmanager
import gzip
import json

import httpx
import pytest

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
from tests.ingestion.support import client_returning, run

USER_AGENT = "Jane Doe jane@example.com"
URL = "https://www.sec.gov/Archives/edgar/data/1/one.htm"
FILING = b"<html><body>Item 1. Business</body></html>"


def fetch(handler):
    """Fetch the fixed test URL through one mock handler."""
    return run(fetch_document(client_returning(handler), URL, user_agent=USER_AGENT))


def entry(ticker: str, name: str) -> dict[str, str]:
    """Build one minimal EDGAR manifest entry."""
    return {
        "ticker": ticker,
        "url": f"https://www.sec.gov/Archives/edgar/data/1/{name}.htm",
        "file": f"data/corpus/{ticker}/{name}.html",
    }


def write_manifest(tmp_path, payload) -> object:
    """Write a manifest payload and return its path."""
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


async def collect(client, entries):
    """Collect every pending download from the asynchronous iterator."""
    return [item async for item in download_pending(client, entries, user_agent=USER_AGENT)]


async def collect_with(client, entries, *, progress):
    """Collect pending downloads while injecting a progress factory."""
    downloads = download_pending(client, entries, user_agent=USER_AGENT, progress=progress)
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


def test_manifest_not_found_names_the_path(tmp_path):
    """A missing manifest names the path that was looked for."""
    with pytest.raises(ValueError, match="manifest was not found"):
        read_manifest(tmp_path / "absent.json")


def test_broken_manifest_json_names_the_position(tmp_path):
    """Broken JSON reports where parsing stopped."""
    path = tmp_path / "manifest.json"
    path.write_text("[{", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON at line 1"):
        read_manifest(path)


def test_manifest_must_hold_a_list(tmp_path):
    """A manifest is a list of entries, not a single object."""
    with pytest.raises(ValueError, match="list of entries"):
        read_manifest(write_manifest(tmp_path, {"url": "u", "file": "f"}))


@pytest.mark.parametrize("missing", ["url", "file"])
def test_entry_without_a_fetchable_field_is_rejected(tmp_path, missing):
    """Both fields are required: one names the source, the other the destination."""
    broken = entry("NVDA", "one")
    broken[missing] = "  "
    with pytest.raises(ValueError, match=f"entry 0 has no nonblank '{missing}'"):
        read_manifest(write_manifest(tmp_path, [broken]))


def test_valid_manifest_is_returned_in_order(tmp_path):
    """Entries keep manifest order, which is fetch order."""
    payload = [entry("NVDA", "one"), entry("AMD", "two")]
    assert [item["file"] for item in read_manifest(write_manifest(tmp_path, payload))] == [
        "data/corpus/NVDA/one.html",
        "data/corpus/AMD/two.html",
    ]


# --- selection ---


def test_documents_already_on_disk_are_skipped(tmp_path, monkeypatch):
    """Re-running after an interrupted download fetches only what is still missing."""
    monkeypatch.chdir(tmp_path)
    entries = [entry("NVDA", "one"), entry("AMD", "two")]
    present = tmp_path / entries[0]["file"]
    present.parent.mkdir(parents=True)
    present.write_bytes(FILING)

    assert [item["file"] for item in pending(entries)] == ["data/corpus/AMD/two.html"]
    assert len(pending(entries, force=True)) == 2


def test_ticker_filter_is_case_insensitive(tmp_path, monkeypatch):
    """A ticker is selected however the caller cased it."""
    monkeypatch.chdir(tmp_path)
    entries = [entry("NVDA", "one"), entry("AMD", "two")]
    assert [item["ticker"] for item in pending(entries, tickers=["amd"])] == ["AMD"]


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
    store_document(target, FILING)

    assert target.read_bytes() == FILING
    assert list(target.parent.iterdir()) == [target]


def test_failed_write_leaves_no_partial_file(tmp_path, monkeypatch):
    """An interrupted write must not leave bytes the next run would skip as complete."""
    target = tmp_path / "NVDA" / "one.html"

    def explode(self, data):
        """Leave a touched target and simulate a failed write."""
        self.parent.joinpath(self.name).touch()
        raise OSError("disk full")

    monkeypatch.setattr(edgar_api.Path, "write_bytes", explode)
    with pytest.raises(OSError, match="disk full"):
        store_document(target, FILING)

    assert not target.exists()
    assert list(target.parent.iterdir()) == []


# --- the loop ---


def test_download_stores_every_entry_and_paces_the_requests(tmp_path, monkeypatch):
    """Every entry lands, and requests are spaced by the interval SEC asks for."""
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

    assert [str(path) for path, _ in stored] == [item["file"] for item in entries]
    assert all(size == len(FILING) for _, size in stored)
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

    with pytest.raises(EdgarApiError, match="http 500"):
        run(collect(client_returning(handler), entries))

    assert (tmp_path / entries[0]["file"]).read_bytes() == FILING
    assert not (tmp_path / entries[1]["file"]).exists()


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
    assert (tmp_path / "data/corpus/NVDA/one.html").read_bytes() == FILING
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
    assert [item["accession"] for item in entries] == [TEN_K[1]]


def test_discovered_entry_matches_the_committed_manifest_shape():
    """A generated entry is indistinguishable from one already in the corpus."""
    columns = submissions_payload([TEN_K])["filings"]["recent"]
    built = annual_reports(
        submission_rows(columns), ticker="NVDA", cik=1045810, years=range(2024, 2025)
    )[0]
    assert built == {
        "ticker": "NVDA",
        "aliases": ["NVDA"],
        "cik": 1045810,
        "accession": "0001045810-24-000029",
        "filing_date": "2024-02-21",
        "report_date": "2024-01-28",
        "primary_doc": "nvda-20240128.htm",
        "file": "data/corpus/NVDA/2024-02-21_0001045810-24-000029.html",
        "url": (
            "https://www.sec.gov/Archives/edgar/data/1045810/000104581024000029/nvda-20240128.htm"
        ),
    }


# --- merging ---


def manifest_item(ticker: str, year: str, accession: str) -> dict[str, object]:
    """Build a manifest entry with the fields merging and ordering read."""
    return {
        "ticker": ticker,
        "accession": accession,
        "report_date": f"{year}-01-28",
        "file": f"data/corpus/{ticker}/{year}_{accession}.html",
        "url": f"https://www.sec.gov/Archives/edgar/data/1/{accession}.htm",
    }


def test_existing_entries_keep_their_order_and_new_ones_follow():
    """A widened corpus must not reshuffle the entries it was measured against."""
    existing = [manifest_item("NVDA", "2024", "a"), manifest_item("AMD", "2023", "b")]
    discovered = [manifest_item("NVDA", "2020", "d"), manifest_item("AMD", "2019", "c")]

    merged, added = merge_entries(existing, discovered)

    assert [item["accession"] for item in merged] == ["a", "b", "c", "d"]
    assert [item["accession"] for item in added] == ["c", "d"]


def test_a_filing_already_in_the_manifest_is_not_added_twice():
    """Re-running discovery over the same range changes nothing."""
    existing = [manifest_item("NVDA", "2024", "a")]
    merged, added = merge_entries(existing, [manifest_item("NVDA", "2024", "a")])
    assert added == []
    assert len(merged) == 1


def test_a_second_filing_for_one_fiscal_year_is_refused():
    """doc_id is the database key, so two filings for one year would collapse to one row."""
    existing = [manifest_item("NVDA", "2024", "a")]
    merged, added = merge_entries(existing, [manifest_item("NVDA", "2024", "other")])
    assert added == []
    assert len(merged) == 1


def test_manifest_round_trips_through_the_writer(tmp_path):
    """What the writer emits is what the reader accepts."""
    path = tmp_path / "manifest.json"
    entries = [manifest_item("NVDA", "2024", "a")]
    edgar_api.write_manifest(path, entries)
    assert read_manifest(path) == entries


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
        opened.append(item["file"])
        yield lambda read, total: seen.append((read, total))

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a filing for the progress callback test."""
        return httpx.Response(200, content=FILING)

    entries = [entry("NVDA", "one"), entry("AMD", "two")]
    stored = run(collect_with(client_returning(handler), entries, progress=factory))

    assert len(stored) == 2
    assert opened == [item["file"] for item in entries]
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
