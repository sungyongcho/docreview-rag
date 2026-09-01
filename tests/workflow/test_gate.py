"""Conversation gate regression tests."""

import pytest

from app.workflow.gate import deterministic_decision


@pytest.mark.parametrize(
    "query",
    [
        "안녕",
        "안녕하세요",
        "안녕!!!",
        "하이",
        "hi",
        "hello",
        "hello world",
        "뭐함",
        "섹스",
        "보지털",
    ],
)
def test_exact_casual_intents_never_enter_document_review(query: str) -> None:
    """Classify only complete normalized canned utterances as casual."""
    decision = deterministic_decision(query)

    assert decision is not None
    assert decision.intent == "casual_chat"
    assert decision.canned_answer


@pytest.mark.parametrize(
    "query",
    [
        "NVIDIA 10-K sexual harassment risk disclosure",
        "삼성전자 사업보고서의 성희롱 관련 위험",
    ],
)
def test_filing_context_wins_over_words_that_are_casual_alone(query: str) -> None:
    """Avoid a substring blacklist that would bypass filing retrieval."""
    decision = deterministic_decision(query, has_issuer_alias=True)

    assert decision is not None
    assert decision.intent == "document_review"


def test_ambiguous_input_is_left_for_the_structured_classifier() -> None:
    """Return no guess when deterministic evidence is insufficient."""
    assert deterministic_decision("오늘 기분이 어때?") is None
