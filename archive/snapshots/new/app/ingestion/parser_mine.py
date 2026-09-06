from dataclasses import dataclass, field
import re
from typing import Literal
import warnings

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

SegmentType = Literal["number", "sec_canonical", "custom_title", "xref", "undefined"]
ItemStatus = Literal["parsed", "empty_disclosure", "incorporated_by_reference"]

"""
CONSTANNTS
"""
DATA_TABLE_MIN_CELLS = 6  # 이하는 표가 아니라 레이아웃 조각
LAYOUT_CELL_CHARS = 300  # 이 길이의 셀이 하나라도 있으면 레이아웃 표.
#                          숫자 밀도보다 **먼저** 본다 — Intel 인포그래픽 표 배제 (B05)
NUMERIC_CELL_CHARS = 30  # 그보다 길면 숫자가 섞인 문장이지 데이터 셀이 아니다
DATA_TABLE_MIN_NUMERIC = 4  # 숫자 셀 최소 개수
DATA_TABLE_NUMERIC_DIVISOR = 4  # 그리고 전체 셀의 1/4 이상이어야 한다

# L7 헤딩 순회
HEADING_MAX_CHARS = 300  # 이보다 긴 블록은 헤딩일 수 없다 — 가장 값싼 필터
SUBHEADING_MAX_CHARS = 80  # level-2 하위 소제목 상한
REPORTED_TITLE_MAX = 150  # Section.reported_title 보관 길이
CANON_MIN_CHARS = 8  # SEC 표준 제목 대조 하한. 짧으면 우연히 겹친다 (B11)
CANON_PREFIX_CHARS = 14  # 접두 일치는 이만큼 길 때만 인정 (B11)

# L9 판별 캐스케이드
NUMBER_MIN_HITS = 5  # 이하는 헤딩이 아니라 상호참조
OUTSIDE_TABLE_MIN_HITS = 15  # 표 밖에서 이만큼 못 찾으면 표 안까지 본다 (F4)
TOC_MIN_ITEMS = 10  # 목차 판정에 필요한 최소 Item 후보 수
TOC_DENSITY = 0.15  # 후보가 문서의 이 비율 안에 몰려 있으면 목차 (B16)
XREF_MIN_ENTRIES = 10  # 색인표로 인정할 최소 엔트리
XREF_MIN_TOC_ROWS = 5  # 목차표로 인정할 최소 행

# L8 xref 조립
ORPHAN_MIN_BLOCKS = 3  # 고아 구간이 이보다 짧으면 잔부스러기 — 버린다 (B07)
JOINED_TITLE_MAX = 300  # 서사 제목 여러 개를 합친 reported_title 상한
PAGE_HEADER_MAX_CHARS = 60  # 짧고 자주 나오면 페이지 헤더다 (F11)
PAGE_HEADER_MIN_REPEATS = 10  # "Table of Contents" 113회

# L10 상태 분류
CLASSIFY_SCAN_CHARS = 400  # 섹션 서두 이만큼만 보고 판정한다
REF_MAX_BLOCKS = 3  # 블록이 이보다 많으면 본문이 있는 것 — 참조로 안 본다

# L12 검증
CORE_THIN_BLOCKS = 20  # 핵심 Item이 이보다 적으면 "본문 없음"
CORE_THIN_COUNT = 2  # 그런 핵심 Item이 이만큼이면 목차를 헤딩으로 잡은 것 (B10)
XREF_THIN_BLOCKS = 5  # xref에서 얇은 섹션 기준
XREF_THIN_RATIO = 0.3  # 얇은 섹션이 이 비율을 넘으면 실패

XREF_TABLE_MIN_ITEM_ROWS = 5  # `Item N.` 셀이 이만큼 있어야 색인표
TOC_HEADER_SCAN_ROWS = 3  # 앞 몇 행에서 "Page" 헤더를 찾나
TOC_TABLE_MIN_ROWS = 10  # `제목 | 쪽수` 행이 이만큼 있어야 목차표
REF_NOTE_MIN_CHARS = 8  # "(a) Incorporated by …" — 이보다 짧으면 각주가 아니다

# 본문 연결
TOC_TITLE_MAX_CHARS = 120  # 이보다 긴 블록은 제목이 아니라 문단이다
MISSING_TITLE_MIN_CHARS = 8  # 2차 수색 — 짧은 제목은 우연히 겹친다

# 페이지 footer 지도 (F8)
FOOTER_MAX_STEP = 3  # 페이지 증가폭. 표 안 숫자 셀은 순서가 뒤죽박죽이라 걸러낸다
FOOTER_MIN_GAP = 5  # 직전 footer와 최소 간격. 재무 색인의 "76 77 78…" 클러스터 배제


@dataclass
class Block:
    kind: Literal["heading", "paragraph", "table"]
    text: str
    level: int | None = None  # 1=Item 헤딩, 2=하위 소제목
    html: str | None = None  # 표 원본 (M1.2에서 markdown 변환)


@dataclass
class Section:
    part: str | None  # "I".."IV"
    item: str | None  # "1A"
    canonical_title: str  # SEC 표준 제목
    reported_title: str  # 문서가 실제로 쓴 제목
    blocks: list[Block] = field(default_factory=list)
    status: ItemStatus = "parsed"
    reference_source: str | None = None
    # ── 위치. "Item을 찾았다"가 아니라 "어디서 찾았다"를 말할 수 있어야 검증이 된다
    block_index: int | None = None  # 헤딩 블록 번호
    block_range: tuple[int, int] | None = None  # 이 섹션이 차지하는 블록 구간
    source_pos: int | None = None  # 원본 HTML의 문자 오프셋


CANONICAL = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety Disclosures",
    "5": "Market for Registrant's Common Equity",
    "6": "Reserved",
    "7": "Management's Discussion and Analysis",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements and Supplementary Data",
    "9": "Changes in and Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Foreign Jurisdictions That Prevent Inspections",
    "10": "Directors, Executive Officers and Corporate Governance",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Certain Relationships and Related Transactions",
    "14": "Principal Accountant Fees and Services",
    "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}
ORDER = list(CANONICAL)  # dict는 3.7+ 삽입 순서 보장
PART_OF = {
    **dict.fromkeys(["1", "1A", "1B", "1C", "2", "3", "4"], "I"),
    **dict.fromkeys(["5", "6", "7", "7A", "8", "9", "9A", "9B", "9C"], "II"),
    **dict.fromkeys(["10", "11", "12", "13", "14"], "III"),
    **dict.fromkeys(["15", "16"], "IV"),
}

ITEM_RE = re.compile(
    r"^\s*item\s+(?P<num>1[0-6]|[1-9])(?P<suffix>[A-C])?\s*[.\-–—:]?\s*(?P<title>.*)$",
    re.I,
)


# def line_offsets(html: str) -> list[int]:
#     """각 줄의 시작 절대 오프셋. `source_pos` 계산에 쓴다."""
#     out, off = [], 0
#     for line in html.splitlines(keepends=True):
#         out.append(off)
#         off += len(line)
#     return out


def normalize(html: str) -> BeautifulSoup:
    # html.parser + store_line_numbers: 블록의 원본 위치를 알아야 검증이 가능하다.
    # lxml은 sourceline을 안 채운다. 실측상 20개 파일 블록 텍스트가 완전히 동일하고
    # 전체 비용은 +1.6초뿐이다.

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "html.parser", store_line_numbers=True)
    for tag in soup.find_all(["script", "style", "noscript", "img"]):
        tag.decompose()
    for tag in soup.find_all(
        "ix:header"
    ):  # to mark that ix needs to be treated differenty fron aboves
        tag.decompose()
    for tag in soup.find_all(lambda tag: bool(tag.name and tag.name.startswith("ix:"))):
        tag.unwrap()  # 나머지는 태그만 벗기고 텍스트(숫자) 보존
    return soup


def leaf_blocks(soup: BeautifulSoup) -> list[Tag]:
    def _is_data_table(tbl: Tag) -> bool:
        """재무 데이터 표인가(숫자 셀 밀도). 레이아웃 표와 갈라야 한다."""
        cells = tbl.find_all(["td", "th"])
        if len(cells) < 6:
            return False
        texts = [c.get_text(" ", strip=True) for c in cells]
        if any(len(t) > 300 for t in texts):  # 장문 셀 = 레이아웃 표
            return False
        numeric = sum(1 for t in texts if t and len(t) < 30 and re.search(r"\d", t))
        return numeric >= max(4, len(cells) // 4)

    data_ids: set[int] = set()
    for t in soup.find_all("table"):
        if _is_data_table(t) and not any(id(p) in data_ids for p in t.find_parents("table")):
            data_ids.add(id(t))  # 중첩 표는 바깥 것만

    out = []
    for el in soup.find_all(["div", "p", "table"]):
        inside_data = any(id(p) in data_ids for p in el.find_parents("table"))
        if el.name == "table":
            if not inside_data and (id(el) in data_ids or el.find(["div", "p", "table"]) is None):
                out.append(el)  # 데이터 표 or 구식 리프 표 → 통짜
        elif not inside_data and el.find(["div", "p", "table"]) is None:
            out.append(el)
    return out


def block_props(el: Tag) -> dict:
    def _inline_css(el: Tag) -> str:
        """현재 요소와 안쪽 span 2개의 인라인 CSS를 하나로 합친다."""
        styles: list[str] = []

        own_style = el.get("style")
        if isinstance(own_style, str):
            styles.append(own_style)

        for span in el.find_all("span", limit=2):
            span_style = span.get("style")
            if isinstance(span_style, str):
                styles.append(span_style)

        return " ".join(styles)

    css = _inline_css(el)

    def num(pattern: str) -> float:
        m = re.search(pattern, css)
        return float(m.group(1)) if m else 0.0

    mw = re.search(r"font-weight:\s*(\d+|bold)", css)
    weight = mw.group(1) if mw else "400"
    return {
        "font_weight": 700 if weight == "bold" else int(weight),
        "font_size": num(r"font-size:\s*([\d.]+)pt"),
        "margin_top": num(r"margin-top:\s*([\d.]+)pt"),
        "margin_bottom": num(r"margin-bottom:\s*([\d.]+)pt"),
        "text_align": (m.group(1) if (m := re.search(r"text-align:\s*(\w+)", css)) else ""),
        "tag": el.name,
        "in_table": el.find_parent("table") is not None,
    }


def matches_rule(el: Tag, rule: dict) -> bool:
    props = block_props(el)
    for key, expected in rule.items():
        actual = props.get(key)
        if actual is None:
            continue
        if key == "in_table":
            if not expected and actual:
                return False
        elif isinstance(expected, bool) or isinstance(actual, bool):
            if actual != expected:
                return False
        elif isinstance(expected, int | float):
            if actual < expected:
                return False
        elif actual != expected:
            return False
    return True


def matches_any(el: Tag, rules: list[dict]) -> bool:
    return any(matches_rule(el, r) for r in rules)


# def body_after(blocks: list[Tag], idx: int, span: int = 8) -> int:
#     """이 블록 뒤에 따라오는 본문 분량. 학습 시 후보 필터용.

#     실측(INTC FY2019 'RISK FACTORS' 3회): 헤딩 뒤 1851 / 목차 뒤 41 / 색인 뒤 90
#     """
#     return sum(
#         len(blocks[j].get_text(" ", strip=True))
#         for j in range(idx + 1, min(idx + 1 + span, len(blocks)))
#     )


def match_canonical(text: str) -> str | None:
    def _norm_title(s: str) -> str:
        """비교용 정규화 — 소문자 + 알파벳/공백만."""
        return re.sub(r"[^a-z ]", "", s.lower()).strip()

    t = _norm_title(text)
    if len(t) < CANON_MIN_CHARS:
        return None

    for item, canon in CANONICAL.items():
        c = _norm_title(canon)
        if t == c:
            return item
        if len(c) >= CANON_PREFIX_CHARS and (
            t.startswith(c[:CANON_PREFIX_CHARS]) or c.startswith(t[:CANON_PREFIX_CHARS])
        ):
            return item
    return None


def find_item(el: Tag, text: str, seg: dict) -> str | None:
    match seg["type"]:
        case "number":
            m = ITEM_RE.match(text)
            item = (m.group("num") + (m.group("suffix") or "")).upper() if m else None
        case "sec_canonical":
            item = match_canonical(text)
        case "custom_title":
            low = text.strip().lower()
            item = next(
                (e["item"] for e in seg["order"] if e["title"].strip().lower() == low),
                None,
            )
        case _:
            return None

    if item is None:
        return None

    return item if matches_any(el, seg["rules"]) else None


def source_pos(
    el: Tag, offsets: list[int]
) -> int | None:  # TODO:  need to check if it's safe to place this function in here
    """이 블록이 원본 HTML의 몇 번째 문자에서 시작하나.

    10-K는 minify돼서 파일이 5줄뿐이다 — 줄 번호는 무의미하고 문자 오프셋이 필요하다.
    `sourcepos`는 줄 안에서의 위치라 줄 시작 오프셋을 더해야 절대 위치가 된다.
    """
    if el.sourceline is None or el.sourcepos is None:
        return None
    return offsets[el.sourceline - 1] + el.sourcepos


def segment_by_heading(
    blocks: list[Tag], seg: dict, offsets: list[int] | None = None
) -> list[Section]:
    def _body_block(el: Tag, text: str) -> Block:
        """헤딩이 아닌 블록을 출력 계약의 Block으로."""
        if el.name == "table":
            return Block("table", "", html=str(el))
        if len(text) <= SUBHEADING_MAX_CHARS and block_props(el)["font_weight"] >= 700:
            return Block("heading", text, level=2)  # 하위 소제목
        return Block("paragraph", text)

    texts = [b.get_text(" ", strip=True) for b in blocks]
    sections: list[Section] = []
    current: Section | None = None

    for i, el in enumerate(blocks):
        text = texts[i]
        if not text:
            continue

        item = find_item(el, text, seg) if len(text) < HEADING_MAX_CHARS else None

        if item:
            if current is not None:
                current.block_range = (current.block_index or 0, i)
            current = Section(
                part=PART_OF.get(item),
                item=item,
                canonical_title=CANONICAL.get(item, ""),
                reported_title=text[:REPORTED_TITLE_MAX],
                block_index=i,
                source_pos=source_pos(el, offsets) if offsets else None,
            )
            sections.append(current)
        elif current is not None:
            current.blocks.append(_body_block(el, text))

    if current is not None:
        current.block_range = (current.block_index or 0, len(blocks))

    return sections
