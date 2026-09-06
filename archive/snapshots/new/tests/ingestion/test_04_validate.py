"""5단계 — `validate` + `classify_sections`.

graceful degradation의 핵심은 폴백이 아니라 **실패 감지**다. 틀렸는지 모르면
폴백할 기회조차 없다. 그래서 여기서는 "정상이 통과한다"보다 **"고장이 잡힌다"**를
더 많이 단언한다.

앞부분은 코퍼스가 필요 없다.
문서 강의: `docs/ko/m1-1-parser/03-build.md` L10(상태 분류) · L12(검증)
"""

import pytest

from tests.ingestion.golden import NVDA_FY2024_ITEM15_MIN_CHARS, STATUS_NVDA_FY2024
from tests.support import need

NUMBER_PROFILE = {
    "segmentation": {"type": "number"},
    "validation": {"expected_items": 23, "must_have": ["1", "1A", "7", "8"]},
}


def make_sections(P, items, blocks_each=30):
    """검증에 넣을 최소 섹션들. 본문이 있어야 '목차로 보임'에 안 걸린다."""
    return [
        P.Section(
            part=P.PART_OF.get(i),
            item=i,
            canonical_title=P.CANONICAL.get(i, ""),
            reported_title="",
            blocks=[P.Block("paragraph", "본문") for _ in range(blocks_each)],
        )
        for i in items
    ]


def test_validate_returns_a_list_not_an_exception(P):
    """문제를 예외가 아니라 리스트로 모은다.

    `raise`하면 첫 문제에서 멈춰 나머지를 못 본다. 리스트면 로그 한 줄에 전부
    나오고, 호출부는 `if problems:` 하나로 "재학습해야 하나"를 판단한다.
    """
    need(P, "validate")
    problems = P.validate(make_sections(P, ["1", "1A"]), NUMBER_PROFILE)
    assert isinstance(problems, list)
    assert len(problems) >= 2, "문제 여러 개가 한 번에 모여야 한다"


def test_validate_catches_count_and_missing_core(P):
    """5단계 스니펫의 자동화 — 개수 부족과 핵심 Item 누락이 동시에 잡힌다."""
    need(P, "validate")
    problems = " ".join(P.validate(make_sections(P, ["1", "1A"]), NUMBER_PROFILE))
    assert "2" in problems and "23" in problems, "개수 불일치를 못 잡았다"
    assert "7" in problems and "8" in problems, "핵심 item 누락을 못 잡았다"


def test_validate_catches_duplicates(P):
    """같은 Item이 두 번 나오면 규칙이 느슨한 것이다."""
    need(P, "validate")
    prof = {**NUMBER_PROFILE, "validation": {**NUMBER_PROFILE["validation"], "expected_items": 5}}
    problems = P.validate(make_sections(P, ["1", "1A", "1A", "7", "8"]), prof)
    assert any("1A" in p for p in problems)


def test_validate_catches_wrong_order(P):
    """순서 — SEC 표준 순서에서 벗어나면 경계가 밀린 것이다."""
    need(P, "validate")
    prof = {**NUMBER_PROFILE, "validation": {**NUMBER_PROFILE["validation"], "expected_items": 4}}
    ok = P.validate(make_sections(P, ["1", "1A", "7", "8"]), prof)
    bad = P.validate(make_sections(P, ["7", "1", "1A", "8"]), prof)
    assert ok == []
    assert bad != [], "뒤집힌 순서를 통과시켰다"


def test_validate_catches_a_perfect_structure_with_no_content(P):
    """**구조 검사만으로는 부족하다.** 목차를 헤딩으로 잡으면 개수·순서·중복이
    전부 완벽한데 각 섹션에 내용이 없다.

    이 검사 하나가 실제로 "21개 섹션 전원 blocks=2" 사고(B10)를 잡았다.
    """
    need(P, "validate")
    items = list(P.CANONICAL)[:23]
    prof = {
        **NUMBER_PROFILE,
        "validation": {"expected_items": 23, "must_have": ["1", "1A", "7", "8"]},
    }

    fat = P.validate(make_sections(P, items, blocks_each=30), prof)
    thin = P.validate(make_sections(P, items, blocks_each=2), prof)

    assert fat == [], f"정상 입력이 실패했다: {fat}"
    assert thin != [], "본문 없는 섹션 23개를 통과시켰다 — 목차를 헤딩으로 잡아도 못 잡는다"


def test_classify_empty_disclosure(P):
    """짧은 섹션은 대부분 버그가 아니라 정상 공시다."""
    need(P, "classify_sections")
    for text in ("None.", "Not applicable.", "N/A", "none"):
        s = P.Section(
            part=None,
            item="4",
            canonical_title="",
            reported_title="",
            blocks=[P.Block("paragraph", text)],
        )
        P.classify_sections([s])
        assert s.status == "empty_disclosure", f"{text!r}를 못 잡았다"


def test_classify_incorporated_by_reference(P):
    """Proxy 등 외부 문서로 위임한 섹션."""
    need(P, "classify_sections")
    s = P.Section(
        part=None,
        item="11",
        canonical_title="",
        reported_title="",
        blocks=[
            P.Block(
                "paragraph",
                "The information required by this Item is "
                "incorporated herein by reference to the Proxy Statement.",
            )
        ],
    )
    P.classify_sections([s])
    assert s.status == "incorporated_by_reference"


def test_classify_leaves_real_content_alone(P):
    """긴 본문은 건드리지 않는다 — 오분류가 더 위험하다."""
    need(P, "classify_sections")
    s = P.Section(
        part=None,
        item="1",
        canonical_title="",
        reported_title="",
        blocks=[P.Block("paragraph", "NVIDIA pioneered accelerated computing. " * 40)],
    )
    P.classify_sections([s])
    assert s.status == "parsed"


# ── 여기부터 코퍼스 필요


@pytest.mark.parametrize("item,expected", sorted(STATUS_NVDA_FY2024.items()))
def test_nvda_statuses(item, expected, parsed):
    """NVDA-FY2024의 비-`parsed` 섹션이 골든값과 일치.

    NVDA는 재무제표를 Item 15 아래에 싣기 때문에 Item 8이 참조가 된다 —
    "Item 8이 154자뿐"은 버그가 아니라 이 회사의 편집 방식이다.
    """
    sec = next(s for s in parsed["NVDA-FY2024"].sections if s.item == item)
    assert sec.status == expected


def test_nvda_item15_is_the_fat_one(parsed):
    """위의 귀결 — Item 8이 얇으면 Item 15가 두꺼워야 앞뒤가 맞는다."""
    s15 = next(s for s in parsed["NVDA-FY2024"].sections if s.item == "15")
    assert sum(len(b.text) for b in s15.blocks) > NVDA_FY2024_ITEM15_MIN_CHARS
    assert sum(1 for b in s15.blocks if b.kind == "table") > 30
