"""Source round-trip helpers shared by chunk tests."""

from collections import Counter
import re

from bs4 import BeautifulSoup

TOKEN = re.compile(r"[A-Za-z0-9]+(?:[.,'-][A-Za-z0-9]+)*|[$%€¥£()]", re.ASCII)


def source_text(raw: str, start: int, end: int) -> str:
    """Visible text from an original-HTML slice."""
    return BeautifulSoup(raw[start:end], "html.parser").get_text(" ", strip=True)


def tokens(text: str) -> list[str]:
    """Stable comparison tokens, excluding markdown's separator row."""
    return [match.group(0).lower() for match in TOKEN.finditer(text) if match.group(0) != "---"]


def is_subsequence(needles: list[str], haystack: list[str]) -> bool:
    """Whether all needles occur in order in the haystack."""
    iterator = iter(haystack)
    return all(any(candidate == needle for candidate in iterator) for needle in needles)


def counter_contains(haystack: list[str], needles: list[str]) -> bool:
    """Multiset containment used for column-merged table header cells."""
    source_counts = Counter(haystack)
    return all(source_counts[token] >= count for token, count in Counter(needles).items())
