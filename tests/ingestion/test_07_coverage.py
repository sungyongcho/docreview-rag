"""최종확인② — 커버리지. **가장 중요한 지표다.**

개수·순서·중복 검증은 통째로 버려진 텍스트를 못 잡는다. 그리고 `expected_items`가
같은 측정에서 나오므로 부트스트랩 시 개수 검증은 **순환 논리**다.
커버리지는 "문서 전체 대비 섹션에 담긴 양"이라 그 순환 밖에 있다.

실제로 이 지표 하나가 `ix:header` 유입(B09)을 잡았다 — 그때 Item 개수·순서·중복은
**전부 완벽했다.**

문서: `docs/ko/m1-1-parser/05-verify.md`
"""

from bs4 import BeautifulSoup
import pytest

from tests.ingestion.golden import COVERAGE, COVERAGE_BAND, SEGMENT_TYPE


def measure(r) -> tuple[int, int]:
    """(문서 전체 문자수, 섹션에 담긴 문자수).

    분모를 `ParsedFiling`이 들고 나오므로 문서를 다시 파싱하지 않는다.
    실측 20개 기준 40초 → 18초 차이였다.
    """
    body = sum(len(b.text) for s in r.sections for b in s.blocks)
    tables = sum(
        len(BeautifulSoup(b.html, "html.parser").get_text(" ", strip=True))
        for s in r.sections
        for b in s.blocks
        if b.kind == "table" and b.html
    )
    return r.n_chars, body + tables


@pytest.mark.parametrize("doc", sorted(COVERAGE))
def test_coverage_matches_golden(doc, parsed):
    """문서별 (전체, 섹션합)이 골든값과 정확히 일치."""
    assert measure(parsed[doc]) == COVERAGE[doc]


@pytest.mark.parametrize("doc", sorted(COVERAGE))
def test_coverage_stays_inside_its_band(doc, parsed):
    """**하한도 상한도 있다.**

    하한 — 헤딩을 놓치면 그 뒤 구간이 통째로 사라져 급락한다.
    상한 — **100%는 목표가 아니다.** 표지·목차·서명은 SEC 기준으로 어느 Item에도
    속하지 않으므로 정상 상한이 96~98%다. 100%에 가까우면 오히려 표지가 Item 1에
    붙었다는 신호다. 지표는 "높을수록 좋다"가 아니라 "예상 구간 안에 있어야 한다".
    """
    total, covered = measure(parsed[doc])
    pct = covered / total * 100
    lo, hi = COVERAGE_BAND[SEGMENT_TYPE[doc]]
    assert lo <= pct <= hi, f"{doc}: 커버 {pct:.1f}% (기대 {lo}~{hi}%)"


def test_xref_runs_lower_than_number_by_design(parsed):
    """`xref`가 평균적으로 더 낮은 게 정상이다 — 버그가 아니라 문서 성격이다.

    Intel은 페이지마다 헤더를 넣어서(F11 "Table of Contents" 113회) 노이즈
    필터가 더 많이 걷어낸다.

    **구간은 겹친다.** 최저 number(NVDA-FY2020 95.67%)와 최고 xref
    (INTC-FY2020 95.74%)가 0.07pp 차이로 뒤집혀 있어서 "xref가 전부 더 낮다"는
    성립하지 않는다. 평균으로 봐야 한다(number ~97.2% vs xref ~94.9%).
    """

    def pct(doc):
        total, covered = measure(parsed[doc])
        return covered / total * 100

    number = [pct(d) for d, t in SEGMENT_TYPE.items() if t == "number"]
    xref = [pct(d) for d, t in SEGMENT_TYPE.items() if t == "xref"]
    assert sum(xref) / len(xref) + 1.0 < sum(number) / len(number), (
        "xref 평균이 number에 근접했다 — 노이즈 필터가 안 도는 것 아닌가"
    )


def test_n_chars_is_carried_not_recomputed(parsed, blocks_by_doc):
    """`n_chars`가 파싱 시점의 측정값 그대로여야 한다.

    분모를 결과에 담아 두는 게 이 필드의 존재 이유다. 여기가 어긋나면
    커버리지 숫자 전체의 의미가 없어진다.
    """
    for doc, r in parsed.items():
        _soup, blocks, _raw = blocks_by_doc[doc]
        assert r.n_chars == sum(len(b.get_text(" ", strip=True)) for b in blocks)
        assert r.n_blocks == len(blocks)
