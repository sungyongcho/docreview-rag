from dataclasses import dataclass


@dataclass
class ChunkHit:
    """검색 결과 한 건 — 검색·워크플로우·평가가 공유하는 중심 계약."""

    doc_id: str
    section: str
    snippet: str
    score: float
    citation: str
