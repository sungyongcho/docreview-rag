"""Hangul-scan query-language detection."""

import pytest

from app.retrieval.language import HANGUL_RANGES, contains_hangul, detect_query_language


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
