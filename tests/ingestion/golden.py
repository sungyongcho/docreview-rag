"""골든값 — 20문서 코퍼스의 실측 기준선. **이 파일이 유일한 출처다.**

`docs/ko/m1-1-parser/05-verify.md`의 표는 여기를 사람이 읽으라고 옮겨 적은 것이고,
단언은 전부 이 파일을 import한다. 양쪽에 숫자를 적으면 드리프트가 재발한다.

전부 `data/corpus/manifest.json`의 20파일을 **프로파일 없는 상태에서 새로 학습**해
측정했다(= `conftest.py`의 `parsed` 픽스처와 같은 조건). `data/profiles/`에 뭐가
저장돼 있든 결과가 같아야 한다.

다시 뽑으려면:
    uv run python -m app.ingestion.parser --blocks
    uv run python -m app.ingestion.parser --coverage
"""

# ── 1~2단계: 블록화. (블록 수, 표블록 수, 문서 전체 <table> 수)
#
# 표블록이 0인 파일이 하나도 없어야 한다 — 0이면 F9(셀마다 <div>)에 걸려
# 재무제표가 셀 단위 문단으로 부서진 것이다. B04.
BLOCKS = {
    "AMD-FY2019": (5505, 22, 105),
    "AMD-FY2020": (1394, 54, 74),
    "AMD-FY2021": (1269, 49, 71),
    "AMD-FY2022": (1650, 54, 77),
    "AMD-FY2023": (1484, 43, 76),
    "INTC-FY2019": (10448, 18, 492),
    "INTC-FY2020": (2230, 133, 337),
    "INTC-FY2021": (2344, 119, 324),
    "INTC-FY2022": (2267, 120, 305),
    "INTC-FY2023": (2333, 95, 296),
    "MU-FY2020": (2130, 59, 72),
    "MU-FY2021": (2071, 55, 69),
    "MU-FY2022": (1976, 55, 68),
    "MU-FY2023": (2014, 54, 69),
    "MU-FY2024": (2071, 50, 68),
    "NVDA-FY2020": (5263, 23, 158),
    "NVDA-FY2021": (1323, 46, 59),
    "NVDA-FY2022": (1346, 49, 61),
    "NVDA-FY2023": (1420, 50, 66),
    "NVDA-FY2024": (1341, 52, 66),
}

# 구식 파일 3개 — 껍데기 div가 많아 블록이 3~5배다. 정상이므로 별도로 적어둔다.
LEGACY_FILES = frozenset({"AMD-FY2019", "NVDA-FY2020", "INTC-FY2019"})

# ── 최종확인②: 커버리지. (n_chars = 문서 전체, 섹션에 담긴 합)
#
# 100%가 목표가 아니다. 표지·목차·서명은 어느 Item에도 속하지 않으므로
# 정상 상한이 96~98%다. 100%에 가까우면 오히려 표지가 Item 1에 붙었다는 신호다.
COVERAGE = {
    "AMD-FY2019": (358178, 352812),
    "AMD-FY2020": (362278, 355792),
    "AMD-FY2021": (343224, 336569),
    "AMD-FY2022": (380277, 373047),
    "AMD-FY2023": (382481, 375210),
    "INTC-FY2019": (389944, 366166),
    "INTC-FY2020": (398474, 381491),
    "INTC-FY2021": (410587, 389769),
    "INTC-FY2022": (439377, 416727),
    "INTC-FY2023": (440913, 418780),
    "MU-FY2020": (311918, 302485),
    "MU-FY2021": (307031, 297276),
    "MU-FY2022": (292828, 282421),
    "MU-FY2023": (301271, 292345),
    "MU-FY2024": (312017, 303550),
    "NVDA-FY2020": (258346, 247153),
    "NVDA-FY2021": (294000, 282319),
    "NVDA-FY2022": (296849, 285038),
    "NVDA-FY2023": (306714, 295261),
    "NVDA-FY2024": (329808, 318319),
}

# 타입별 커버리지 허용 구간 (하한, 상한). 실측은 number 96.02~98.50 / xref 93.90~95.74.
# 상한을 두는 이유: 100%에 가까워지면 표지·목차가 섹션에 유입됐다는 뜻이다.
COVERAGE_BAND = {"number": (95.0, 99.0), "xref": (93.0, 97.0)}

# ── 최종확인①: 문서별 세그멘테이션 타입. 집계는 {'number': 15, 'xref': 5}.
SEGMENT_TYPE = {
    "AMD-FY2019": "number",
    "AMD-FY2020": "number",
    "AMD-FY2021": "number",
    "AMD-FY2022": "number",
    "AMD-FY2023": "number",
    "INTC-FY2019": "xref",
    "INTC-FY2020": "xref",
    "INTC-FY2021": "xref",
    "INTC-FY2022": "xref",
    "INTC-FY2023": "xref",
    "MU-FY2020": "number",
    "MU-FY2021": "number",
    "MU-FY2022": "number",
    "MU-FY2023": "number",
    "MU-FY2024": "number",
    "NVDA-FY2020": "number",
    "NVDA-FY2021": "number",
    "NVDA-FY2022": "number",
    "NVDA-FY2023": "number",
    "NVDA-FY2024": "number",
}

# Item 개수. 연도가 올라가며 20→23으로 느는 게 정상이다 (1C가 2023 신설, 9C가 2021).
N_ITEMS = {
    "AMD-FY2019": 21,
    "AMD-FY2020": 21,
    "AMD-FY2021": 22,
    "AMD-FY2022": 22,
    "AMD-FY2023": 23,
    "INTC-FY2019": 21,
    "INTC-FY2020": 21,
    "INTC-FY2021": 22,
    "INTC-FY2022": 22,
    "INTC-FY2023": 23,
    "MU-FY2020": 21,
    "MU-FY2021": 22,
    "MU-FY2022": 22,
    "MU-FY2023": 22,
    "MU-FY2024": 23,
    "NVDA-FY2020": 20,
    "NVDA-FY2021": 21,
    "NVDA-FY2022": 22,
    "NVDA-FY2023": 22,
    "NVDA-FY2024": 23,
}

# ── 최종확인③: SEC Item 대조.
#
# 이 셋만 부재가 정상이다. 그 외가 누락되면 헤딩을 놓친 것이고,
# ORDER에 없는 Item이 나오면(과잉) 헤딩 오탐이다. 실측 20/20 누락·과잉 0.
#   1C Cybersecurity          SEC 2023 신설  → FY2022 이전엔 없음
#   9C Foreign Jurisdictions  HFCAA 2021     → FY2020 이전엔 없음
#   16 Form 10-K Summary      선택 항목      → 언제든 (NVDA-FY2020이 생략)
ALWAYS_OPTIONAL = frozenset({"1C", "9C", "16"})

# ── 6단계: 프로파일 I/O. {ticker: (default_year, 저장된 연도들)}
#
# 연도 전부가 아니라 일부만 항목이 있는 게 정상이다 — 앞 연도 프로파일로
# 검증을 통과하면 새로 만들지 않는다. INTC가 1개인 건 xref에 expected_items가
# 없어서 5년이 전부 한 프로파일로 통과하기 때문이다.
# default_year는 항상 **최신**이어야 한다. 첫 부트스트랩 연도로 고정되면
# AMD가 FY2019(표 안 헤딩)를 기본값으로 갖게 되어 깨진다. F4.
PROFILE_YEARS = {
    "AMD": ("2023", ["2019", "2021", "2023"]),
    "INTC": ("2019", ["2019"]),
    "MU": ("2024", ["2020", "2021", "2024"]),
    "NVDA": ("2024", ["2020", "2021", "2022", "2024"]),
}

# 학습된 스타일 규칙. AMD-FY2019만 in_table=True인 게 F4의 증거다.
# {ticker: {year: (font_weight, font_size, in_table)}}
PROFILE_RULES = {
    "AMD": {
        "2019": (700, 10.0, True),  # ★이 해만 헤딩이 표 안
        "2021": (700, 10.0, False),
        "2023": (700, 10.0, False),
    },
    "MU": {
        "2020": (700, 14.0, False),
        "2021": (700, 14.0, False),
        "2024": (700, 14.0, False),
    },
    "NVDA": {
        "2020": (700, 11.0, False),
        "2021": (700, 11.0, False),
        "2022": (700, 11.0, False),
        "2024": (700, 10.0, False),  # 2024에 본문 폰트가 줄었다
    },
}

# ── 5단계: 상태 분류. NVDA-FY2024에서 `parsed`가 아닌 섹션 전부.
#
# 짧은 섹션이 버그가 아니라 정상 공시임을 보이는 표본이다.
# NVDA는 재무제표를 Item 15 아래에 싣기 때문에 Item 8이 참조가 된다.
STATUS_NVDA_FY2024 = {
    "1B": "empty_disclosure",  # "Not applicable."
    "4": "empty_disclosure",
    "9": "empty_disclosure",
    "8": "incorporated_by_reference",  # 재무제표는 Item 15에
    "9C": "incorporated_by_reference",
    "11": "incorporated_by_reference",  # proxy 위임
    "13": "incorporated_by_reference",
}
# Item 15가 두꺼운 게 위의 귀결이다 — 82k / 표 34개.
NVDA_FY2024_ITEM15_MIN_CHARS = 80_000

# ── 7~8단계: xref. {doc_id: (색인표 엔트리 수, 목차 행 수)}
XREF_TABLES = {
    "INTC-FY2019": (21, 30),
    "INTC-FY2020": (21, 29),
    "INTC-FY2021": (22, 26),
    "INTC-FY2022": (22, 25),
    "INTC-FY2023": (23, 29),
}

# xref 페이지 조인의 결과물. {doc_id: (Item 7 본문자수, Item 8 표 개수)}
#
# ⚠ FY2019는 다른 해와 성격이 다르다. 두 가지가 겹친다:
#   ① Intel 자체 색인표가 그 해엔 "Our Products"(p17)를 Item 7이 아니라 Item 1에
#      배정했다 → Item 7이 33k로 작고 Item 1이 86k로 크다. 버그가 아니라
#      문서가 말하는 대로 따른 결과다.
#   ② 구식 파일이라 표블록 자체가 18개뿐이다 → Item 8 표가 7개.
# 그래서 "Item 7은 65k↑, Item 8 표는 50↑" 같은 단일 기준선을 쓸 수 없다.
XREF_ITEM_SHAPE = {
    "INTC-FY2019": (33_445, 7),
    "INTC-FY2020": (76_692, 65),
    "INTC-FY2021": (69_838, 60),
    "INTC-FY2022": (76_131, 64),
    "INTC-FY2023": (74_065, 52),
}

# ── 최종확인④: 원본 오프셋 대조. NVDA-FY2024의 헤딩 위치.
#
# 파서가 "Item 1A를 찾았다"고 주장할 때 그게 정말 거기 있는지는 원본을 봐야 안다.
# {item: (source_pos, 그 위치에서 시작해야 하는 원본 텍스트)}
NVDA_FY2024_FILE = "data/corpus/NVDA/2024-02-21_0001045810-24-000029.html"
NVDA_FY2024_OFFSETS = {
    "1": (198007, "Item 1. Business"),
    "1A": (289841, "Item 1A. Risk Factors"),
    "1B": (462881, "Item 1B. Unresolved Staff Comments"),
    "1C": (463352, "Item 1C. Cybersecurity"),
}

# M1.2: table HTML to markdown.
# Tuple: (table blocks, empty markdown, expanded cells, collapsed cells)
#
# SEC tables are layout tables. The median table has 63.6% empty raw cells,
# the corpus has no <th>, and colspan is used to position content. A logical
# three-column income statement arrives as 12 physical columns.
#
# These values protect layout collapse, not mere serialization. The stages are
# 221,730 expanded cells -> 69,241 after empty-axis removal -> 66,575 after unit
# folding. A higher final count leaves layout behind; a lower one removes content.
#
# The 26 empty markdown results are layout-only spacer tables. They occur only
# in AMD and INTC filings and are a publisher-layout difference, not an error.
#
# Regenerate every aggregate and per-document tuple with:
#     uv run python -m scripts.measure_tables
TABLES = {
    "AMD-FY2019": (22, 0, 3628, 2494),
    "AMD-FY2020": (54, 4, 10644, 3166),
    "AMD-FY2021": (49, 4, 10098, 2821),
    "AMD-FY2022": (54, 1, 11577, 3458),
    "AMD-FY2023": (43, 1, 9603, 3003),
    "INTC-FY2019": (18, 0, 4740, 2812),
    "INTC-FY2020": (133, 4, 17817, 3972),
    "INTC-FY2021": (119, 4, 18555, 3996),
    "INTC-FY2022": (120, 4, 20289, 4358),
    "INTC-FY2023": (95, 4, 15882, 3268),
    "MU-FY2020": (59, 0, 13047, 4354),
    "MU-FY2021": (55, 0, 9267, 3624),
    "MU-FY2022": (55, 0, 9687, 3700),
    "MU-FY2023": (54, 0, 8949, 3611),
    "MU-FY2024": (50, 0, 8658, 3530),
    "NVDA-FY2020": (23, 0, 3689, 2346),
    "NVDA-FY2021": (46, 0, 10473, 2774),
    "NVDA-FY2022": (49, 0, 12090, 3036),
    "NVDA-FY2023": (50, 0, 11100, 2949),
    "NVDA-FY2024": (52, 0, 11937, 3303),
}

# Representative full-output golden: the NVDA-FY2024 percentage income statement
# collapses from 12 physical columns to 3 logical columns.
NVDA_FY2024_INCOME_MD = """\
|  | Year Ended Jan 28, 2024 | Jan 29, 2023 |
| --- | --- | --- |
| Revenue | 100.0 % | 100.0 % |
| Cost of revenue | 27.3 | 43.1 |
| Gross profit | 72.7 | 56.9 |
| Operating expenses |  |  |
| Research and development | 14.2 | 27.2 |
| Sales, general and administrative | 4.4 | 9.1 |
| Acquisition termination cost | — | 5.0 |
| Total operating expenses | 18.6 | 41.3 |
| Operating income | 54.1 | 15.6 |
| Interest income | 1.4 | 1.0 |
| Interest expense | (0.4) | (1.0) |
| Other, net | 0.4 | (0.1) |
| Other income (expense), net | 1.4 | (0.1) |
| Income before income tax | 55.5 | 15.5 |
| Income tax expense (benefit) | 6.6 | (0.7) |
| Net income | 48.9 % | 16.2 % |"""
