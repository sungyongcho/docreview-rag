"""Open DART client: request validation, archive selection, and credential hygiene."""

import hashlib
import io
import json
import zipfile

import httpx
import pytest

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
from tests.ingestion.support import client_returning, run

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

    written = tmp_path / "dart" / "005930" / f"{RCEPT_NO}.xml"
    stored = written.read_bytes().decode("utf-8")
    assert entry["registry"] == "dart"
    assert entry["issuer"] == "005930"
    assert entry["issuer_id"] == "00126380"
    assert entry["filing_id"] == RCEPT_NO
    assert entry["form"] == "사업보고서"
    assert entry["language"] == "ko"
    assert entry["filing_date"] == "2025-03-11"
    assert entry["report_period"] == "2024-12-31"
    assert entry["fiscal_year"] == 2024
    assert entry["source_encoding"] == "euc-kr"
    assert entry["source_length"] == len(stored)
    assert entry["source_sha256"] == hashlib.sha256(stored.encode()).hexdigest()
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


def dart_entry(issuer: str, fiscal_year: int, filing_id: str) -> dict[str, object]:
    """Build a DART manifest entry with the fields reading and merging depend on."""
    return {
        "issuer": issuer,
        "fiscal_year": fiscal_year,
        "filing_id": filing_id,
        "file": f"data/corpus/dart/{issuer}/{filing_id}.xml",
        "source_sha256": filing_id,
    }


def test_a_missing_manifest_is_a_first_run(tmp_path):
    """Creating the manifest is the command's job, so its absence is not an error."""
    assert dart_api.read_manifest(tmp_path / "dart-manifest.json") == []


def test_manifest_entry_without_an_identity_is_rejected(tmp_path):
    """An entry that names no filing and no file cannot be merged against."""
    path = tmp_path / "dart-manifest.json"
    path.write_text(json.dumps([{"issuer": "005930"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="entry 0 has no nonblank 'filing_id'"):
        dart_api.read_manifest(path)


def test_a_second_fiscal_year_does_not_erase_the_first():
    """Writing the file wholesale used to cost the previous run's filings."""
    existing = [dart_entry("005930", 2024, "a")]
    merged, added = dart_api.merge_manifest(existing, [dart_entry("005930", 2023, "b")])

    assert [item["fiscal_year"] for item in merged] == [2024, 2023]
    assert [item["filing_id"] for item in added] == ["b"]


def test_re_archiving_one_filing_replaces_its_entry():
    """The bytes on disk were just rewritten, so the recorded digest must follow."""
    existing = [dart_entry("005930", 2024, "a") | {"source_sha256": "stale"}]
    merged, added = dart_api.merge_manifest(existing, [dart_entry("005930", 2024, "a")])

    assert len(merged) == 1
    assert merged[0]["source_sha256"] == "a"
    assert added == []


def test_two_receipts_for_one_issuer_year_stay_one_entry():
    """The document ID is the database key: one issuer-year is one row."""
    existing = [dart_entry("005930", 2024, "a")]
    merged, _ = dart_api.merge_manifest(existing, [dart_entry("005930", 2024, "amended")])

    assert len(merged) == 1
    assert merged[0]["filing_id"] == "amended"


def test_manifest_round_trips_with_korean_names_intact(tmp_path):
    """Issuer names stay readable in the file, so a human can check what was archived."""
    path = tmp_path / "dart-manifest.json"
    entries = [dart_entry("005930", 2024, "a") | {"corp_name": "삼성전자"}]
    dart_api.write_manifest(path, entries)

    assert "삼성전자" in path.read_text(encoding="utf-8")
    assert dart_api.read_manifest(path) == entries


def test_dart_acquisition_skips_a_manifest_entry_whose_source_is_valid(tmp_path, monkeypatch):
    """A matching file and digest avoid even the corp-code request."""
    source_path = tmp_path / "dart/005930/existing.xml"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("사업보고서", encoding="utf-8")
    source = source_path.read_text(encoding="utf-8")
    entry = dart_entry("005930", 2024, "existing") | {
        "file": str(source_path),
        "source_length": len(source),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
    }
    dart_api.write_manifest(tmp_path / "dart-manifest.json", [entry])

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
    source_path = tmp_path / "dart/005930/existing.xml"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("damaged", encoding="utf-8")
    entry = dart_entry("005930", 2024, "existing") | {
        "file": str(source_path),
        "source_length": len("damaged"),
        "source_sha256": "0" * 64,
    }
    dart_api.write_manifest(tmp_path / "dart-manifest.json", [entry])
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
    assert requested_paths == [
        "/api/corpCode.xml",
        "/api/list.json",
        "/api/document.xml",
    ]
    stored = dart_api.read_manifest(tmp_path / "dart-manifest.json")
    assert stored[0]["filing_id"] == RCEPT_NO
    assert stored[0]["source_sha256"] != "0" * 64


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
    assert (tmp_path / "dart/005930" / f"{RCEPT_NO}.xml").is_file()
    assert updates[-1].current == updates[-1].total == 1
