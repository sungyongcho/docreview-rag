from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Section:
    doc_id: str
    section: str
    heading: str
    content: str
    citation: str


DOC_ID_RE = re.compile(r"doc_id:\s*([A-Z]+-\d+)")
VERSION_RE = re.compile(r"version:\s*([^|>\s]+)")
EFFECTIVE_RE = re.compile(r"effective:\s*([^|>\s]+)")
TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
SECTION_HEADING_RE = re.compile(
    r"^(#{2,6})\s+(\d+(?:\.\d+)*)\.?\s*(.+?)\s*$",
    re.MULTILINE,
)


def parse_document(path: Path) -> list[Section]:
    text = path.read_text(encoding="utf-8")

    # 1) 첫 줄에서 doc_id 정규식 추출 (없으면 에러)
    doc_id = _required_match(DOC_ID_RE, text, f"missing doc_id header in {path}")
    # version = _optional_match(VERSION_RE, text)
    # effective = _optional_match(EFFECTIVE_RE, text)
    # title = _optional_match(TITLE_RE, text) or path.stem

    # 2) 번호 헤딩(## 2, ### 2.1 ...)을 순서대로 찾고
    lines = text.splitlines()
    headings = list(SECTION_HEADING_RE.finditer(text))
    sections: list[Section] = []

    # 3) 각 헤딩~다음 헤딩 사이를 content로 잘라 Section 생성. 섹션 1개 = 청크 1개.
    for index, match in enumerate(headings):
        next_match = headings[index + 1] if index + 1 < len(headings) else None
        heading_line = text.count("\n", 0, match.start()) + 1
        content_start_line = heading_line + 1
        content_end_offset = next_match.start() if next_match else len(text)
        end_line = text.count("\n", 0, content_end_offset) + 1

        content = _slice_lines(lines, content_start_line, end_line).strip()
        _, section, heading = match.groups()

        sections.append(
            Section(
                doc_id=doc_id,
                section=section,
                heading=heading,
                content=content,
                citation=f"{doc_id} §{section}",
            )
        )

    return sections


def parse_corpus(dataset_root: Path) -> list[Section]:
    # seed/synthetic/*.md 전부 parse_document → 평탄화한 Section 리스트
    all_sections: list[Section] = []

    for path in sorted(dataset_root.glob("*.md")):
        sections = parse_document(path)
        all_sections.extend(sections)
    return all_sections


def _required_match(pattern: re.Pattern[str], text: str, error_message: str) -> str:
    match = pattern.search(text)
    if not match:
        raise ValueError(error_message)
    return match.group(1).strip()


def _optional_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1).strip()


def _slice_lines(lines: list[str], start_line: int, end_line: int) -> str:
    return "\n".join(lines[start_line - 1 : end_line - 1])


if __name__ == "__main__":
    import os

    root = Path(
        os.getenv("DATASET_ROOT", "data/sample1/docreview-dataset/data/seed/synthetic")
    )
    sections = parse_corpus(root)
    print("docs? ", len({s.doc_id for s in sections}), " sections:", len(sections))
    for s in sections:
        print(f"  {s.citation:12} | {s.heading[:40]}")
    assert all(s.citation == f"{s.doc_id} §{s.section}" for s in sections), (
        "인용 형식 깨짐"
    )
    print("OK: 모든 섹션에 doc_id·section·citation 존재")
