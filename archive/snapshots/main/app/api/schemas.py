"""API 요청/응답 DTO. (LLM 도메인 모델은 app/llm/schemas.py — 역할 다름)"""

from pydantic import BaseModel


# --- 검색 ---


class RetrieveRequest(BaseModel):
    query: str
    k: int = 5
    rerank: bool = False


class Hit(BaseModel):
    doc_id: str
    section: str
    snippet: str
    score: float
    citation: str


class RetrieveResponse(BaseModel):
    query: str
    results: list[Hit]


# --- 리뷰 ---


class ReviewRequest(BaseModel):
    claim: str
