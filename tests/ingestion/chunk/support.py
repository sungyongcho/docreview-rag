"""Source round-trip helpers shared by chunk tests."""

from collections import Counter
from pathlib import Path
import re

from bs4 import BeautifulSoup

from app.ingestion.parser import Block, ParsedFiling, Section
from app.retrieval.language import HANGUL_RANGES
from tests.ingestion.support import filing_source

# The Hangul ranges come from the retrieval boundary that already declares all three
# forms Korean text arrives in, so widening one place widens both.
_HANGUL = "".join(rf"\u{start:04x}-\u{end:04x}" for start, end in HANGUL_RANGES)
_HANJA = r"一-鿿"

# The ASCII alternative stays first and byte-identical: English tokenization is
# unchanged by construction. Without the scripts that follow it, a Korean chunk
# tokenizes to nothing and every grounding assertion below passes vacuously.
# ``re.ASCII`` is dropped rather than kept because the pattern uses no `\w`-class
# escape for it to narrow, so it only misleads the next reader.
TOKEN = re.compile(
    r"[A-Za-z0-9]+(?:[.,'-][A-Za-z0-9]+)*"
    rf"|[{_HANGUL}]+"
    rf"|[{_HANJA}]+"
    r"|[$%€¥£₩()△▲]"
)


def build_filing(blocks: list[Block]) -> ParsedFiling:
    """Build a source-identified filing for chunk unit tests."""
    filing = ParsedFiling(
        source=filing_source(Path(__file__)),
        source_length=1_000,
        source_sha256="a" * 64,
    )
    filing.sections = [
        Section("II", "7", "Management's Discussion", "Item 7. Management's Discussion", blocks)
    ]
    return filing


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


def markdown_cells(row: str) -> list[str]:
    """Split one markdown row without treating escaped cell pipes as delimiters."""
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", row.strip("|"))]
