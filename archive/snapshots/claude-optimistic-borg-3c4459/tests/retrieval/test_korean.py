"""Korean lexical tokenization: n-gram shape, mixed scripts, and the shared contract."""

import pytest

from app.ingestion.registry import REGISTRIES
from app.retrieval.korean import (
    KOREAN_LEXICAL_GRAMS,
    KOREAN_TEXT_SEARCH_CONFIG,
    hangul_ngrams,
    lexical_corpus_language,
    lexical_plan,
    tokenize_korean_text,
)
from app.retrieval.types import RetrievalFilters


def test_hangul_runs_become_overlapping_bigrams():
    """Split a Hangul run into overlapping bigrams so inflection cannot hide a term."""
    assert tokenize_korean_text("삼성전자", grams=2) == "삼성 성전 전자"


def test_short_hangul_run_stays_whole():
    """Keep a run shorter than the gram size as one token."""
    assert hangul_ngrams("칩", 2) == ["칩"]
    assert tokenize_korean_text("칩 설계", grams=2) == "칩 설계"


def test_particles_still_share_the_stem_grams():
    """The agglutinative variants a whitespace index separates now share grams."""
    subject = set(tokenize_korean_text("삼성전자는", grams=2).split())
    other = set(tokenize_korean_text("삼성전자가", grams=2).split())

    assert {"삼성", "성전", "전자"} <= subject & other


def test_latin_words_numbers_and_joined_figures_stay_whole():
    """Leave Latin words, numbers, and joined figures untouched."""
    tokens = tokenize_korean_text("HBM 매출 300,870,903원 (58.1%)", grams=2).split()

    assert "hbm" in tokens
    assert "300,870,903" in tokens
    assert "58.1" in tokens


def test_mixed_script_text_keeps_document_order():
    """Emit mixed-script tokens in the order the text carries them."""
    assert tokenize_korean_text("DRAM 시장", grams=2) == "dram 시장"


def test_grams_must_be_positive():
    """Reject a nonpositive gram size."""
    with pytest.raises(ValueError, match="positive"):
        tokenize_korean_text("삼성", grams=0)


def test_contract_constants_are_pinned():
    """The stored corpus depends on these exact values; changing them re-seeds."""
    assert KOREAN_LEXICAL_GRAMS == 2
    assert KOREAN_TEXT_SEARCH_CONFIG == "simple"


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
