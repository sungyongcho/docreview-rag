"""Open DART client: request validation, archive selection, and credential hygiene."""

import asyncio
import hashlib
import io
import json
import zipfile

import httpx
import pytest

from app.ingestion import dart_api
from app.ingestion.dart_api import (
    AnnualReport,
    CorpCode,
    DartApiError,
    DartArchiveError,
    DocumentArchive,
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
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def client_returning(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coroutine):
    return asyncio.run(coroutine)


# --- transport and credential hygiene ---


def test_transport_failure_never_carries_the_api_key(monkeypatch):
    """A transport error surfaces the endpoint and exception class, never the key."""
    monkeypatch.setattr(dart_api, "RETRY_BACKOFF_SECONDS", 0.0)

    def handler(request: httpx.Request) -> httpx.Response:
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
        calls["count"] += 1
        return httpx.Response(503)

    with pytest.raises(DartApiError, match="http 503"):
        run(fetch_corp_code_archive(client_returning(handler), api_key=API_KEY))
    assert calls["count"] == 1


def test_non_zip_body_reports_the_dart_status():
    """A JSON error body on a ZIP endpoint becomes a typed error with its status."""
    error = json.dumps({"status": "020", "message": "요청 제한을 초과하였습니다"}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=error)

    with pytest.raises(DartApiError) as excinfo:
        run(fetch_corp_code_archive(client_returning(handler), api_key=API_KEY))
    assert excinfo.value.dart_status == "020"


# --- corp code parsing ---


def test_parse_corp_codes_maps_each_requested_stock_code():
    archive = zip_bytes({"CORPCODE.xml": CORPCODE_XML.encode()})

    found = parse_corp_codes(archive, stock_codes=("005930", "000660"))

    assert found["005930"] == CorpCode("00126380", "삼성전자", "005930")
    assert found["000660"] == CorpCode("00164779", "SK하이닉스", "000660")


def test_parse_corp_codes_rejects_a_missing_stock_code():
    archive = zip_bytes({"CORPCODE.xml": CORPCODE_XML.encode()})

    with pytest.raises(DartApiError, match="123456"):
        parse_corp_codes(archive, stock_codes=("005930", "123456"))


def test_parse_corp_codes_rejects_a_broken_archive():
    with pytest.raises(DartArchiveError):
        parse_corp_codes(b"not a zip", stock_codes=("005930",))


# --- annual report search ---


def search_payload(rows: list[dict]) -> bytes:
    return json.dumps({"status": "000", "message": "정상", "list": rows}).encode()


def test_fetch_annual_report_rows_fixes_the_search_arguments():
    """The search request pins the documented filter set for reproducibility."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
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
        return httpx.Response(200, content=error)

    with pytest.raises(DartApiError) as excinfo:
        run(
            fetch_annual_report_rows(
                client_returning(handler), api_key=API_KEY, corp_code="00126380", filing_year=2025
            )
        )
    assert excinfo.value.dart_status == "013"


def test_fetch_annual_report_rows_rejects_a_malformed_corp_code():
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
    with pytest.raises(DartApiError, match="no 사업보고서"):
        select_annual_report([QUARTERLY], corp_code="00126380", fiscal_year=2024)


def test_select_annual_report_refuses_two_matches():
    """An amended filing produces a second row; picking one silently would move the corpus."""
    amended = dict(ANNUAL, rcept_no="20250401000001", report_nm="[기재정정]사업보고서 (2024.12)")

    with pytest.raises(DartApiError, match="2 candidate"):
        select_annual_report([ANNUAL, amended], corp_code="00126380", fiscal_year=2024)


def test_select_annual_report_refuses_a_malformed_receipt_number():
    broken = dict(ANNUAL, rcept_no="123")

    with pytest.raises(DartApiError, match="malformed receipt number"):
        select_annual_report([broken], corp_code="00126380", fiscal_year=2024)


# --- document download ---


def test_fetch_document_archive_hashes_exactly_what_was_served():
    payload = zip_bytes({f"{RCEPT_NO}.xml": b"<DOCUMENT/>"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    document = run(
        fetch_document_archive(client_returning(handler), api_key=API_KEY, rcept_no=RCEPT_NO)
    )

    assert document.zip_bytes == payload
    assert document.archive_sha256 == hashlib.sha256(payload).hexdigest()


def test_fetch_document_archive_rejects_an_error_body():
    error = json.dumps({"status": "014", "message": "파일이 존재하지 않습니다"}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=error)

    with pytest.raises(DartApiError) as excinfo:
        run(fetch_document_archive(client_returning(handler), api_key=API_KEY, rcept_no=RCEPT_NO))
    assert excinfo.value.dart_status == "014"


def test_fetch_document_archive_rejects_a_malformed_receipt_number():
    with pytest.raises(ValueError, match="fourteen digits"):
        run(fetch_document_archive(httpx.AsyncClient(), api_key=API_KEY, rcept_no="20250311"))


# --- member selection and decoding ---


def test_select_primary_member_picks_the_report_by_exact_name():
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
    raw = '<?xml version="1.0" encoding="euc-kr"?><doc>한글</doc>'.encode("cp949")

    text, encoding = decode_source(raw)

    assert "한글" in text
    assert encoding == "euc-kr"


def test_decode_source_rejects_undecodable_bytes():
    with pytest.raises(DartArchiveError, match="no strict decoding"):
        decode_source(b"\xff\xfe\xff\xff\x80\x80")


def test_canonicalize_normalizes_newlines_and_restamps_the_declaration():
    text = '<?xml version="1.0" encoding="euc-kr"?>\r\n<doc>a\rb\x0cc</doc>'

    normalized, exotic = canonicalize(text)

    assert 'encoding="utf-8"' in normalized
    assert "\r" not in normalized
    assert exotic == 1  # the form feed survives and is counted, not removed


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
    document = DocumentArchive(RCEPT_NO, b"not a zip", hashlib.sha256(b"not a zip").hexdigest())
    report = AnnualReport(RCEPT_NO, "00126380", "삼성전자", "사업보고서 (2024.12)", "20250311")
    issuer = CorpCode("00126380", "삼성전자", "005930")

    with pytest.raises(DartArchiveError, match="not a readable ZIP"):
        archive_document(document, report, issuer, fiscal_year=2024, corpus_dir=tmp_path)
