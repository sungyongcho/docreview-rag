from typing import Literal

from pydantic import BaseModel, Field

Label = Literal["SUPPORTED", "CONTRADICTED", "NOT_IN_DOCS", "PARTIALLY_SUPPORTED"]


class ClaimReport(BaseModel):
    label: Label = Field(description="판정 라벨")
    citations: list[str] = Field(
        default_factory=list, description="근거 인용, 예: ['HR-001 §2.1']"
    )
    rationale: str = Field(description="왜 그 라벨인지 근거 문장")


class EvidenceGrade(BaseModel):
    sufficient: bool = Field(description="근거가 이 주장을 판정하기에 관련·충분한가")
    reason: str = Field(description="이유")


class SearchQuery(BaseModel):
    query: str = Field(description="정책 문서 검색용 짧은 키워드 쿼리")


class ChecklistItemVerdict(BaseModel):
    verdict: Literal["PASS", "FAIL"] = Field(
        description="시나리오가 이 요건을 만족하나"
    )
    reason: str = Field(description="이유")
