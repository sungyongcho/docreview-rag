"""Korean lexical tokenization: n-gram shape, mixed scripts, and the shared contract."""

import pytest

from app.retrieval.korean import (
    KOREAN_LEXICAL_GRAMS,
    KOREAN_TEXT_SEARCH_CONFIG,
    hangul_ngrams,
    tokenize_korean_text,
)


def test_hangul_runs_become_overlapping_bigrams():
    assert tokenize_korean_text("삼성전자", grams=2) == "삼성 성전 전자"


def test_short_hangul_run_stays_whole():
    assert hangul_ngrams("칩", 2) == ["칩"]
    assert tokenize_korean_text("칩 설계", grams=2) == "칩 설계"


def test_particles_still_share_the_stem_grams():
    """The agglutinative variants a whitespace index separates now share grams."""
    subject = set(tokenize_korean_text("삼성전자는", grams=2).split())
    other = set(tokenize_korean_text("삼성전자가", grams=2).split())

    assert {"삼성", "성전", "전자"} <= subject & other


def test_latin_words_numbers_and_joined_figures_stay_whole():
    tokens = tokenize_korean_text("HBM 매출 300,870,903원 (58.1%)", grams=2).split()

    assert "hbm" in tokens
    assert "300,870,903" in tokens
    assert "58.1" in tokens


def test_mixed_script_text_keeps_document_order():
    assert tokenize_korean_text("DRAM 시장", grams=2) == "dram 시장"


def test_grams_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        tokenize_korean_text("삼성", grams=0)


def test_contract_constants_are_pinned():
    """The stored corpus depends on these exact values; changing them re-seeds."""
    assert KOREAN_LEXICAL_GRAMS == 2
    assert KOREAN_TEXT_SEARCH_CONFIG == "simple"
