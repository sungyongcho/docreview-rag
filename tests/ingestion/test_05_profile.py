"""6단계 — 프로파일 I/O + 오케스트레이션.

문서 강의: `docs/ko/m1-1-parser/03-build.md` L11(프로파일 I/O) · L13(오케스트레이션)
"""

import json

import pytest

from tests.ingestion.golden import PROFILE_YEARS
from tests.support import need

SAMPLE = {
    "segmentation": {"type": "number", "rules": [{"font_weight": 700}]},
    "validation": {"expected_items": 23, "must_have": ["1"]},
}


@pytest.fixture
def isolated(P, tmp_path):
    """`data/profiles`를 건드리지 않는 프로파일 디렉터리."""
    need(P, "PROFILES", "save_profile", "load_profile")
    original = P.PROFILES
    P.PROFILES = tmp_path
    yield tmp_path
    P.PROFILES = original


def test_missing_file_returns_none(P, isolated):
    """파일이 없으면 `None` — "아직 안 봤다"는 부트스트랩 대상이라는 뜻이다."""
    assert P.load_profile("ZZZZ", 2024) is None


def test_save_load_roundtrip(P, isolated):
    """저장한 게 그대로 돌아온다."""
    P.save_profile("TEST", 2024, SAMPLE)
    assert P.load_profile("TEST", 2024) == SAMPLE


def test_year_keys_are_strings(P, isolated):
    """JSON 객체 키는 문자열만 가능하다.

    `json.dumps`가 int 키를 조용히 문자열로 바꾸므로, 처음부터 `str(year)`로
    통일해야 "저장은 int, 로드는 str"이라는 미묘한 버그가 안 생긴다.
    """
    P.save_profile("TEST", 2024, SAMPLE)
    data = json.loads((isolated / "TEST.json").read_text())
    assert list(data["profiles"]) == ["2024"]


def test_unknown_year_falls_back_to_default(P, isolated):
    """요청 연도가 없으면 `default_year`의 것을 쓴다."""
    P.save_profile("TEST", 2024, SAMPLE)
    assert P.load_profile("TEST", 1999) == SAMPLE


def test_default_year_tracks_the_newest(P, isolated):
    """**`default_year`는 항상 가장 최근 연도를 가리킨다.**

    레이아웃은 앞으로 흘러가므로 새 제출물은 옛 해보다 최신 해를 닮을 확률이 높다.
    첫 부트스트랩 연도로 고정하면 AMD가 깨진다 — FY2019만 헤딩이 표 안이라(F4)
    그 예외가 기본값이 되어버린다.

    저장 순서와 무관해야 하므로 일부러 거꾸로 넣는다.
    """
    P.save_profile("TEST", 2019, {**SAMPLE, "learned_from": "old"})
    assert json.loads((isolated / "TEST.json").read_text())["default_year"] == "2019"

    P.save_profile("TEST", 2023, {**SAMPLE, "learned_from": "new"})
    data = json.loads((isolated / "TEST.json").read_text())
    assert data["default_year"] == "2023"

    # 옛 연도를 나중에 추가해도 default는 안 밀린다
    P.save_profile("TEST", 2020, {**SAMPLE, "learned_from": "older"})
    data = json.loads((isolated / "TEST.json").read_text())
    assert data["default_year"] == "2023"
    assert P.load_profile("TEST", 1999)["learned_from"] == "new"


def test_years_are_stored_in_ascending_order(P, isolated):
    """사람이 읽기 좋게 연도 오름차순으로 저장한다."""
    for y in (2023, 2019, 2021):
        P.save_profile("TEST", y, SAMPLE)
    data = json.loads((isolated / "TEST.json").read_text())
    assert list(data["profiles"]) == ["2019", "2021", "2023"]


def test_each_year_is_self_contained(P, isolated):
    """연도 항목에 병합 규칙이 없다 — 그래서 `load_profile`이 3줄로 끝난다.

    `default` + 오버라이드 구조였다면 "어느 필드를 어떻게 합칠까"가 들어온다.
    """
    a = {
        "segmentation": {"type": "number", "rules": [{"font_size": 10.0}]},
        "validation": {"expected_items": 21},
    }
    b = {"segmentation": {"type": "xref"}, "validation": {"must_have": ["8"]}}
    P.save_profile("TEST", 2019, a)
    P.save_profile("TEST", 2023, b)
    assert P.load_profile("TEST", 2019) == a  # b의 필드가 섞여 들어오지 않는다
    assert P.load_profile("TEST", 2023) == b
    assert "rules" not in P.load_profile("TEST", 2023)["segmentation"]


# ── 여기부터 코퍼스 필요 (`parsed`가 부트스트랩한 결과를 들여다본다)


@pytest.mark.parametrize("ticker", sorted(PROFILE_YEARS))
def test_bootstrapped_profile_shape(ticker, parsed, profiles_dir):
    """부트스트랩 결과의 `default_year`와 저장된 연도 목록.

    **연도 전부가 아니라 일부만 항목이 있는 게 정상이다** — 앞 연도 프로파일로
    검증을 통과하면 새로 만들지 않는다. INTC가 1개인 건 `xref`에
    `expected_items`가 없어서 5년이 한 프로파일로 전부 통과하기 때문이다.
    """
    default_year, years = PROFILE_YEARS[ticker]
    data = json.loads((profiles_dir / f"{ticker}.json").read_text())
    assert data["default_year"] == default_year
    assert sorted(data["profiles"], key=int) == years


def test_xref_profile_has_no_expected_items(parsed, profiles_dir):
    """`xref`는 `expected_items`를 저장하지 않는다 — 색인표가 연도마다 직접 알려준다."""
    data = json.loads((profiles_dir / "INTC.json").read_text())
    prof = data["profiles"]["2019"]
    assert prof["segmentation"] == {"type": "xref"}, "xref엔 rules가 없어야 한다"
    assert "expected_items" not in prof["validation"]


def test_profiles_converge_but_not_on_the_second_pass(P, manifest, tmp_path):
    """**같은 코퍼스를 반복해 돌리면 3회차에 안정된다. 2회차가 아니다.**

    직관은 "2회차는 전부 `saved`"지만 실측은 다르고, 그 차이에 이유가 있다.
    `expected_items`가 연도마다 다르기 때문이다(Item 1C·9C 신설로 21→23).
    `default_year`는 **최신** 연도를 가리키므로(F4가 요구한다), 항목이 없는
    옛 연도는 최신 연도의 기대 개수로 검증받아 반드시 실패한다:

        pass1  2019:bootstrap 2020:saved     2021:relearned 2022:saved     2023:relearned
               → 저장된 연도 {2019, 2021, 2023}, default=2023
        pass2  2019:saved     2020:relearned 2021:saved     2022:relearned 2023:saved
               → 2020·2022가 default(2023, 기대 23개)로 검증받아 실패 → 재학습·저장
        pass3  전부 saved     → 5개 연도가 다 채워져 폴백이 일어나지 않는다

    **버그가 아니라 self-healing이다** — 재학습이 성공했을 때만 저장하므로
    나쁜 규칙이 남지 않고, 빈 연도를 하나씩 메우며 수렴한다. 다만 "한 번 더
    돌리면 조용하다"가 아니라 "코퍼스를 한 바퀴 더 돌아야 조용하다"이다.

    AMD로 확인한다 — 5년 내내 항목 수가 21→23으로 변해 폴백 경로를 전부 지난다.
    """
    need(P, "parse_filing", "PROFILES")
    amd = sorted((x for x in manifest if x["ticker"] == "AMD"), key=lambda x: x["report_date"])
    original = P.PROFILES
    P.PROFILES = tmp_path
    try:
        passes = []
        for _ in range(3):
            used = {}
            for e in amd:
                r = P.parse_filing(e)
                r = r[0] if isinstance(r, tuple) else r
                assert r.parse_status == "parsed", f"{r.doc_id}: {r.warnings}"
                used[r.fiscal_year] = r.profile_used
            passes.append(used)
    finally:
        P.PROFILES = original

    assert passes[0] == {
        2019: "bootstrap",
        2020: "saved",
        2021: "relearned",
        2022: "saved",
        2023: "relearned",
    }
    assert passes[1] == {
        2019: "saved",
        2020: "relearned",
        2021: "saved",
        2022: "relearned",
        2023: "saved",
    }
    assert passes[2] == dict.fromkeys(range(2019, 2024), "saved"), "3회차에 수렴해야 한다"

    # 수렴한 뒤에는 다섯 해가 모두 자기 항목을 갖는다
    data = json.loads((tmp_path / "AMD.json").read_text())
    assert sorted(data["profiles"], key=int) == [str(y) for y in range(2019, 2024)]
    assert data["default_year"] == "2023"


def test_a_failed_relearn_is_not_saved(P, manifest, tmp_path):
    """**성공했을 때만 저장한다.**

    검증에 실패한 프로파일을 저장하면 다음 실행이 그 나쁜 규칙으로 시작한다.
    여기서는 통과할 수 없는 프로파일을 심어두고, 재학습이 그것을 덮어쓰되
    파일에 남는 것이 **재학습에 성공한 쪽**임을 확인한다.
    """
    need(P, "parse_filing", "PROFILES")
    e = next(x for x in manifest if x["ticker"] == "NVDA" and x["report_date"][:4] == "2024")
    original = P.PROFILES
    P.PROFILES = tmp_path
    try:
        P.save_profile(
            "NVDA",
            2024,
            {
                "segmentation": {
                    "type": "number",
                    "rules": [{"font_size": 99.0}],
                },  # 아무것도 안 맞는다
                "validation": {"expected_items": 23, "must_have": ["1", "1A", "7", "8"]},
            },
        )
        r = P.parse_filing(e)
        r = r[0] if isinstance(r, tuple) else r
    finally:
        P.PROFILES = original

    assert r.profile_used == "relearned"
    assert r.parse_status == "parsed"
    saved = json.loads((tmp_path / "NVDA.json").read_text())["profiles"]["2024"]
    assert saved["segmentation"]["rules"][0]["font_size"] != 99.0, "나쁜 규칙이 남았다"
