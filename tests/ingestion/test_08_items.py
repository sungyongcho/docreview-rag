"""최종확인③ — 경계 정확도. SEC가 정한 Item 목록과 대조한다.

**커버리지는 헤딩 누락을 못 잡는다.** 놓친 헤딩의 내용이 앞 섹션에 흡수되어
총량이 그대로이기 때문이다:

    정상:    [Item 7 본문 30k][Item 7A 본문 3k]   → 커버 96%
    7A 놓침: [Item 7 본문 33k          ........]  → 커버 96%   ← 똑같다

그래서 **외부 기준**(SEC가 정한 Item 목록)과 맞춰야 한다. `expected_items`가
파서 자신의 측정에서 나오는 것과 달리 이건 순환하지 않는다.

문서: `docs/ko/m1-1-parser/05-verify.md`
"""

import pytest

from tests.ingestion.golden import ALWAYS_OPTIONAL, N_ITEMS


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_no_extra_items(doc, P, parsed):
    """과잉이 하나라도 나오면 헤딩 오탐이다."""
    got = [s.item for s in parsed[doc].sections if s.item]
    assert [i for i in got if i not in P.ORDER] == []


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_missing_items_are_only_the_optional_ones(doc, P, parsed):
    """누락은 전부 "그 해에 없던 Item"이어야 한다.

        1C Cybersecurity          SEC 2023 신설  → FY2022 이전엔 없음
        9C Foreign Jurisdictions  HFCAA 2021     → FY2020 이전엔 없음
        16 Form 10-K Summary      선택 항목      → 언제든

    이 셋 외의 누락이 나오면 헤딩을 놓친 것이다.
    """
    got = {s.item for s in parsed[doc].sections if s.item}
    missing = [i for i in P.ORDER if i not in got]
    assert set(missing) <= ALWAYS_OPTIONAL, (
        f"{doc}: 설명 안 되는 누락 {sorted(set(missing) - ALWAYS_OPTIONAL)}"
    )


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_new_items_appear_only_after_they_existed(doc, parsed):
    """반대 방향 — 생기기 전 연도에 있으면 그것도 오탐이다."""
    year = int(doc.split("FY")[1])
    got = {s.item for s in parsed[doc].sections if s.item}
    if year <= 2022:
        assert "1C" not in got, "1C는 2023 신설인데 그 전에 나왔다"
    if year <= 2020:
        assert "9C" not in got, "9C는 2021 신설인데 그 전에 나왔다"


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_core_items_have_real_content(doc, parsed):
    """핵심 Item 넷은 내용이 있어야 한다.

    구조가 완벽해도 내용이 없으면 목차를 헤딩으로 잡은 것이다(B10).
    단 NVDA의 Item 8처럼 재무제표를 Item 15에 싣는 편집은 정상이므로,
    `status`가 `parsed`인 것만 따진다.
    """
    for s in parsed[doc].sections:
        if s.item in ("1", "1A", "7", "8") and s.status == "parsed":
            assert len(s.blocks) >= 20, f"{doc} Item {s.item}: 블록 {len(s.blocks)}개뿐"


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_sections_carry_their_position(doc, parsed):
    """위치를 안 들고 있으면 검증이 불가능하다.

    파서의 일이 "Item 헤딩이 **어디** 있나"인데, 출력에 위치가 없으면
    "찾았다"는 주장을 확인할 방법이 없다. F15 — `lxml`은 위치를 안 채우므로
    여기가 None이면 파서를 잘못 고른 것이다(B17).
    """
    for s in parsed[doc].sections:
        if s.status != "parsed" or not s.blocks:
            continue
        assert s.block_index is not None, f"{doc} Item {s.item}: block_index 없음"
        assert s.source_pos is not None, f"{doc} Item {s.item}: source_pos 없음"
        assert s.block_range is not None


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_every_section_has_its_canonical_title(doc, P, parsed):
    """`canonical_title`은 세그먼트 타입과 무관하게 모든 타입에서 채워진다.

    타입 이름이 `canonical_title`이 아니라 `sec_canonical`인 이유가 이 혼동 차단이다 —
    `sec_canonical`은 *그 제목을 매칭에 쓴다*는 뜻이지, 그 타입에서만
    `canonical_title`이 채워진다는 뜻이 아니다.
    """
    for s in parsed[doc].sections:
        if s.item:
            assert s.canonical_title == P.CANONICAL[s.item]
            assert s.part == P.PART_OF[s.item]


def test_items_stay_in_sec_order_for_heading_types(P, parsed):
    """`number` 타입은 문서 순서가 SEC 표준 순서와 같아야 한다.

    `xref`는 제외한다 — Item이 문서 곳곳에 흩어져 있는 게 정상이라 순서가
    무의미하다(F7). 검증 기준이 타입마다 다른 이유가 이것이다.
    """
    rank = {v: i for i, v in enumerate(P.ORDER)}
    for doc, r in parsed.items():
        if r.segment_type != "number":
            continue
        items = [s.item for s in r.sections if s.item]
        assert items == sorted(items, key=lambda i: rank[i]), f"{doc} 순서 어긋남"
