"""Query-language detection for the cross-lingual retrieval path."""

from typing import Literal

QueryLanguage = Literal["en", "ko"]

# Korean reaches this boundary in three Unicode ranges: precomposed syllables,
# the conjoining jamo that decomposed (NFD) input carries, and the compatibility
# jamo an input method emits for a bare consonant or vowel. Scanning all three
# means a query is classified from its own characters, with no model, no API call,
# and no dependency on how the client normalized the text.
HANGUL_SYLLABLES = (0xAC00, 0xD7A3)
HANGUL_JAMO = (0x1100, 0x11FF)
HANGUL_COMPATIBILITY_JAMO = (0x3130, 0x318F)
HANGUL_RANGES = (HANGUL_SYLLABLES, HANGUL_JAMO, HANGUL_COMPATIBILITY_JAMO)


def contains_hangul(text: str) -> bool:
    """Return whether any character of ``text`` is a Hangul syllable or jamo."""
    return any(start <= ord(character) <= end for character in text for start, end in HANGUL_RANGES)


def detect_query_language(query: str) -> QueryLanguage:
    """Classify a nonblank query as Korean when it contains any Hangul.

    Presence, rather than script proportion, preserves mixed queries such as tickers
    and process nodes surrounded by Korean text.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    return "ko" if contains_hangul(query) else "en"
