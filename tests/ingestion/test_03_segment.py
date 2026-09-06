"""4단계 + 최종확인① — 판별과 세그멘테이션.

문서 강의: `docs/ko/m1-1-parser/03-build.md` L7(헤딩 순회) · L9(판별 캐스케이드)
"""

from collections import Counter

import pytest

from tests.ingestion.golden import N_ITEMS, PROFILE_RULES, SEGMENT_TYPE
from tests.support import need


def test_segment_type_per_document(parsed):
    """최종확인① — 20문서의 타입이 골든값과 일치."""
    assert {d: r.segment_type for d, r in parsed.items()} == SEGMENT_TYPE


def test_aggregate_is_15_number_5_xref(parsed):
    """집계: {'number': 15, 'xref': 5}."""
    assert Counter(r.segment_type for r in parsed.values()) == {"number": 15, "xref": 5}


def test_everything_parses_without_warnings(parsed):
    """20/20이 경고 없이 파싱된다. 하나라도 깨지면 여기서 문서 이름이 나온다."""
    failed = {d: r.warnings for d, r in parsed.items() if r.parse_status != "parsed"}
    assert failed == {}


def test_item_counts(parsed):
    """Item 개수. 연도가 오르며 20→23으로 느는 게 정상(1C 2023 신설, 9C 2021)."""
    assert {d: len([s for s in r.sections if s.item]) for d, r in parsed.items()} == N_ITEMS


@pytest.mark.parametrize("doc", sorted(N_ITEMS))
def test_no_duplicate_items(doc, parsed):
    """같은 Item이 두 번 나오면 규칙이 느슨한 것이다."""
    items = [s.item for s in parsed[doc].sections if s.item]
    assert len(items) == len(set(items)), (
        f"{doc} 중복: {sorted(i for i in items if items.count(i) > 1)}"
    )


@pytest.mark.parametrize(
    "doc", ["INTC-FY2019", "INTC-FY2020", "INTC-FY2021", "INTC-FY2022", "INTC-FY2023"]
)
def test_detect_number_must_fail_on_intel(doc, P, blocks_by_doc):
    """`detect_number` must fail on all five Intel filings.

    Intel has no leaf-block Item heading candidates. A successful number strategy
    would therefore mean that layout or index content was mistaken for a heading.
    """
    need(P, "detect_number")
    _soup, blocks, _raw = blocks_by_doc[doc]
    assert P.detect_number(blocks) == {}


def test_detect_number_succeeds_on_the_other_fifteen(P, blocks_by_doc):
    """반대로 나머지 15개는 성공해야 한다 — 실패 테스트만 있으면 통과가 공짜다."""
    need(P, "detect_number")
    for doc, (_soup, blocks, _raw) in blocks_by_doc.items():
        if doc.startswith("INTC"):
            continue
        assert P.detect_number(blocks).get("type") == "number", f"{doc} 판별 실패"


def test_intel_fails_for_lack_of_candidates_not_toc_density(P, blocks_by_doc):
    """Pin the real reason Intel fails the numbered-heading strategy.

    The cross-reference index is absorbed as one table block, so none of its cells
    become leaf-block Item candidates. The strategy exits for too few candidates
    before the dormant TOC-density guard matters, which is why xref is required.
    """
    need(P, "ITEM_RE")
    _soup, blocks, _raw = blocks_by_doc["INTC-FY2022"]
    cands = [
        b
        for b in blocks
        if (t := b.get_text(" ", strip=True)) and len(t) < 300 and P.ITEM_RE.match(t)
    ]
    assert cands == []


def test_toc_detector_is_a_dormant_guard(P, blocks_by_doc):
    """`_looks_like_toc` — 이 코퍼스에서는 **한 번도 발화하지 않는다.**

    표 안까지 허용할 때(AMD FY2019, F4) 목차 표를 잡지 않도록 두는 방어책인데,
    AMD의 Item 후보 21개는 5,220블록에 걸쳐 퍼져 있어 밀집 임계(문서의 15% =
    826블록)에 한참 못 미친다. **발화하지 않는다는 사실 자체를 고정해둔다** —
    나중에 여기가 True로 바뀌면 블록화나 임계가 달라졌다는 신호다.
    """
    need(P, "_looks_like_toc")
    for doc, (_soup, blocks, _raw) in blocks_by_doc.items():
        assert P._looks_like_toc(blocks) is False, f"{doc}에서 목차 판정이 발화했다"


def test_toc_detector_fires_on_a_dense_index(P):
    """다만 진짜 조밀한 목차를 주면 발화해야 한다 — 죽은 코드가 아니라는 확인.

    목차는 항목 사이에 본문이 없어 좁은 구간에 몰린다. 본문 헤딩은 사이사이에
    수만 자가 들어가 문서 전체에 퍼진다. 그 차이를 밀집도로 잡는다.
    """
    need(P, "_looks_like_toc", "normalize", "leaf_blocks")
    items = "".join(f"<p>Item {n}. Something</p>" for n in range(1, 17))
    padding = "<p>본문</p>" * 200  # 목차 뒤로 문서가 길게 이어진다
    blocks = P.leaf_blocks(P.normalize(f"<html><body>{items}{padding}</body></html>"))
    assert P._looks_like_toc(blocks) is True


def test_learned_rules_match_golden(parsed, profiles_dir):
    """학습된 스타일 규칙. **AMD-FY2019만 `in_table: true`인 게 F4의 증거다.**

    사람이 손대지 않아도 "표 밖에서 15개 미만이면 표 안까지" 규칙으로 자동 전환된다.
    """
    import json

    for ticker, years in PROFILE_RULES.items():
        data = json.loads((profiles_dir / f"{ticker}.json").read_text())
        for year, (weight, size, in_table) in years.items():
            rule = data["profiles"][year]["segmentation"]["rules"][0]
            assert (rule["font_weight"], rule["font_size"], rule["in_table"]) == (
                weight,
                size,
                in_table,
            ), f"{ticker}-{year}"


def test_headings_are_found_by_style_plus_number(P, blocks_by_doc):
    """3단계 스니펫의 자동화 — NVDA-FY2024에 규칙을 걸면 정확히 23개가 남는다.

    "Item 1A"는 문서에 5번 나오지만(F2) 4번은 문장 중간 상호참조라 `^`에서,
    목차는 표 안이라 `in_table: false`에서 탈락한다. 남는 게 정확히 하나씩이다.
    """
    need(P, "matches_any", "ITEM_RE")
    _soup, blocks, _raw = blocks_by_doc["NVDA-FY2024"]
    rule = [{"font_weight": 700, "font_size": 10.0, "in_table": False}]
    hits = [
        t
        for b in blocks
        if (t := b.get_text(" ", strip=True))
        and len(t) < 300
        and P.ITEM_RE.match(t)
        and P.matches_any(b, rule)
    ]
    assert len(hits) == 23
    assert hits[0].startswith("Item 1.")
    assert hits[1].startswith("Item 1A.")


def test_cover_page_and_toc_are_dropped(parsed):
    """첫 헤딩 이전(표지·목차)은 버려진다 — 의도된 동작이다.

    커버리지가 100%가 아닌 이유의 대부분이 이것이고, SEC 기준으로 그 구간은
    어느 Item에도 속하지 않는다. 100%가 나오면 오히려 표지가 Item 1에 붙은 것이다.
    """
    r = parsed["NVDA-FY2024"]
    first = r.sections[0]
    assert first.item == "1"
    assert first.block_index is not None and first.block_index > 0, (
        "첫 섹션이 0번 블록에서 시작하면 표지를 삼킨 것이다"
    )
    body = " ".join(b.text for b in first.blocks[:3])
    assert "Securities registered pursuant" not in body, "표지 문구가 Item 1에 들어왔다"
