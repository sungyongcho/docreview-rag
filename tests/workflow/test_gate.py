"""Conversation gate regression tests."""

import json
from pathlib import Path

import pytest

from app.retrieval.scope import ManifestScopeIndex
from app.workflow.gate import deterministic_decision
from tests.ingestion.support import filing_document


@pytest.fixture
def scope_index():
    """Provide the manifest aliases needed for deterministic target verification."""
    return ManifestScopeIndex.from_entries(
        (
            filing_document(
                registry="sec", issuer="NVDA", fiscal_year=2024, aliases=("NVDA", "Nvidia")
            ),
            filing_document(
                registry="dart",
                issuer="005930",
                fiscal_year=2024,
                aliases=("삼성전자", "Samsung Electronics"),
            ),
        )
    )


@pytest.mark.parametrize(
    "case",
    json.loads(
        (Path(__file__).resolve().parents[2] / "web/lib/routing-demo-cases.json").read_text()
    )["cases"],
    ids=lambda case: case["id"],
)
def test_development_demo_matches_routing_rules(case, scope_index) -> None:
    """Keep the illustrative guide scenarios aligned with the actual routing gate."""
    decision = deterministic_decision(
        case["query"], scope_index=scope_index, prior_filing_query=case.get("prior")
    )
    assert (decision.intent if decision else None) == case["expected_intent"]
    assert (decision.matched_rule if decision else None) == case["expected_rule"]
    if case.get("prior"):
        unanchored = deterministic_decision(case["query"], scope_index=scope_index)
        assert unanchored is None


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
        "고마워",
        "감사합니다",
        "help",
        "사용법",
    ],
)
def test_exact_service_intents_return_bounded_guidance(query: str) -> None:
    """Allow exact greetings and service help without inviting general conversation."""
    decision = deterministic_decision(query)

    assert decision is not None
    assert decision.intent == "service_help"
    assert decision.canned_answer


@pytest.mark.parametrize(
    "query",
    [
        "Nvidia revenue",
        "삼성전자 매출",
        "삼성의 주가는?",
        "삼전 영업이익",
        "엔비디아의 주가는?",
        "samsung 매출",
    ],
)
def test_known_company_filing_questions_stay_deterministic(query: str, scope_index) -> None:
    """Resolve fully covered issuer questions without spending a classifier call."""
    decision = deterministic_decision(query, scope_index=scope_index)

    assert decision is not None
    assert decision.intent == "document_review"
    assert decision.source == "deterministic"


@pytest.mark.parametrize(
    "query",
    [
        "NVIDIA 10-K sexual harassment risk disclosure",
        "삼성전자 사업보고서의 성희롱 관련 위험",
    ],
)
def test_filing_context_wins_over_words_that_are_casual_alone(query: str, scope_index) -> None:
    """Treat filing wording as review or fallback, never as out-of-scope casual."""
    decision = deterministic_decision(query, scope_index=scope_index)

    assert decision is None or decision.intent == "document_review"


@pytest.mark.parametrize(
    "query",
    [
        "고양이와 대화하기",
        "Pretend you are a cat",
        "Pretend Nvidia is a cat and talk to me",
    ],
)
def test_clear_roleplay_is_rejected_without_a_model(query: str, scope_index) -> None:
    """Keep obvious roleplay out of scope even with issuer or filing context."""
    decision = deterministic_decision(
        query, prior_filing_query="NVDA revenue 2023", scope_index=scope_index
    )

    assert decision is not None
    assert decision.intent == "out_of_scope"
    assert decision.source == "deterministic"


@pytest.mark.parametrize(
    "query",
    [
        "그럼 2024년은?",
        "What about Samsung Electronics?",
        "방금 이야기해준거 한글로 다시 설명해줄래",
        "Please explain that again in Korean",
    ],
)
def test_bounded_followups_continue_the_prior_filing_scope(query: str, scope_index) -> None:
    """Keep short elliptical continuations on the deterministic follow-up rule."""
    decision = deterministic_decision(
        query, prior_filing_query="NVDA revenue 2023", scope_index=scope_index
    )

    assert decision is not None
    assert decision.intent == "document_review"
    assert decision.source == "deterministic"
    assert decision.matched_rule == "filing_followup"


def test_followup_form_without_an_anchor_is_not_a_followup(scope_index) -> None:
    """An elliptical question without a filing anchor cannot claim follow-up scope."""
    decision = deterministic_decision("그럼 2024년은?", scope_index=scope_index)

    assert decision is None or decision.matched_rule != "filing_followup"


@pytest.mark.parametrize(
    "query",
    [
        "Compare Nvidia and SanDisk",
        "Nvidia or another company?",
        "Nvidia and UnknownCorp revenue",
        "Nvidia and NvidiaAI revenue",
    ],
)
def test_unresolved_targets_are_left_for_the_classifier(query: str, scope_index) -> None:
    """Leave mixed, partial, or unclear targets to one structured classification."""
    assert deterministic_decision(query, scope_index=scope_index) is None


def test_ambiguous_input_is_left_for_the_structured_classifier() -> None:
    """Return no guess when deterministic evidence is insufficient."""
    assert deterministic_decision("오늘 기분이 어때?") is None


def test_malformed_overlapping_tokens_cannot_hang_or_claim_scope() -> None:
    """Bound pathological repeated tokens that once triggered catastrophic backtracking."""
    import subprocess
    import sys

    script = """
from app.retrieval.scope import ManifestScopeIndex
from app.workflow.gate import deterministic_decision, is_filing_followup
from tests.ingestion.support import filing_document

index = ManifestScopeIndex.from_entries(
    (
        filing_document(
            registry="dart",
            issuer="005930",
            fiscal_year=2024,
            aliases=("삼성전자", "Samsung Electronics"),
        ),
    )
)
payload = "이야" * 40 + "X"
assert not is_filing_followup(payload)
decision = deterministic_decision(
    payload, prior_filing_query="NVDA revenue 2023", scope_index=index
)
assert decision is None or decision.intent != "document_review"
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
