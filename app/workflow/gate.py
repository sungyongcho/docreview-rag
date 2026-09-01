"""Conversation intent gate that keeps obvious casual input out of retrieval."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self
import unicodedata

from pydantic import Field, StrictStr
from pydantic.functional_validators import model_validator

from app.llm.schemas import NonBlank, StrictSchema

ConversationIntent = Literal["document_review", "casual_chat"]

CANNED_RESPONSES: dict[str, str] = {
    "안녕": "안녕하세요. 편하게 대화해도 되고, SEC 10-K나 DART 공시를 같이 봐도 좋아요.",
    "하이": "안녕하세요. 지금은 대화하거나 기업 공시를 검토할 수 있어요.",
    "안녕하세요": "안녕하세요. 편하게 대화해도 되고, SEC 10-K나 DART 공시를 같이 봐도 좋아요.",
    "hi": "Hello. We can chat, or review SEC and DART filings together.",
    "hello": "Hello. We can chat, or review SEC and DART filings together.",
    "helloworld": "Hello. DocReview is ready for SEC and DART filing questions.",
    "뭐함": "질문을 기다리고 있어요. 편하게 말하거나 기업 공시를 물어보세요.",
    "뭐해": "대기 중이에요. 잡담도 좋고 공시 분석도 가능합니다.",
    "섹스": "그 단어에 대해 어떤 맥락으로 이야기하고 싶은지 조금 더 알려주세요.",
    "보지털": "그 단어에 대해 어떤 맥락으로 이야기하고 싶은지 조금 더 알려주세요.",
}

FILING_CUES = re.compile(
    r"\b(?:10-k|sec|dart|filing|disclosure|revenue|risk|section|item)\b|"
    r"공시|사업보고서|매출|위험|실적|재무|원인|근거|수치",
    flags=re.IGNORECASE,
)


def normalize_intent_text(value: str) -> str:
    """Normalize one full utterance for exact canned-intent matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[\s!?.,~]+", "", normalized)


class ConversationTurn(StrictSchema):
    """One bounded prior browser conversation turn."""

    role: Literal["user", "assistant"]
    text: Annotated[StrictStr, Field(min_length=1, max_length=4_000)]

    @model_validator(mode="after")
    def reject_blank_text(self) -> Self:
        """Reject whitespace-only history text."""
        if not self.text.strip():
            raise ValueError("conversation turn text must not be blank")
        return self


class IntentClassification(StrictSchema):
    """Strict classifier output for an input the deterministic gate cannot decide."""

    intent: ConversationIntent
    reason: NonBlank


class ChatReply(StrictSchema):
    """One concise retrieval-free conversational answer."""

    answer: NonBlank


class ConversationDecision(StrictSchema):
    """Auditable deterministic or provider-backed conversation routing decision."""

    intent: ConversationIntent
    source: Literal["deterministic", "classifier"]
    matched_rule: NonBlank
    rationale: NonBlank
    canned_answer: NonBlank | None = None


def deterministic_decision(
    query: str,
    *,
    has_issuer_alias: bool = False,
) -> ConversationDecision | None:
    """Return only high-confidence exact casual or filing decisions."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    normalized = normalize_intent_text(query)
    if answer := CANNED_RESPONSES.get(normalized):
        return ConversationDecision(
            intent="casual_chat",
            source="deterministic",
            matched_rule=f"canned:{normalized}",
            rationale="The complete normalized utterance matches a canned casual intent.",
            canned_answer=answer,
        )
    if has_issuer_alias and FILING_CUES.search(query):
        return ConversationDecision(
            intent="document_review",
            source="deterministic",
            matched_rule="issuer_and_filing_cue",
            rationale="The query combines a known issuer with filing-review language.",
        )
    if FILING_CUES.search(query):
        return ConversationDecision(
            intent="document_review",
            source="deterministic",
            matched_rule="filing_cue",
            rationale="The query contains explicit filing-review language.",
        )
    return None
