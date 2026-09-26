"""Hangul-scan query-language detection."""

import pytest

from app.ingestion.parsing.registry import REGISTRIES
from app.query.language import (
    HANGUL_RANGES,
    KOREAN_TEXT_SEARCH_CONFIG,
    contains_hangul,
    detect_query_language,
    lexical_corpus_language,
    lexical_plan,
    tokenize_korean_text,
)
from app.retrieval.types import RetrievalFilters


@pytest.mark.parametrize(
    "query, language",
    [
        pytest.param("AMD의 매출총이익률은 어떻게 변화했습니까?", "ko", id="hangul-makes-korean"),
        pytest.param("TSMC 7nm 2021 10-K", "en", id="no-hangul-stays-english"),
    ],
)
def test_detect_query_language_classifies_on_hangul_presence(query, language):
    """Classify mixed-script queries by the presence of Hangul."""
    assert detect_query_language(query) == language


def test_detect_query_language_scans_the_declared_unicode_boundaries():
    """Recognize every declared Hangul boundary without spilling past it."""
    for start, end in HANGUL_RANGES:
        assert contains_hangul(chr(start))
        assert contains_hangul(chr(end))
        assert detect_query_language(f"AMD {chr(start)}") == "ko"

    # The characters immediately outside each range must stay English, or the
    # detector would route CJK punctuation and Latin text onto the Korean path.
    assert not contains_hangul(chr(0xAC00 - 1))
    assert not contains_hangul(chr(0xD7A3 + 1))
    assert not contains_hangul("AMD gross margin 2019")


def test_detect_query_language_rejects_blank_input():
    """Reject a query that carries no language-bearing text."""
    with pytest.raises(ValueError, match="blank"):
        detect_query_language("   ")


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        pytest.param("삼성전자", "삼성 성전 전자", id="hangul-run-becomes-overlapping-bigrams"),
        pytest.param("칩 설계", "칩 설계", id="runs-up-to-the-gram-size-stay-whole"),
        pytest.param(
            "HBM 매출 300,870,903원 (58.1%)",
            "hbm 매출 300,870,903 원 58.1",
            id="latin-words-and-joined-figures-stay-whole-in-document-order",
        ),
    ],
)
def test_tokenizer_emits_the_stored_lexical_tokens(text, tokens):
    """Split Hangul runs into overlapping bigrams and keep every other run whole, in order."""
    assert tokenize_korean_text(text) == tokens


def test_lexical_plans_cover_every_registry_language():
    """Every language a registry publishes in resolves to a lexical plan."""
    for registry in REGISTRIES.values():
        plan = lexical_plan(registry.language)
        assert plan.text_search_config

    with pytest.raises(ValueError, match="no lexical plan"):
        lexical_plan("fr")


def test_lexical_plans_pin_the_committed_index_contracts():
    """The en plan stores no lexical_text; the ko plan tokenizes both sides alike."""
    english = lexical_plan("en")
    korean = lexical_plan("ko")

    assert english.index_transform is None
    assert english.query_transform("NVDA revenue") == "NVDA revenue"
    assert english.text_search_config == "english"
    assert korean.index_transform is korean.query_transform is tokenize_korean_text
    assert korean.text_search_config == KOREAN_TEXT_SEARCH_CONFIG


def test_lexical_corpus_language_reads_the_filter():
    """No language filter keeps English; one language selects it; two are refused."""
    assert lexical_corpus_language(None) == "en"
    assert lexical_corpus_language(RetrievalFilters()) == "en"
    assert lexical_corpus_language(RetrievalFilters(languages=("ko",))) == "ko"

    with pytest.raises(ValueError, match="cannot span corpus languages"):
        lexical_corpus_language(RetrievalFilters(languages=("en", "ko")))
