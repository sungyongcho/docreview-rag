"""1~2단계 — `normalize` + `leaf_blocks`.

문서 강의: `docs/ko/m1-1-parser/03-build.md` L2·L3
"""

import pytest

from tests.ingestion.golden import BLOCKS, LEGACY_FILES
from tests.support import need


def test_block_counts(P, blocks_by_doc):
    """20문서의 블록 수·표블록 수·문서 표 수가 골든값과 일치."""
    actual = {
        d: (len(blocks), sum(1 for b in blocks if b.name == "table"), len(soup.find_all("table")))
        for d, (soup, blocks, _raw) in blocks_by_doc.items()
    }
    assert actual == BLOCKS


@pytest.mark.parametrize("doc", sorted(BLOCKS))
def test_no_document_loses_its_tables(doc, blocks_by_doc):
    """표블록이 0인 파일이 하나도 없다.

    B04 — 구식 파일은 표 셀마다 <div>를 넣어서 "내부 블록 없는 요소만 리프"
    규칙으로는 표가 리프가 아니게 되고, 재무제표가 셀 단위 문단으로 부서진다.
    그때 이 값이 0이 된다.
    """
    _soup, blocks, _raw = blocks_by_doc[doc]
    assert sum(1 for b in blocks if b.name == "table") > 0


def test_ix_header_is_dropped_not_unwrapped(P, blocks_by_doc):
    """B09 — `ix:header`는 unwrap이 아니라 decompose여야 한다.

    iXBRL 규격상 렌더링되지 않는 기계용 영역인데 안에 XBRL 컨텍스트 정의가
    들어 있다. unwrap하면 `xbrli:*`/`xbrldi:*` 자식이 살아남아 본문 첫 블록에
    수만 자짜리 쓰레기로 뭉친다(MU-FY2024 34,148자 / INTC-FY2019 59,005자).

    이 버그는 Item 개수·순서·중복 검증을 **전부 통과했다.** 커버리지를 재고 나서야
    드러났다 — 그래서 여기서 직접 막는다.
    """
    need(P, "normalize")
    for doc in ("MU-FY2024", "INTC-FY2019"):
        soup, blocks, _raw = blocks_by_doc[doc]
        assert soup.find("ix:header") is None, f"{doc}: ix:header가 트리에 남아 있다"
        head = " ".join(b.get_text(" ", strip=True) for b in blocks[:5])
        assert "xbrli" not in head and "explicitMember" not in head, (
            f"{doc}: 첫 블록에 XBRL 컨텍스트가 유입됐다"
        )


def test_ixbrl_numbers_survive(P):
    """F10 — `ix:*`는 벗기되(unwrap) 지우면(decompose) 안 된다.

    iXBRL이 재무 수치마다 태그를 감싸므로, 지우면 숫자가 통째로 증발한다.
    """
    need(P, "normalize")
    soup = P.normalize(
        "<html><body><div>매출 <ix:nonFraction>26,974</ix:nonFraction> 백만</div></body></html>"
    )
    assert "26,974" in soup.get_text()


def test_legacy_files_have_far_more_blocks(blocks_by_doc):
    """구식 파일 3개가 같은 회사의 다른 해보다 블록이 훨씬 많다 — 정상이다.

    껍데기 div가 많을 뿐이라, 여기서 블록이 적게 나오면 오히려 표를 통째로
    삼키고 있다는 신호다.
    """
    for doc in LEGACY_FILES:
        ticker = doc.split("-")[0]
        peers = [
            len(b)
            for d, (_s, b, _r) in blocks_by_doc.items()
            if d.startswith(ticker) and d not in LEGACY_FILES
        ]
        assert len(blocks_by_doc[doc][1]) > 2 * max(peers), f"{doc}가 구식 파일 특성을 안 보인다"
