"""M8.4 query path: fail-closed translation through the deterministic LLM boundary."""

import asyncio
from decimal import Decimal

from pydantic import ValidationError
import pytest

from app.llm import DeterministicLLMProvider, ProviderBudget, RawProviderResponse, TokenPricing
from tests.support import need

KOREAN_QUERY = "AMD는 TSMC와 관련하여 어떤 7nm 공급 위험을 밝혔습니까?"
ENGLISH_QUERY = "What specific 7 nm supply risk did AMD identify involving TSMC?"


def budget() -> ProviderBudget:
    """Return one budget large enough for a translation and its single repair."""
    return ProviderBudget(
        max_input_tokens=1_000,
        max_output_tokens=200,
        max_cost_usd=Decimal("0.10"),
        pricing=TokenPricing(
            input_per_million_usd=Decimal("0.4"),
            output_per_million_usd=Decimal("1.6"),
        ),
    )


def raw(output_text: str, *, refusal: str | None = None) -> RawProviderResponse:
    """Return one canned provider response with fixed usage accounting."""
    return RawProviderResponse(
        output_text=output_text,
        input_tokens=10,
        output_tokens=5,
        request_id="req-1",
        refusal=refusal,
    )


def translate(TR, provider):
    """Run one translation through the injected provider."""
    return asyncio.run(
        TR.translate_query(
            KOREAN_QUERY,
            llm_provider=provider,
            provider_budget=budget(),
        )
    )


def test_translate_query_returns_the_validated_english_query(TR):
    need(TR, "translate_query", "QueryTranslation")
    provider = DeterministicLLMProvider(
        [raw(f'{{"translated_query":"{ENGLISH_QUERY}","source_language":"ko"}}')]
    )

    translation = translate(TR, provider)

    assert translation.translated_query == ENGLISH_QUERY
    assert translation.source_language == "ko"
    assert provider.prompts[0].user == KOREAN_QUERY
    assert "English" in provider.prompts[0].system


def test_translation_contract_rejects_blank_extra_and_unknown_languages(TR):
    need(TR, "QueryTranslation")
    translation = TR.QueryTranslation(translated_query=ENGLISH_QUERY, source_language="ko")

    with pytest.raises(ValidationError):
        translation.translated_query = "changed"
    with pytest.raises(ValidationError):
        TR.QueryTranslation(translated_query="   ", source_language="ko")
    with pytest.raises(ValidationError):
        TR.QueryTranslation(translated_query=ENGLISH_QUERY, source_language="fr")
    with pytest.raises(ValidationError):
        TR.QueryTranslation(
            translated_query=ENGLISH_QUERY,
            source_language="ko",
            confidence=0.9,
        )


def test_translate_query_fails_closed_instead_of_returning_the_original(TR):
    need(TR, "translate_query", "QueryTranslationError")

    # Schema failure survives the provider's one repair attempt.
    rejecting = DeterministicLLMProvider([raw("not json"), raw("still not json")])
    with pytest.raises(TR.QueryTranslationError, match="schema_rejected"):
        translate(TR, rejecting)

    refusing = DeterministicLLMProvider([raw("", refusal="I cannot help with that.")])
    with pytest.raises(TR.QueryTranslationError, match="provider_refused"):
        translate(TR, refusing)


def test_translate_query_rejects_a_translation_that_is_still_korean(TR):
    need(TR, "translate_query", "QueryTranslationError")
    provider = DeterministicLLMProvider(
        [raw('{"translated_query":"AMD의 7nm 공급 위험","source_language":"ko"}')] * 2
    )

    with pytest.raises(TR.QueryTranslationError, match="not English"):
        translate(TR, provider)


@pytest.mark.parametrize("query", ["", "   "])
def test_translate_query_rejects_blank_input_before_any_provider_call(TR, query):
    need(TR, "translate_query")
    provider = DeterministicLLMProvider([])

    with pytest.raises(ValueError, match="blank"):
        asyncio.run(TR.translate_query(query, llm_provider=provider, provider_budget=budget()))
    assert provider.prompts == ()


def test_translation_never_reaches_a_network_provider(TR):
    need(TR, "translate_query")
    provider = DeterministicLLMProvider(
        [raw(f'{{"translated_query":"{ENGLISH_QUERY}","source_language":"ko"}}')]
    )

    translate(TR, provider)

    # The queue is empty afterwards, so exactly one request was made and it was made
    # against the injected provider. Translation is injection-only by design: no
    # Settings switch can put a paid call into the query path.
    with pytest.raises(TR.QueryTranslationError):
        translate(TR, provider)
    assert len(provider.prompts) == 2
    with pytest.raises(TypeError):
        asyncio.run(TR.translate_query(KOREAN_QUERY))
