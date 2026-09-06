"""DART parser: part detection, section contract, and source identity fail-closed."""

import hashlib
import json
from pathlib import Path

import pytest

from app.ingestion.dart import (
    DART_LEAF_TAGS,
    DART_PARTS,
    DartParseError,
    dart_doc_id,
    dart_section_label,
    parse_dart_filing,
    part_numeral,
    segment,
)
from app.ingestion.parser import leaf_blocks, normalize

MINIMAL_SOURCE = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT>
<BODY>
<LIBRARY><TITLE ATOC="N">표지</TITLE><P>표지 문단</P></LIBRARY>
<SECTION-1 ACLASS="MANDATORY"><TITLE ATOC="Y">I. 회사의 개요</TITLE>
<SECTION-2><TITLE>1. 회사의 개요</TITLE>
<P>당사는 반도체를 생산한다.</P>
<TABLE-GROUP><TITLE>(단위: 백만원)</TITLE>
<TABLE BORDER="1"><TR><TD>매출액</TD><TD>300,870,903</TD></TR></TABLE>
</TABLE-GROUP>
</SECTION-2>
</SECTION-1>
<SECTION-1 ACLASS="MANDATORY"><TITLE ATOC="Y">II. 사업의 내용</TITLE>
<P>사업 개황 문단.</P>
</SECTION-1>
<SECTION-1 ACLASS="MANDATORY"><TITLE ATOC="Y">III. 재무에 관한 사항</TITLE>
<P>재무 요약 문단.</P>
</SECTION-1>
</BODY>
</DOCUMENT>
"""


def elements_of(source: str) -> list:
    return leaf_blocks(normalize(source), DART_LEAF_TAGS)


def entry_for(path: Path, source: str) -> dict:
    return {
        "registry": "dart",
        "issuer": "005930",
        "issuer_id": "00126380",
        "filing_id": "20250311001085",
        "form": "사업보고서",
        "language": "ko",
        "filing_date": "2025-03-11",
        "report_period": "2024-12-31",
        "fiscal_year": 2024,
        "file": str(path),
        "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250311001085",
        "source_length": len(source),
        "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
    }


def write_source(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "20250311001085.xml"
    path.write_bytes(source.encode("utf-8"))
    return path


# --- part heading recognition ---


def test_part_numeral_reads_the_registry_headings():
    assert part_numeral("I. 회사의 개요") == ("I", "회사의 개요")
    assert part_numeral("XII. 상세표") == ("XII", "상세표")


def test_part_numeral_folds_unicode_numerals_and_fullwidth_period():
    assert part_numeral("Ⅷ．임원 및 직원 등에 관한 사항") == ("VIII", "임원 및 직원 등에 관한 사항")


def test_part_numeral_rejects_non_part_text():
    assert part_numeral("【 대표이사 등의 확인 】") is None
    assert part_numeral("1. 회사의 개요") is None
    assert part_numeral("XIII. 존재하지 않는 장") is None
    assert part_numeral("IV 없는 구분점") is None


def test_dart_section_label_spells_numeral_and_division_name():
    assert dart_section_label("I") == "I. 회사의 개요"
    assert dart_section_label("III") == "III. 재무에 관한 사항"
    assert dart_section_label("Z") == "Z"


# --- segmentation ---


def test_segment_builds_one_section_per_numbered_division():
    source = MINIMAL_SOURCE

    sections, warnings = segment(elements_of(source), source)

    assert [section.part for section in sections] == ["I", "II", "III"]
    assert [section.item for section in sections] == ["I", "II", "III"]
    assert [section.canonical_title for section in sections] == [
        "회사의 개요",
        "사업의 내용",
        "재무에 관한 사항",
    ]
    assert sections[0].reported_title == "I. 회사의 개요"
    assert warnings == []


def test_segment_drops_cover_material_before_the_first_division():
    source = MINIMAL_SOURCE

    sections, _ = segment(elements_of(source), source)

    texts = [block.text for section in sections for block in section.blocks]
    assert "표지 문단" not in texts


def test_segment_assigns_source_ordered_spans_inside_the_source():
    source = MINIMAL_SOURCE

    sections, _ = segment(elements_of(source), source)

    previous_end = -1
    for section in sections:
        for block in section.blocks:
            assert block.source_pos is not None and block.end_pos is not None
            assert 0 <= block.source_pos < block.end_pos <= len(source)
            assert block.source_pos >= previous_end
            previous_end = block.end_pos


def test_segment_keeps_the_table_html_as_an_exact_source_slice():
    source = MINIMAL_SOURCE

    sections, _ = segment(elements_of(source), source)

    tables = [b for s in sections for b in s.blocks if b.kind == "table"]
    assert len(tables) == 1
    cited = source[tables[0].source_pos : tables[0].end_pos]
    assert "<TABLE" in cited and "300,870,903" in cited


def test_segment_keeps_the_part_heading_out_of_its_own_blocks():
    """The heading is the section's identity, so it is not also section content."""
    source = MINIMAL_SOURCE

    sections, _ = segment(elements_of(source), source)

    first = sections[0].blocks
    assert all(block.text != "I. 회사의 개요" for block in first)
    assert first[0].kind == "heading" and first[0].text == "1. 회사의 개요"
    assert all(block.level == 2 for block in first if block.kind == "heading")


def test_segment_warns_on_missing_core_parts():
    source = MINIMAL_SOURCE.replace("III. 재무에 관한 사항", "IV. 이사의 경영진단 및 분석의견")

    _, warnings = segment(elements_of(source), source)

    assert any("core part III" in warning for warning in warnings)


def test_segment_warns_on_out_of_order_parts():
    source = (
        MINIMAL_SOURCE.replace("I. 회사의 개요", "PARTSWAP")
        .replace("II. 사업의 내용", "I. 회사의 개요")
        .replace("PARTSWAP", "II. 사업의 내용")
    )

    sections, warnings = segment(elements_of(source), source)

    assert [section.part for section in sections] == ["II", "I", "III"]
    assert any("out of filing order" in warning for warning in warnings)


def test_segment_fails_closed_without_any_numbered_division():
    source = MINIMAL_SOURCE.replace("SECTION-1", "SECTION-9")

    with pytest.raises(DartParseError, match="no numbered top-level division"):
        segment(elements_of(source), source)


def test_segment_ignores_a_numbered_title_outside_a_section_boundary():
    """A table-group caption that happens to read like a part heading starts no section."""
    source = MINIMAL_SOURCE.replace("(단위: 백만원)", "IV. 이사의 경영진단 및 분석의견")

    sections, _ = segment(elements_of(source), source)

    assert [section.part for section in sections] == ["I", "II", "III"]


def test_segment_excludes_a_trailing_non_part_division():
    """A closing certification division belongs to no numbered part."""
    source = MINIMAL_SOURCE.replace(
        "</BODY>",
        "<SECTION-1><TITLE>【 전문가의 확인 】</TITLE><P>확인 내용 문단</P></SECTION-1></BODY>",
    )

    sections, _ = segment(elements_of(source), source)

    texts = [block.text for section in sections for block in section.blocks]
    assert "확인 내용 문단" not in texts
    assert all("전문가의 확인" not in text for text in texts)


# --- parse_dart_filing ---


def test_parse_dart_filing_maps_registry_identity_without_derivation(tmp_path):
    """fiscal_year comes from the manifest, not from the 2025 filing date."""
    path = write_source(tmp_path, MINIMAL_SOURCE)

    filing, profile = parse_dart_filing(entry_for(path, MINIMAL_SOURCE))

    assert filing.doc_id == "005930-FY2024"
    assert filing.registry == "dart"
    assert filing.issuer == "005930"
    assert filing.issuer_id == "00126380"
    assert filing.filing_id == "20250311001085"
    assert filing.form == "사업보고서"
    assert filing.filing_date == "2025-03-11"
    assert filing.fiscal_year == 2024
    assert filing.source_length == len(MINIMAL_SOURCE)
    assert filing.source_sha256 == hashlib.sha256(MINIMAL_SOURCE.encode()).hexdigest()
    assert filing.segment_type == "dart_part"
    assert filing.profile_used == "static"
    assert profile["segmentation"]["parts"] == list(DART_PARTS)


def test_parse_dart_filing_keeps_sec_vocabulary_out_of_sections(tmp_path):
    path = write_source(tmp_path, MINIMAL_SOURCE)

    filing, _ = parse_dart_filing(entry_for(path, MINIMAL_SOURCE))

    for section in filing.sections:
        assert "Item" not in section.canonical_title
        assert "Item" not in section.reported_title


def test_parse_dart_filing_rejects_a_foreign_registry(tmp_path):
    path = write_source(tmp_path, MINIMAL_SOURCE)
    entry = entry_for(path, MINIMAL_SOURCE) | {"registry": "sec"}

    with pytest.raises(DartParseError, match="not a DART filing"):
        parse_dart_filing(entry)


def test_parse_dart_filing_rejects_a_source_that_drifted_from_the_manifest(tmp_path):
    path = write_source(tmp_path, MINIMAL_SOURCE)
    entry = entry_for(path, MINIMAL_SOURCE) | {"source_sha256": "0" * 64}

    with pytest.raises(DartParseError, match="source digest"):
        parse_dart_filing(entry)


def test_parse_dart_filing_rejects_a_truncated_source(tmp_path):
    path = write_source(tmp_path, MINIMAL_SOURCE)
    entry = entry_for(path, MINIMAL_SOURCE) | {"source_length": len(MINIMAL_SOURCE) + 1}

    with pytest.raises(DartParseError, match="manifest records"):
        parse_dart_filing(entry)


def test_parse_dart_filing_rejects_a_non_utf8_archive(tmp_path):
    path = tmp_path / "20250311001085.xml"
    path.write_bytes(MINIMAL_SOURCE.encode("cp949"))

    with pytest.raises(DartParseError, match="not UTF-8"):
        parse_dart_filing(entry_for(path, MINIMAL_SOURCE))


def test_dart_doc_id_reads_issuer_and_fiscal_year():
    entry = json.loads('{"issuer": "000660", "fiscal_year": 2024}')

    assert dart_doc_id(entry) == "000660-FY2024"
