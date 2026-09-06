"""3단계 — 규칙 평가기 `matches_rule` / `matches_any`.

**코퍼스가 필요 없다.** `parser_mine.py`를 짜기 시작한 직후부터 바로 켜진다.

평가 규약(`docs/ko/m1-1-parser/02-spec.md`):
    안 적은 key   → 제약 없음
    수치         → **이상** (font_size: 14 = 14pt 미만 탈락)
    불리언·문자열 → 일치
    in_table     → false=표 밖만, true=제약 없음 (**비대칭**)
    리스트 전체   → 하나라도 통과하면 헤딩
"""

from bs4 import BeautifulSoup
import pytest

from tests.support import need


def tag(html: str):
    """스니펫 하나에서 첫 요소를 꺼낸다."""
    return BeautifulSoup(html, "html.parser").find(True)


BOLD_10PT = 'style="font-weight:700;font-size:10.0pt;text-align:center"'


@pytest.fixture
def bold():
    return tag(f"<div {BOLD_10PT}>Item 1. Business</div>")


@pytest.fixture
def plain():
    return tag('<div style="font-weight:400;font-size:9.0pt">본문 문단</div>')


def test_unlisted_key_is_unconstrained(P, bold):
    """규약1 — 규칙에 안 적은 속성은 아무 제약도 걸지 않는다."""
    need(P, "matches_rule")
    assert P.matches_rule(bold, {"font_weight": 700}) is True


def test_unknown_key_is_ignored(P, bold):
    """`props`에 없는 key는 조용히 무시된다.

    프로파일 오타(`font_wieght`)에 죽지 않는 대신 오타를 못 잡는다는 뜻이기도 하다.
    """
    need(P, "matches_rule")
    assert P.matches_rule(bold, {"font_wieght": 700}) is True


def test_numeric_is_a_minimum_not_equality(P, bold):
    """규약2 — 수치는 '이상'이다. 학습이 min()으로 규칙을 뽑는 것과 짝을 이룬다."""
    need(P, "matches_rule")
    assert P.matches_rule(bold, {"font_size": 9.0}) is True  # 10 >= 9
    assert P.matches_rule(bold, {"font_size": 10.0}) is True  # 경계 포함
    assert P.matches_rule(bold, {"font_size": 11.0}) is False  # 10 < 11


def test_string_is_equality(P, bold):
    """규약3 — 문자열은 일치."""
    need(P, "matches_rule")
    assert P.matches_rule(bold, {"text_align": "center"}) is True
    assert P.matches_rule(bold, {"text_align": "left"}) is False


def test_in_table_is_asymmetric(P):
    """규약4 — `in_table`의 비대칭. **AMD FY2019(F4) 때문에 필요하다.**

    false = 표 밖만 허용, true = 제약 없음(표 안팎 모두).
    true를 "반드시 표 안"으로 해석하면 표 밖 헤딩이 전부 탈락한다.
    """
    need(P, "matches_rule")
    outside = tag(f"<div {BOLD_10PT}>Item 1</div>")
    inside = BeautifulSoup(
        f"<table><tr><td><div {BOLD_10PT}>Item 1</div></td></tr></table>", "html.parser"
    ).find("div")

    assert P.matches_rule(outside, {"in_table": False}) is True
    assert P.matches_rule(inside, {"in_table": False}) is False  # 표 안은 탈락
    assert P.matches_rule(outside, {"in_table": True}) is True  # ★true는 제약 없음
    assert P.matches_rule(inside, {"in_table": True}) is True


def test_bool_is_checked_before_numeric(P):
    """B12 — 파이썬에서 `bool`은 `int`의 서브클래스라 `isinstance(True, int)`가 True다.

    수치 검사가 불리언 검사보다 앞에 오면 `in_table: True`가 "1 이상"으로,
    `in_table: False`가 "0 이상"(= 항상 통과)으로 해석된다. 그러면 표 안 헤딩이
    전부 통과해 히트 수가 수십~수백 개로 폭증한다.

    `in_table`은 자체 분기가 있으니 다른 불리언 속성으로 순서를 검증한다.
    """
    need(P, "matches_rule", "block_props")
    el = tag(f"<div {BOLD_10PT}>Item 1</div>")
    props = P.block_props(el)
    assert props["in_table"] is False, "in_table은 진짜 bool이어야 한다"
    # font_weight 700에 대해 True(=1)를 요구하면, 수치 규약이면 통과(700>=1)하고
    # 불리언 규약이면 탈락(700 != True)한다. 불리언이 먼저여야 한다.
    assert P.matches_rule(el, {"font_weight": True}) is False


def test_bold_keyword_normalizes_to_700(P):
    """`font-weight: bold`와 `700`이 같은 값이어야 한다.

    정규화를 아래층(block_props)에서 끝내야 위층 규칙이 단순해진다.
    """
    need(P, "block_props")
    assert P.block_props(tag('<div style="font-weight:bold">x</div>'))["font_weight"] == 700
    assert P.block_props(tag('<div style="font-weight:700">x</div>'))["font_weight"] == 700


def test_missing_style_defaults_to_400(P):
    """style이 없으면 굵기 400 — 헤딩 규칙(700 이상)에서 탈락해야 한다."""
    need(P, "block_props")
    assert P.block_props(tag("<div>x</div>"))["font_weight"] == 400


def test_inline_css_reaches_inner_spans(P):
    """스타일이 안쪽 span에 붙어 있어도 읽어야 한다.

    10-K는 시맨틱 태그가 없고(F1) 스타일이 div/span에 흩어져 있다.
    `_inline_css`가 el의 style + 안쪽 span 2개까지 합친다.
    """
    need(P, "block_props")
    el = tag('<div><span style="font-weight:700;font-size:14.0pt">RISK FACTORS</span></div>')
    props = P.block_props(el)
    assert props["font_weight"] == 700
    assert props["font_size"] == 14.0


def test_matches_any_is_or(P, bold, plain):
    """규약5 — `rules`는 배열이고 하나라도 통과하면 헤딩이다.

    회사가 헤딩을 여러 형식으로 쓸 수 있어서 필요하다.
    """
    need(P, "matches_any")
    rules = [{"font_size": 99.0}, {"font_weight": 700}]  # 앞은 실패, 뒤는 성공
    assert P.matches_any(bold, rules) is True
    assert P.matches_any(plain, rules) is False
    assert P.matches_any(bold, []) is False  # 빈 배열은 통과할 수 없다


def test_item_regex_anchors_and_prefers_long_alternation(P):
    """`ITEM_RE` 두 가지 설계.

    ① `^` 앵커 — 본문 중간의 "see Item 1A"를 걸러낸다 (F2).
    ② `1[0-6]|[1-9]` 순서 — 교대는 왼쪽 우선이라 긴 패턴이 먼저여야 한다.
       뒤집으면 "Item 15"에서 `1`만 먹고 멈춘다.
    """
    need(P, "ITEM_RE")

    def item_of(text):
        m = P.ITEM_RE.match(text)
        return (m.group("num") + (m.group("suffix") or "")).upper() if m else None

    assert item_of("Item 1. Business") == "1"
    assert item_of("Item 1A. Risk Factors") == "1A"
    assert item_of("Item 15. Exhibits") == "15", "두 자리 Item이 잘렸다 (교대 순서)"
    assert item_of("Item 16") == "16"
    assert item_of("ITEM 7A.") == "7A"  # 대소문자 무시
    assert item_of("as described in Item 1A above") is None, "^ 앵커가 없다 (F2)"
