"""7~8단계 — `xref` 페이지 조인.

Intel은 본문에 Item 헤딩이 아예 없다(F5). 대신 SEC가 재구성의 대가로 의무화한
Cross-Reference Index가 "내 어느 페이지가 어느 Item인가"를 표로 들고 있다(F6).
그 표와 기업 자체 목차를 **페이지로 조인**해서 경계를 긋는다.

문서 강의: `docs/ko/m1-1-parser/03-build.md` L8
"""

import pytest

from tests.ingestion.golden import XREF_ITEM_SHAPE, XREF_TABLES

INTC_DOCS = sorted(XREF_TABLES)


@pytest.fixture(scope="session")
def xref_tables(P, blocks_by_doc):
    """문서별 (색인표, 목차표). 표 탐색은 싸므로 세션당 한 번이면 충분하다."""
    from app.ingestion.xref import find_tables

    return {d: find_tables(blocks_by_doc[d][0]) for d in INTC_DOCS}


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_both_tables_are_found(doc, xref_tables):
    """색인표와 목차표가 둘 다 잡혀야 `xref`가 성립한다.

    하나라도 없으면 `detect_xref`가 `{}`를 반환하고 `undefined`로 떨어진다.
    """
    xref_tbl, toc_tbl = xref_tables[doc]
    assert xref_tbl is not None, f"{doc}: 색인표를 못 찾았다"
    assert toc_tbl is not None, f"{doc}: 목차표를 못 찾았다"


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_table_row_counts(doc, xref_tables):
    """색인표 엔트리 수와 목차 행 수가 골든값과 일치."""
    from app.ingestion.xref import parse_toc, parse_xref

    xref_tbl, toc_tbl = xref_tables[doc]
    assert (len(parse_xref(xref_tbl)), len(parse_toc(toc_tbl))) == XREF_TABLES[doc]


def test_open_row_absorption_stops_at_a_closed_item(xref_tables):
    """B01 — 자기 행에 값이 있는 Item은 아래 들여쓴 행을 흡수하지 않는다.

    무조건 흡수하면 표 끝의 "Signatures | Page 125"가 Item 16에 붙어,
    "Not applicable"인 Item 16이 본문 있는 것처럼 보인다.
    """
    from app.ingestion.xref import parse_xref

    entries = parse_xref(xref_tables["INTC-FY2022"][0])
    item16 = next((e for e in entries if e.item == "16"), None)
    if item16 is not None:
        assert item16.spans == [], "Item 16이 서명행의 페이지를 흡수했다"


def test_value_cell_is_the_third_one(xref_tables):
    """B02 — 값 셀은 3번째뿐이다.

    2셀 행(번호|제목)에서 제목을 값으로 읽으면 "Form 10-K Summary"의 **10**이
    페이지로 오독된다.
    """
    from app.ingestion.xref import parse_xref

    for doc in INTC_DOCS:
        for e in parse_xref(xref_tables[doc][0]):
            for lo, hi in e.spans:
                assert 1 <= lo <= hi <= 400, f"{doc} Item {e.item}: 말이 안 되는 페이지 {(lo, hi)}"


def test_status_is_decided_by_page_spans(xref_tables):
    """B03 — 최종 status 판정은 **페이지 구간 유무**로 한다.

    하위행의 참조기호(`(a)`)가 상위 Item의 status를 오염시켜 배정 후보에서
    빼버린 사고가 있었다(FY2019·2020 Item 7 실종). 구간이 있으면 본문이
    실재하는 Item이다.
    """
    from app.ingestion.xref import parse_xref

    for doc in INTC_DOCS:
        for e in parse_xref(xref_tables[doc][0]):
            if e.spans:
                assert e.status == "parsed", f"{doc} Item {e.item}: 페이지가 있는데 {e.status}"


def test_covering_picks_the_narrowest_span():
    """`XrefEntry.covering` — 이 페이지를 덮는 구간 중 가장 좁은 것.

    배정 우선순위(제목 겹침 → 구간 좁은 순 → 번호 짧은 순)의 두 번째 축이다.
    """
    from app.ingestion.xref import XrefEntry

    e = XrefEntry(
        item="7", reported_title="MD&A", spans=[(5, 6), (19, 44), (40, 41)], status="parsed"
    )
    assert e.covering(41) == (40, 41)  # (19,44)보다 좁다
    assert e.covering(20) == (19, 44)
    assert e.covering(100) is None


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_item_7_is_joined_from_many_narrative_sections(doc, parsed):
    """F7 — Item 하나 = 서사 섹션 여러 개.

    INTC FY2022 Item 7 = Pages 5-6, 19-44, 47-51 → 서사 섹션 8개가 하나로 합쳐진다.
    조인이 안 되면 10k대로 떨어진다.

    ⚠ FY2019만 33k로 작은데 **버그가 아니다.** Intel 자체 색인표가 그 해엔
    "Our Products"(p17)를 Item 7이 아니라 Item 1에 배정했고, 실제로 FY2019는
    Item 1이 다른 해보다 크다. 총량이 보존되고 우리는 문서가 말하는 대로 따랐다.
    """
    expected_chars, expected_tables = XREF_ITEM_SHAPE[doc]
    s7 = next(s for s in parsed[doc].sections if s.item == "7")
    assert sum(len(b.text) for b in s7.blocks) == expected_chars


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_financial_statements_land_in_item_8(doc, parsed):
    """B06 — 재무제표가 Item 8에 귀속됐나.

    Intel은 일부 헤딩이 이미지라 본문 텍스트에 없다(F8). 그러면 다음 앵커가
    멀리 밀려 재무제표 8페이지가 Item 9B에 통째로 흡수된다. 페이지 footer로
    경계를 보정해야 여기 표가 제대로 들어온다.

    ⚠ FY2019는 구식 파일이라 표블록 자체가 18개뿐이다(다른 해는 95~133).
    그래서 단일 하한("표 50개 이상")을 쓸 수 없고 연도별 골든값을 쓴다.
    """
    _chars, expected_tables = XREF_ITEM_SHAPE[doc]
    s8 = next(s for s in parsed[doc].sections if s.item == "8")
    assert sum(1 for b in s8.blocks if b.kind == "table") == expected_tables


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_item_3_is_found_by_the_second_sweep(doc, parsed):
    """**Item 3은 2차 수색으로만 잡힌다.**

    "Legal Proceedings"는 재무제표 주석 안에 있어 기업 목차에 없지만 본문에
    헤딩이 실존한다. 목차 조인만으로는 안 나오고, "목차엔 없지만 색인표에
    페이지가 있는 Item"을 본문 제목 검색으로 찾아야 한다.
    """
    s3 = next((s for s in parsed[doc].sections if s.item == "3"), None)
    assert s3 is not None, "Item 3이 없다 — 2차 수색이 동작하지 않는다"
    assert sum(len(b.text) for b in s3.blocks) > 5_000


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_part_iii_is_incorporated_by_reference(doc, parsed):
    """Part III(10~14)는 proxy로 위임된다 — 색인표가 `(a)`~`(e)` 각주로 알려준다.

    제목·번호 기반 타입은 본문 텍스트로 **추정**하지만, `xref`는 색인표가
    **직접 알려주는 사실**이다. 그래서 근거를 갖고 답할 수 있다.
    """
    by_item = {s.item: s for s in parsed[doc].sections}
    referenced = [
        i
        for i in ("10", "11", "12", "13", "14")
        if i in by_item and by_item[i].status == "incorporated_by_reference"
    ]
    assert len(referenced) >= 4, f"{doc}: Part III 참조 처리가 {referenced}뿐"


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_page_footers_and_repeated_headers_are_stripped(doc, parsed):
    """본문 조립 시 노이즈 제거 — 페이지 번호와 반복 페이지 헤더.

    F11 — 진짜 헤딩은 문서에 한 번, 가짜는 반복된다. INTC FY2022의
    "Table of Contents"는 113회 나온다. 이게 남으면 청크가 오염된다.
    """
    texts = [b.text for s in parsed[doc].sections for b in s.blocks if b.kind == "paragraph"]
    assert sum(1 for t in texts if t.strip() == "Table of Contents") == 0
    assert sum(1 for t in texts if t.strip().isdigit() and len(t.strip()) <= 3) == 0


@pytest.mark.parametrize("doc", INTC_DOCS)
def test_no_block_is_emitted_twice(doc, P, blocks_by_doc, parsed):
    """**한 블록은 한 Item에만 들어간다.**

    Item의 페이지 구간이 겹칠 수 있으므로 명시적으로 확인해야 한다. 배정이
    이중으로 되면 같은 문단이 두 청크에 실려 검색 결과가 오염된다.

    주의 — "같은 **텍스트**가 두 Item에 있으면 안 된다"로 검사하면 안 된다.
    INTC-FY2020은 실효세율 문단을 MD&A(블록 933)와 재무제표 주석(블록 1709)에
    **원문이 두 번 싣는다.** 둘 다 올바른 배정이다. 불변식은 텍스트가 아니라
    블록 단위로 세워야 한다.
    """
    from collections import Counter
    import re

    from app.ingestion.xref import _in_tables, find_tables

    soup, blocks, _raw = blocks_by_doc[doc]
    xref_tbl, toc_tbl = find_tables(soup)
    skip = _in_tables(blocks, [xref_tbl, toc_tbl])
    freq = Counter(b.get_text(" ", strip=True) for b in blocks)

    eligible = sum(
        1
        for j, b in enumerate(blocks)
        if j not in skip
        and (t := b.get_text(" ", strip=True))
        and not re.fullmatch(r"\d{1,3}", t)  # 페이지 footer
        and not (len(t) < 60 and freq[t] >= 10)  # 반복 페이지 헤더 (F11)
    )
    emitted = sum(len(s.blocks) for s in parsed[doc].sections)
    assert emitted <= eligible, f"{doc}: {emitted - eligible}개 블록이 중복 적재됐다"
