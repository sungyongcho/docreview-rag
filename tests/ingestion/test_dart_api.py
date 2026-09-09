"""Open DART client: request validation, archive selection, and credential hygiene."""

import hashlib
import io
import json
import zipfile

import httpx
import pytest

from app.ingestion.acquisition import read_catalog
import app.ingestion.dart_api as dart_api
from app.ingestion.dart_api import (
    AnnualReport,
    CorpCode,
    DartApiError,
    DartArchiveError,
    DocumentArchive,
    acquire_dart,
    archive_document,
    canonicalize,
    decode_source,
    fetch_annual_report_rows,
    fetch_corp_code_archive,
    fetch_document_archive,
    member_names,
    parse_corp_codes,
    select_annual_report,
    select_primary_member,
)
from app.ingestion.manifest import CorpusIdentity, Manifest
from app.ingestion.source_publication import publish_acquired
from tests.ingestion.support import acquired_filing, client_returning, filing_document, run

API_KEY = "k" * 40
RCEPT_NO = "20250311001085"

CORPCODE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
    <stock_code>005930</stock_code></list>
  <list><corp_code>00164779</corp_code><corp_name>SK하이닉스</corp_name>
    <stock_code>000660</stock_code></list>
  <list><corp_code>99999999</corp_code><corp_name>비상장</corp_name>
    <stock_code> </stock_code></list>
</result>
"""


def zip_bytes(members: dict[str, bytes]) -> bytes:
    """Build an in-memory ZIP archive from named byte payloads."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


# --- transport and credential hygiene ---


def test_transport_failure_never_carries_the_api_key(monkeypatch):
    """A transport error surfaces the endpoint and exception class, never the key."""
    monkeypatch.setattr(dart_api, "RETRY_BACKOFF_SECONDS", 0.0)

    def handler(request: httpx.Request) -> httpx.Response:
        """Raise a transport failure for the corp-code request."""
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(DartApiError) as excinfo:
        run(fetch_corp_code_archive(client_returning(handler), api_key=API_KEY))

    message = str(excinfo.value)
    assert API_KEY not in message
    assert "ConnectError" in message
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_transport_errors_are_retried_then_succeed(monkeypatch):
    """A dropped connection is retried; a later success completes the request."""
    monkeypatch.setattr(dart_api, "RETRY_BACKOFF_SECONDS", 0.0)
    calls = {"count": 0}
    payload = zip_bytes({"CORPCODE.xml": CORPCODE_XML.encode()})

    def handler(request: httpx.Request) -> httpx.Response:
        """Fail once, then return a valid corp-code archive."""
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.RemoteProtocolError("dropped", request=request)
        return httpx.Response(200, content=payload)

    body = run(fetch_corp_code_archive(client_returning(handler), api_key=API_KEY))

    assert body == payload
    assert calls["count"] == 2


def test_http_error_status_is_not_retried(monkeypatch):
    """An HTTP status is an answer, so it is reported on the first attempt."""
    monkeypatch.setattr(dart_api, "RETRY_BACKOFF_SECONDS", 0.0)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """Return one HTTP error response while recording the attempt."""
        calls["count"] += 1
        return httpx.Response(503)

    with pytest.raises(DartApiError, match="http 503"):
        run(fetch_corp_code_archive(client_returning(handler), api_key=API_KEY))
    assert calls["count"] == 1


def test_non_zip_body_reports_the_dart_status():
    """A JSON error body on a ZIP endpoint becomes a typed error with its status."""
    error = json.dumps({"status": "020", "message": "요청 제한을 초과하였습니다"}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a DART JSON error body from the ZIP endpoint."""
        return httpx.Response(200, content=error)

    with pytest.raises(DartApiError) as excinfo:
        run(fetch_corp_code_archive(client_returning(handler), api_key=API_KEY))
    assert excinfo.value.dart_status == "020"


# --- corp code parsing ---


def test_parse_corp_codes_maps_each_requested_stock_code():
    """Map every requested stock code to its registry corp code."""
    archive = zip_bytes({"CORPCODE.xml": CORPCODE_XML.encode()})

    found = parse_corp_codes(archive, stock_codes=("005930", "000660"))

    assert found["005930"] == CorpCode("00126380", "삼성전자", "005930")
    assert found["000660"] == CorpCode("00164779", "SK하이닉스", "000660")


def test_parse_corp_codes_rejects_a_missing_stock_code():
    """Refuse to continue when a requested stock code has no entry."""
    archive = zip_bytes({"CORPCODE.xml": CORPCODE_XML.encode()})

    with pytest.raises(DartApiError, match="123456"):
        parse_corp_codes(archive, stock_codes=("005930", "123456"))


def test_parse_corp_codes_rejects_a_broken_archive():
    """Reject an archive the registry response could not produce."""
    with pytest.raises(DartArchiveError):
        parse_corp_codes(b"not a zip", stock_codes=("005930",))


# --- annual report search ---


def search_payload(rows: list[dict]) -> bytes:
    """Encode successful annual-report search rows."""
    return json.dumps({"status": "000", "message": "정상", "list": rows}).encode()


def test_fetch_annual_report_rows_fixes_the_search_arguments():
    """The search request pins the documented filter set for reproducibility."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Capture search parameters and return an empty success payload."""
        seen.update(dict(request.url.params))
        return httpx.Response(200, content=search_payload([]))

    run(
        fetch_annual_report_rows(
            client_returning(handler), api_key=API_KEY, corp_code="00126380", filing_year=2025
        )
    )

    assert seen["bgn_de"] == "20250101"
    assert seen["end_de"] == "20251231"
    assert seen["last_reprt_at"] == "Y"
    assert seen["pblntf_ty"] == "A"
    assert seen["pblntf_detail_ty"] == "A001"


def test_fetch_annual_report_rows_treats_no_data_as_typed_failure():
    """DART status 013 is a missing corpus, not an empty result list."""
    error = json.dumps({"status": "013", "message": "조회된 데이타가 없습니다"}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the DART no-data response."""
        return httpx.Response(200, content=error)

    with pytest.raises(DartApiError) as excinfo:
        run(
            fetch_annual_report_rows(
                client_returning(handler), api_key=API_KEY, corp_code="00126380", filing_year=2025
            )
        )
    assert excinfo.value.dart_status == "013"


def test_fetch_annual_report_rows_rejects_a_malformed_corp_code():
    """Reject a corp code that cannot address a filing."""
    with pytest.raises(ValueError, match="eight digits"):
        run(
            fetch_annual_report_rows(
                httpx.AsyncClient(), api_key=API_KEY, corp_code="5930", filing_year=2025
            )
        )


# --- report selection ---

QUARTERLY = {
    "rcept_no": "20251114002447",
    "report_nm": "분기보고서 (2025.09)",
    "rcept_dt": "20251114",
}
ANNUAL = {
    "rcept_no": RCEPT_NO,
    "report_nm": "사업보고서 (2024.12)",
    "rcept_dt": "20250311",
    "corp_name": "삼성전자",
}


def test_select_annual_report_picks_the_single_period_match():
    """Quarterly and half-year rows in the same response are filtered out by period."""
    report = select_annual_report([QUARTERLY, ANNUAL], corp_code="00126380", fiscal_year=2024)

    assert report == AnnualReport(
        RCEPT_NO, "00126380", "삼성전자", "사업보고서 (2024.12)", "20250311"
    )


def test_select_annual_report_refuses_zero_matches():
    """Refuse a selection with no annual report rather than guessing."""
    with pytest.raises(DartApiError, match="no 사업보고서"):
        select_annual_report([QUARTERLY], corp_code="00126380", fiscal_year=2024)


def test_select_annual_report_refuses_two_matches():
    """An amended filing produces a second row; picking one silently would move the corpus."""
    amended = dict(ANNUAL, rcept_no="20250401000001", report_nm="[기재정정]사업보고서 (2024.12)")

    with pytest.raises(DartApiError, match="2 candidate"):
        select_annual_report([ANNUAL, amended], corp_code="00126380", fiscal_year=2024)


def test_select_annual_report_refuses_a_malformed_receipt_number():
    """Refuse a receipt number that cannot address a document."""
    broken = dict(ANNUAL, rcept_no="123")

    with pytest.raises(DartApiError, match="malformed receipt number"):
        select_annual_report([broken], corp_code="00126380", fiscal_year=2024)


# --- document download ---


def test_fetch_document_archive_hashes_exactly_what_was_served():
    """Hash the served bytes themselves, so the digest pins the response."""
    payload = zip_bytes({f"{RCEPT_NO}.xml": b"<DOCUMENT/>"})

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the exact document archive payload."""
        return httpx.Response(200, content=payload)

    document = run(
        fetch_document_archive(client_returning(handler), api_key=API_KEY, rcept_no=RCEPT_NO)
    )

    assert document.zip_bytes == payload
    assert document.archive_sha256 == hashlib.sha256(payload).hexdigest()


def test_fetch_document_archive_rejects_an_error_body():
    """Reject an error payload instead of archiving it as a filing."""
    error = json.dumps({"status": "014", "message": "파일이 존재하지 않습니다"}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a DART missing-file response."""
        return httpx.Response(200, content=error)

    with pytest.raises(DartApiError) as excinfo:
        run(fetch_document_archive(client_returning(handler), api_key=API_KEY, rcept_no=RCEPT_NO))
    assert excinfo.value.dart_status == "014"


def test_fetch_document_archive_rejects_a_malformed_receipt_number():
    """Reject a malformed receipt number before any request."""
    with pytest.raises(ValueError, match="fourteen digits"):
        run(fetch_document_archive(httpx.AsyncClient(), api_key=API_KEY, rcept_no="20250311"))


# --- member selection and decoding ---


def test_select_primary_member_picks_the_report_by_exact_name():
    """Select the report member by its exact archive name."""
    archive = zipfile.ZipFile(
        io.BytesIO(
            zip_bytes(
                {
                    f"{RCEPT_NO}_00761.xml": b"attachment",
                    f"{RCEPT_NO}.xml": b"report",
                    f"{RCEPT_NO}_00760.xml": b"attachment",
                }
            )
        )
    )

    assert select_primary_member(archive, rcept_no=RCEPT_NO) == f"{RCEPT_NO}.xml"


def test_select_primary_member_lists_members_when_the_report_is_absent():
    """Name every member when the expected report is absent."""
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes({f"{RCEPT_NO}_00760.xml": b"attachment"})))

    with pytest.raises(DartArchiveError, match=f"{RCEPT_NO}_00760.xml"):
        select_primary_member(archive, rcept_no=RCEPT_NO)


def test_member_names_recovers_cp949_names_mangled_through_cp437():
    """Recover a member name the stdlib cp437-decoded from raw CP949 bytes."""
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes({"placeholder.xml": b"payload"})))
    # The mangled state is set on the ZipInfo directly. Going through ``writestr`` would
    # re-encode a non-ASCII name as UTF-8 and set the flag, which is the case excluded here.
    info = archive.infolist()[0]
    info.filename = "사업보고서.xml".encode("cp949").decode("cp437")
    info.flag_bits &= ~0x800

    assert member_names(archive) == ["사업보고서.xml"]


def test_decode_source_honours_the_declared_encoding():
    """Decode the source with the encoding the document declares."""
    raw = '<?xml version="1.0" encoding="euc-kr"?><doc>한글</doc>'.encode("cp949")

    text, encoding = decode_source(raw)

    assert "한글" in text
    assert encoding == "euc-kr"


def test_decode_source_ignores_a_permissive_declared_encoding():
    """A declared ISO-8859-1 decodes any bytes, so the CP949 fallback must win instead."""
    raw = '<?xml version="1.0" encoding="ISO-8859-1"?><doc>사업보고서</doc>'.encode("cp949")

    text, encoding = decode_source(raw)

    assert "사업보고서" in text
    assert encoding == "cp949"


def test_decode_source_skips_an_unknown_declared_encoding():
    """A declared name ``codecs.lookup`` rejects falls through without raising."""
    raw = '<?xml version="1.0" encoding="no-such-codec"?><doc>한글</doc>'.encode("cp949")

    text, encoding = decode_source(raw)

    assert "한글" in text
    assert encoding == "cp949"


def test_decode_source_rejects_undecodable_bytes():
    """Reject bytes the declared encoding cannot decode."""
    with pytest.raises(DartArchiveError, match="no strict decoding"):
        decode_source(b"\xff\xfe\xff\xff\x80\x80")


def test_canonicalize_normalizes_newlines_and_restamps_the_declaration():
    """Normalize newlines and restamp the declaration for a stable source."""
    text = '<?xml version="1.0" encoding="euc-kr"?>\r\n<doc>a\rb\x0cc</doc>'

    normalized, exotic = canonicalize(text)

    assert 'encoding="utf-8"' in normalized
    assert "\r" not in normalized
    assert exotic == 1  # the form feed survives and is counted, not removed


def test_canonicalize_leaves_a_declaration_quoted_in_the_body_alone():
    """With no encoding in the leading declaration, quoted body content stays intact."""
    quoted = '<?xml version="1.0" encoding="euc-kr"?>'
    text = f'<?xml version="1.0"?>\n<doc>{quoted}</doc>'

    normalized, _ = canonicalize(text)

    assert normalized == text


def test_canonicalize_restamps_only_the_leading_declaration():
    """A declaration quoted in the body is content, not the document's own stamp."""
    quoted = '<?xml version="1.0" encoding="euc-kr"?>'
    text = f'<?xml version="1.0" encoding="euc-kr"?>\n<doc>{quoted}</doc>'

    normalized, _ = canonicalize(text)

    assert normalized.startswith('<?xml version="1.0" encoding="utf-8"?>')
    assert quoted in normalized


# --- archive_document end to end ---


def test_archive_document_writes_utf8_and_records_matching_identity(tmp_path):
    """The manifest entry describes the file on disk, including after transcoding."""
    source = '<?xml version="1.0" encoding="euc-kr"?>\r\n<DOCUMENT>사업보고서 본문</DOCUMENT>'
    payload = zip_bytes(
        {
            f"{RCEPT_NO}.xml": source.encode("cp949"),
            f"{RCEPT_NO}_00760.xml": b"attachment",
        }
    )
    document = DocumentArchive(RCEPT_NO, payload, hashlib.sha256(payload).hexdigest())
    report = AnnualReport(RCEPT_NO, "00126380", "삼성전자", "사업보고서 (2024.12)", "20250311")
    issuer = CorpCode("00126380", "삼성전자", "005930")

    entry = archive_document(document, report, issuer, fiscal_year=2024, corpus_dir=tmp_path)

    assert entry.primary.path == f"dart/005930/{RCEPT_NO}/primary.xml"
    assert next(a.path for a in entry.artifacts if a.role == "archive") == (
        f"dart/005930/{RCEPT_NO}/original.zip"
    )
    assert not (tmp_path / entry.primary.path).exists()
    publish_acquired(
        tmp_path / "manifest.json",
        [entry],
        selection_id="dart",
        selected_document_ids=[entry.document.document_id],
    )
    written = tmp_path / entry.primary.path
    stored = written.read_bytes().decode("utf-8")
    assert entry.document.registry == "dart"
    assert entry.document.issuer == "005930"
    assert entry.document.issuer_id == "00126380"
    assert entry.document.filing_id == RCEPT_NO
    assert entry.document.form == "사업보고서"
    assert entry.document.language == "ko"
    assert entry.document.filing_date.isoformat() == "2025-03-11"
    assert entry.document.report_period.isoformat() == "2024-12-31"
    assert entry.document.fiscal_year == 2024
    assert entry.primary.acquisition.original_encoding == "euc-kr"
    assert entry.primary.byte_length == len(stored.encode())
    assert entry.primary.sha256 == hashlib.sha256(stored.encode()).hexdigest()
    assert 'encoding="utf-8"' in stored
    assert "사업보고서 본문" in stored


def test_archive_document_rejects_a_broken_archive(tmp_path):
    """Reject a broken archive rather than storing an unreadable filing."""
    document = DocumentArchive(RCEPT_NO, b"not a zip", hashlib.sha256(b"not a zip").hexdigest())
    report = AnnualReport(RCEPT_NO, "00126380", "삼성전자", "사업보고서 (2024.12)", "20250311")
    issuer = CorpCode("00126380", "삼성전자", "005930")

    with pytest.raises(DartArchiveError, match="not a readable ZIP"):
        archive_document(document, report, issuer, fiscal_year=2024, corpus_dir=tmp_path)


# --- manifest merging ---


def dart_acquired(tmp_path, year=2024, receipt=RCEPT_NO):
    """Build a complete current DART ZIP/XML pair with explicit acquired bytes."""
    return acquired_filing(
        tmp_path,
        document=filing_document(
            registry="dart",
            fiscal_year=year,
            filing_id=receipt,
            document_id=f"dart-{receipt}",
            aliases=("삼성전자",),
        ),
        payload="<DOCUMENT>사업보고서</DOCUMENT>".encode(),
    )


def catalog_with(tmp_path, acquired):
    """Publish current source groups through the actual managed publication boundary."""
    return publish_acquired(
        tmp_path / "manifest.json",
        acquired,
        selection_id="test-selection",
        selected_document_ids=[item.document.document_id for item in acquired],
    )


def test_a_missing_manifest_is_a_first_run(tmp_path):
    """Initialize the common catalog on a first acquisition."""
    assert read_catalog(tmp_path / "manifest.json").documents == ()


def test_manifest_without_common_identity_is_rejected(tmp_path):
    """Reject the removed list-shaped DART format."""
    path = tmp_path / "manifest.json"
    path.write_text('[{"issuer":"005930"}]')
    with pytest.raises(ValueError, match="object"):
        read_catalog(path)


def test_a_second_fiscal_year_does_not_erase_the_first(tmp_path):
    """Add an explicit new selection without replacing existing catalog documents."""
    first = dart_acquired(tmp_path)
    second = dart_acquired(tmp_path, 2023, "20240311001085")
    catalog_with(tmp_path, [first])
    merged = publish_acquired(
        tmp_path / "manifest.json",
        [second],
        selection_id="second",
        selected_document_ids=[second.document.document_id],
    )
    assert [document.fiscal_year for document in merged.documents] == [2024, 2023]
    assert merged.selected_sources("test-selection", tmp_path)[0].document == first.document
    assert merged.selected_sources("second", tmp_path)[0].document == second.document


def test_re_archiving_one_filing_preserves_document_identity(tmp_path):
    """An idempotent repeat must not duplicate the filing or artifact catalog."""
    acquired = dart_acquired(tmp_path)
    catalog = catalog_with(tmp_path, [acquired])
    merged = publish_acquired(
        tmp_path / "manifest.json",
        [acquired],
        selection_id="test-selection",
        selected_document_ids=[acquired.document.document_id],
    )
    assert merged == catalog


def test_two_receipts_for_one_issuer_year_remain_distinct(tmp_path):
    """Keep separate receipt identities instead of overwriting issuer-year evidence."""
    first = dart_acquired(tmp_path)
    second = dart_acquired(tmp_path, 2024, "20250311001086")
    catalog = catalog_with(tmp_path, [first, second])
    assert len(catalog.documents) == 2 and len(catalog.artifacts) == 4


def test_manifest_round_trips_with_korean_names_intact(tmp_path):
    """Keep official aliases readable in the canonical manifest."""
    catalog = catalog_with(tmp_path, [dart_acquired(tmp_path)])
    assert "삼성전자" in (tmp_path / "manifest.json").read_text()
    assert read_catalog(tmp_path / "manifest.json") == catalog


def test_dart_acquisition_skips_a_manifest_entry_whose_source_is_valid(tmp_path, monkeypatch):
    """A matching file and digest avoid even the corp-code request."""
    acquired = dart_acquired(tmp_path)
    catalog_with(tmp_path, [acquired])

    def unexpected_client(**_kwargs):
        """Fail if a no-op acquisition attempts to construct a network client."""
        raise AssertionError("DART network client must not be constructed")

    monkeypatch.setattr(dart_api.httpx, "AsyncClient", unexpected_client)
    updates = []

    result = run(
        acquire_dart(
            stock_codes=("005930",),
            fiscal_years=(2024,),
            corpus_dir=tmp_path,
            api_key="",
            on_progress=updates.append,
        )
    )

    assert result.archived == result.added == ()
    assert result.manifest_entries == 1
    assert updates[-1].current == updates[-1].total == 0


def test_dart_acquisition_refetches_a_source_with_a_stale_digest(tmp_path, monkeypatch):
    """A manifest identity alone is insufficient when the source digest has drifted."""
    acquired = dart_acquired(tmp_path)
    catalog_with(tmp_path, [acquired])
    (tmp_path / acquired.primary.path).write_text("damaged")
    corp_codes = zip_bytes({"CORPCODE.xml": CORPCODE_XML.encode()})
    document = zip_bytes(
        {
            f"{RCEPT_NO}.xml": (
                '<?xml version="1.0" encoding="UTF-8"?><DOCUMENT>복구됨</DOCUMENT>'
            ).encode()
        }
    )
    requested_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Serve the stale target and record which endpoints were needed."""
        requested_paths.append(request.url.path)
        if request.url.path.endswith("corpCode.xml"):
            return httpx.Response(200, content=corp_codes)
        if request.url.path.endswith("list.json"):
            return httpx.Response(200, json={"status": "000", "list": [ANNUAL]})
        if request.url.path.endswith("document.xml"):
            return httpx.Response(200, content=document)
        raise AssertionError(request.url.path)

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        dart_api.httpx,
        "AsyncClient",
        lambda **_kwargs: client_class(transport=httpx.MockTransport(handler)),
    )

    result = run(
        acquire_dart(
            stock_codes=("005930",),
            fiscal_years=(2024,),
            corpus_dir=tmp_path,
            api_key=API_KEY,
        )
    )

    assert len(result.archived) == 1
    assert result.added == ()
    assert requested_paths == ["/api/document.xml"]
    stored = read_catalog(tmp_path / "manifest.json")
    selected = stored.selected_sources(result.selection_id, tmp_path)
    assert selected[0].document.filing_id == RCEPT_NO
    assert "복구됨" in selected[0].read()


def test_reusable_dart_acquisition_archives_and_merges_with_progress(tmp_path, monkeypatch):
    """Run issuer lookup, report selection, and archive storage through one reusable call."""
    corp_codes = zip_bytes({"CORPCODE.xml": CORPCODE_XML.encode()})
    document = zip_bytes(
        {
            f"{RCEPT_NO}.xml": (
                '<?xml version="1.0" encoding="UTF-8"?><DOCUMENT>사업보고서 본문</DOCUMENT>'
            ).encode()
        }
    )
    updates = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Serve each Open DART endpoint from deterministic in-memory payloads."""
        if request.url.path.endswith("corpCode.xml"):
            return httpx.Response(200, content=corp_codes)
        if request.url.path.endswith("list.json"):
            return httpx.Response(200, json={"status": "000", "list": [ANNUAL]})
        if request.url.path.endswith("document.xml"):
            return httpx.Response(200, content=document)
        raise AssertionError(request.url.path)

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        dart_api.httpx,
        "AsyncClient",
        lambda **_kwargs: client_class(transport=httpx.MockTransport(handler)),
    )

    result = run(
        acquire_dart(
            stock_codes=("005930",),
            fiscal_years=(2024,),
            corpus_dir=tmp_path,
            api_key=API_KEY,
            on_progress=updates.append,
        )
    )

    assert len(result.archived) == len(result.added) == 1
    assert result.manifest_entries == 1
    assert result.manifest == "manifest.json"
    assert (tmp_path / result.archived[0].primary.path).is_file()
    assert len(read_catalog(tmp_path / "manifest.json").artifacts) == 2
    assert updates[-1].current == updates[-1].total == 1


def test_known_issuer_reuses_identity_but_discovers_the_requested_year_live(tmp_path, monkeypatch):
    """Skip the large issuer archive while still selecting and downloading the new report."""
    previous = filing_document(
        registry="dart",
        fiscal_year=2023,
        filing_id="20240311001085",
        aliases=("Unverified display alias",),
    )
    catalog = Manifest(corpus=CorpusIdentity(corpus_id="test", name="Test"), documents=(previous,))
    catalog.write(tmp_path / "manifest.json")
    archive = zip_bytes({f"{RCEPT_NO}.xml": b"<DOCUMENT>new report</DOCUMENT>"})
    paths = []

    def handler(request):
        """Require fresh discovery with the exact previously recorded corporation ID."""
        paths.append(request.url.path)
        assert not request.url.path.endswith("corpCode.xml")
        if request.url.path.endswith("list.json"):
            assert request.url.params["corp_code"] == "00126380"
            assert request.url.params["bgn_de"] == "20250101"
            return httpx.Response(200, json={"status": "000", "list": [ANNUAL]})
        assert request.url.params["rcept_no"] == RCEPT_NO
        return httpx.Response(200, content=archive)

    client = httpx.AsyncClient
    monkeypatch.setattr(
        dart_api.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler)),
    )
    result = run(
        acquire_dart(
            stock_codes=("005930",), fiscal_years=(2024,), corpus_dir=tmp_path, api_key=API_KEY
        )
    )
    assert paths == ["/api/list.json", "/api/document.xml"]
    assert result.archived[0].document.filing_id == RCEPT_NO
    assert result.archived[0].document.fiscal_year == 2024
    assert result.archived[0].document.aliases[0] == ANNUAL["corp_name"]


@pytest.mark.parametrize("index_contains_requested", [True, False])
def test_unknown_issuer_fetches_archive_and_requires_an_exact_resolution(
    tmp_path, monkeypatch, index_contains_requested
):
    """A different known issuer cannot supply or guess the requested corporation ID."""
    known = filing_document(registry="dart")
    Manifest(corpus=CorpusIdentity(corpus_id="test", name="Test"), documents=(known,)).write(
        tmp_path / "manifest.json"
    )
    corp_xml = (
        CORPCODE_XML if index_contains_requested else CORPCODE_XML.replace("000660", "999999")
    )
    corp_archive = zip_bytes({"CORPCODE.xml": corp_xml.encode()})
    receipt = "20250319000665"
    report = dict(ANNUAL, rcept_no=receipt, corp_name="SK하이닉스", rcept_dt="20250319")
    archive = zip_bytes({f"{receipt}.xml": b"<DOCUMENT>new report</DOCUMENT>"})
    paths = []

    def handler(request):
        """Serve the issuer archive and validate strict use of its newly resolved ID."""
        paths.append(request.url.path)
        if request.url.path.endswith("corpCode.xml"):
            return httpx.Response(200, content=corp_archive)
        if request.url.path.endswith("list.json"):
            assert request.url.params["corp_code"] == "00164779"
            return httpx.Response(200, json={"status": "000", "list": [report]})
        assert request.url.params["rcept_no"] == receipt
        return httpx.Response(200, content=archive)

    client = httpx.AsyncClient
    monkeypatch.setattr(
        dart_api.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler)),
    )
    operation = acquire_dart(
        stock_codes=("000660",), fiscal_years=(2024,), corpus_dir=tmp_path, api_key=API_KEY
    )
    if not index_contains_requested:
        with pytest.raises(DartApiError, match="000660"):
            run(operation)
        assert paths == ["/api/corpCode.xml"]
    else:
        result = run(operation)
        assert result.archived[0].document.issuer_id == "00164779"
        assert paths == ["/api/corpCode.xml", "/api/list.json", "/api/document.xml"]


def test_conflicting_typed_issuer_ids_are_not_reused():
    """Ambiguous catalog IDs require live issuer-index resolution."""
    first = filing_document(registry="dart")
    second = filing_document(registry="dart", fiscal_year=2023, filing_id="20240311001085")
    assert second.dart is not None
    second = second.model_copy(
        update={
            "issuer_id": "00999999",
            "dart": second.dart.model_copy(update={"corp_code": "00999999"}),
        }
    )
    catalog = Manifest(
        corpus=CorpusIdentity(corpus_id="test", name="Test"), documents=(first, second)
    )
    assert dart_api._known_issuers(catalog, ("005930",)) == {}


def test_same_year_missing_receipt_is_reacquired_without_replacing_ready_filing(
    tmp_path, monkeypatch
):
    """A ready filing in the same year cannot hide a different missing receipt."""
    ready = dart_acquired(tmp_path, receipt="20250311001084")
    missing = dart_acquired(tmp_path, receipt=RCEPT_NO)
    catalog_with(tmp_path, [ready, missing])
    (tmp_path / missing.primary.path).unlink()
    requests = []
    payload = zip_bytes({f"{RCEPT_NO}.xml": b"<DOCUMENT>Recovered exact receipt</DOCUMENT>"})

    def handler(request):
        """Serve only the already identified missing receipt, without issuer/year rediscovery."""
        requests.append(str(request.url))
        assert request.url.path.endswith("document.xml")
        assert request.url.params["rcept_no"] == RCEPT_NO
        return httpx.Response(200, content=payload)

    client = httpx.AsyncClient
    monkeypatch.setattr(
        dart_api.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler)),
    )
    result = run(
        acquire_dart(
            stock_codes=("005930",), fiscal_years=(2024,), corpus_dir=tmp_path, api_key=API_KEY
        )
    )
    assert len(requests) == len(result.archived) == 1
    catalog = read_catalog(tmp_path / "manifest.json")
    assert {d.filing_id for d in catalog.documents} == {ready.document.filing_id, RCEPT_NO}
    assert len(catalog.selected_sources(result.selection_id, tmp_path)) == 2


def registered_dart_filing(root, receipt=RCEPT_NO):
    """Publish a real synthetic ZIP and linked XML through the acquisition boundary."""
    payload = zip_bytes({f"{receipt}.xml": f"<DOCUMENT>{receipt}</DOCUMENT>".encode()})
    entry = archive_document(
        DocumentArchive(receipt, payload, hashlib.sha256(payload).hexdigest()),
        AnnualReport(receipt, "00126380", "Samsung", "Annual report", "2025-03-11"),
        CorpCode("00126380", "Samsung", "005930"),
        fiscal_year=2024,
        corpus_dir=root,
    )
    publish_acquired(
        root / "manifest.json",
        [entry],
        selection_id=receipt,
        selected_document_ids=[entry.document.document_id],
    )
    return entry


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_registered_archive_recovers_exact_receipt_and_preserves_other_inputs(
    tmp_path, monkeypatch, damage
):
    """ZIP recovery keeps the good primary, another same-year filing and pinned job inputs."""
    from app.ingestion.source_selection import record_selection, source_inventory

    target = registered_dart_filing(tmp_path)
    other = registered_dart_filing(tmp_path, "20250311001084")
    name, selection = record_selection(
        tmp_path, ("005930",), (2024,), (target.document.document_id,)
    )
    pinned = (tmp_path / name).read_bytes()
    before = read_catalog(tmp_path / "manifest.json")
    other_artifacts = tuple(
        a for a in before.artifacts if a.document_id == other.document.document_id
    )
    other_bytes = {a.path: a.read_bytes(tmp_path) for a in other_artifacts}
    primary_bytes = target.primary.read_bytes(tmp_path)
    archive = next(a for a in target.artifacts if a.role == "archive")
    if damage == "missing":
        (tmp_path / archive.path).unlink()
    else:
        (tmp_path / archive.path).write_bytes(b"x" * archive.byte_length)
    requested = []

    def handler(request):
        """Serve only the exact damaged receipt without discovering another filing."""
        requested.append(request.url.params["rcept_no"])
        assert request.url.path == "/api/document.xml"
        assert requested[-1] == RCEPT_NO
        return httpx.Response(200, content=target.payloads[0])

    client = httpx.AsyncClient
    monkeypatch.setattr(
        dart_api.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler)),
    )
    result = run(
        acquire_dart(
            stock_codes=("005930",), fiscal_years=(2024,), corpus_dir=tmp_path, api_key=API_KEY
        )
    )
    assert requested == [RCEPT_NO] and len(result.archived) == 1 and result.added == ()
    assert archive.read_bytes(tmp_path) == target.payloads[0]
    assert target.primary.read_bytes(tmp_path) == primary_bytes
    restored = read_catalog(tmp_path / "manifest.json")
    assert restored.documents == before.documents
    assert (
        tuple(a for a in restored.artifacts if a.document_id == other.document.document_id)
        == other_artifacts
    )
    assert all((tmp_path / path).read_bytes() == payload for path, payload in other_bytes.items())
    assert (tmp_path / name).read_bytes() == pinned
    assert (
        Manifest.read(tmp_path / name).selected_sources(selection, tmp_path)[0].read().encode()
        == primary_bytes
    )
    assert all(row.ready and not row.can_redownload for row in source_inventory(tmp_path))


@pytest.mark.parametrize("conflict", ["primary", "archive_link", "archive_link_missing_primary"])
def test_dart_identity_conflicts_block_before_download_or_publication(
    tmp_path, monkeypatch, conflict
):
    """Unknown lineage never becomes an automatic download or a replacement of registered data."""
    from app.ingestion.source_selection import source_inventory

    target = registered_dart_filing(tmp_path)
    catalog = read_catalog(tmp_path / "manifest.json")
    if conflict == "primary":
        artifact = target.primary.model_copy(
            update={
                "artifact_id": "conflicting-primary",
                "path": "missing-conflict.xml",
                "sha256": "0" * 64,
            }
        )
        catalog = catalog.model_copy(update={"artifacts": (*catalog.artifacts, artifact)})
    else:
        primary = target.primary.model_copy(
            update={
                "acquisition": target.primary.acquisition.model_copy(
                    update={"archive_sha256": "0" * 64}
                )
            }
        )
        catalog = catalog.model_copy(
            update={
                "artifacts": tuple(primary if a.role == "primary" else a for a in catalog.artifacts)
            }
        )
    catalog.write(tmp_path / "manifest.json")
    if conflict == "archive_link_missing_primary":
        (tmp_path / target.primary.path).unlink()
    before = (tmp_path / "manifest.json").read_bytes()
    row = source_inventory(tmp_path)[0]
    assert not row.ready and not row.can_redownload

    def unexpected_client(**kwargs):
        """No provider interaction is authorized for conflicting source identities."""
        raise AssertionError("Network must not be reached")

    monkeypatch.setattr(dart_api.httpx, "AsyncClient", unexpected_client)
    with pytest.raises(ValueError, match="Conflicting primary|Archive identity"):
        run(
            acquire_dart(
                stock_codes=("005930",), fiscal_years=(2024,), corpus_dir=tmp_path, api_key=API_KEY
            )
        )
    with pytest.raises(ValueError, match="Conflicting primary|Archive identity"):
        publish_acquired(
            tmp_path / "manifest.json",
            [target],
            selection_id="retry",
            selected_document_ids=[target.document.document_id],
        )
    assert (tmp_path / "manifest.json").read_bytes() == before
    assert all(
        a.read_bytes(tmp_path) == payload
        for a, payload in zip(target.artifacts, target.payloads, strict=True)
        if conflict != "archive_link_missing_primary" or a.role != "primary"
    )
    if conflict == "archive_link_missing_primary":
        assert not (tmp_path / target.primary.path).exists()


def test_unrelated_archive_lineage_does_not_block_selected_filing(tmp_path, monkeypatch):
    """A conflict outside the requested year cannot prevent a valid no-op acquisition."""
    selected = registered_dart_filing(tmp_path)
    unrelated = dart_acquired(tmp_path, year=2023, receipt="20240311001085")
    publish_acquired(
        tmp_path / "manifest.json",
        [unrelated],
        selection_id="unrelated",
        selected_document_ids=[unrelated.document.document_id],
    )
    catalog = read_catalog(tmp_path / "manifest.json")
    conflicting = unrelated.primary.model_copy(
        update={
            "artifact_id": "unrelated-conflict",
            "path": "unrelated-conflict.xml",
            "sha256": "0" * 64,
        }
    )
    catalog.model_copy(
        update={
            "documents": catalog.documents,
            "artifacts": (*catalog.artifacts, conflicting),
        }
    ).write(tmp_path / "manifest.json")
    original = (tmp_path / unrelated.primary.path).read_bytes()

    def unexpected_client(**kwargs):
        """The requested filing is complete and needs no provider call."""
        raise AssertionError("Network must not be reached")

    monkeypatch.setattr(dart_api.httpx, "AsyncClient", unexpected_client)
    result = run(
        acquire_dart(stock_codes=("005930",), fiscal_years=(2024,), corpus_dir=tmp_path, api_key="")
    )
    assert result.archived == ()
    assert (tmp_path / unrelated.primary.path).read_bytes() == original
    assert selected.primary.read_bytes(tmp_path) == selected.payloads[-1]


def test_missing_archive_cannot_hide_later_same_year_lineage_conflict(tmp_path, monkeypatch):
    """Every requested receipt is checked before key validation or provider setup."""
    missing = registered_dart_filing(tmp_path)
    conflicting = registered_dart_filing(tmp_path, "20250311001084")
    archive = next(a for a in missing.artifacts if a.role == "archive")
    (tmp_path / archive.path).unlink()
    catalog = read_catalog(tmp_path / "manifest.json")
    primary = conflicting.primary.model_copy(
        update={
            "acquisition": conflicting.primary.acquisition.model_copy(
                update={"archive_sha256": "0" * 64}
            )
        }
    )
    catalog = catalog.model_copy(
        update={
            "artifacts": tuple(
                primary if a.artifact_id == primary.artifact_id else a for a in catalog.artifacts
            )
        }
    )
    catalog.write(tmp_path / "manifest.json")

    def unexpected_client(**kwargs):
        """A nonrecoverable requested filing must fail before constructing a provider client."""
        raise AssertionError("Network client must not be constructed")

    monkeypatch.setattr(dart_api.httpx, "AsyncClient", unexpected_client)
    with pytest.raises(ValueError, match="Archive identity"):
        dart_api.pending_dart_targets(
            catalog, stock_codes=("005930",), fiscal_years=(2024,), corpus_dir=tmp_path
        )
    with pytest.raises(ValueError, match="Archive identity"):
        run(
            acquire_dart(
                stock_codes=("005930",), fiscal_years=(2024,), corpus_dir=tmp_path, api_key=""
            )
        )
