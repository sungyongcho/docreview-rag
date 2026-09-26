"""Korean lexical tokenization: n-gram shape, mixed scripts, and the shared contract."""

import pytest

from app.ingestion.registry import REGISTRIES
from app.retrieval.korean import (
    KOREAN_TEXT_SEARCH_CONFIG,
    lexical_corpus_language,
    lexical_plan,
    tokenize_korean_text,
)
from app.retrieval.types import RetrievalFilters


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
