"""Resolve one corpus manifest entry to the registry adapter that can read it."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from app.ingestion.dart import dart_doc_id, dart_section_label, dart_sort_key, parse_dart_filing
from app.ingestion.parser import ParsedFiling, doc_id, parse_filing

DEFAULT_REGISTRY: Final[str] = "sec"


@dataclass(frozen=True, slots=True)
class Registry:
    """The readers one publishing registry supplies for its own manifest entries.

    Manifest keys belong to the registry that wrote them — EDGAR spells an entry with
    ``ticker`` and ``report_date`` — while everything downstream of the parse consumes
    the neutral ``ParsedFiling`` contract. Holding the translation here is what lets the
    seed path, the golden loader, and the evaluation corpus read a manifest without
    knowing which registry produced it.

    ``language`` is the corpus language of the documents this registry publishes, which
    the parse records on the filing rather than inferring from the text.
    """

    name: str
    language: str
    doc_id: Callable[[dict[str, Any]], str]
    parse: Callable[[dict[str, Any]], tuple[ParsedFiling, dict[str, Any]]]
    sort_key: Callable[[dict[str, Any]], tuple[str, ...]]
    section_label: Callable[[str], str]
    # Soft chunk-size budget for this registry's corpus, in Unicode code points.
    # EDGAR keeps the committed 1200-char profile. DART uses 600: a 2026-08-30 sweep
    # over both FY2024 filings measured identical source-span coverage (93.2%) and
    # zero table splits at every candidate in {600, 800, 1000, 1200}, so the smallest
    # candidate wins, and Korean carries roughly twice the information per code point,
    # which keeps the two corpora's chunks comparable in content rather than in chars.
    chunk_target: int


def _edgar_sort_key(entry: dict[str, Any]) -> tuple[str, ...]:
    """Order EDGAR entries by issuer symbol, then report date."""
    return (str(entry.get("ticker", "")), str(entry.get("report_date", "")))


EDGAR: Final[Registry] = Registry(
    name="sec",
    language="en",
    doc_id=doc_id,
    parse=parse_filing,
    sort_key=_edgar_sort_key,
    # "Item 7" is how EDGAR itself names the section, and every committed citation
    # already reads that way.
    section_label="Item {}".format,
    chunk_target=1200,
)

DART: Final[Registry] = Registry(
    name="dart",
    language="ko",
    doc_id=dart_doc_id,
    parse=parse_dart_filing,
    sort_key=dart_sort_key,
    section_label=dart_section_label,
    chunk_target=600,
)

REGISTRIES: Final[Mapping[str, Registry]] = MappingProxyType(
    {registry.name: registry for registry in (EDGAR, DART)}
)


def registry_for(name: str) -> Registry:
    """Return the registry adapter registered under ``name``.

    Raises
    ------
    ValueError
        If no adapter carries that name; seeding a filing under a guessed language
        or chunk profile would corrupt the corpus it lands in.
    """
    registry = REGISTRIES.get(name)
    if registry is None:
        known = ", ".join(sorted(REGISTRIES))
        raise ValueError(f"unknown registry {name!r}; known registries: {known}")
    return registry


def section_label(registry_name_: str, item: str) -> str:
    """Return how one registry names a section code inside a citation.

    An unknown registry falls back to the bare code rather than raising: a citation is
    rendered from an already-parsed filing, so refusing here would fail a run that has
    nothing left to validate.
    """
    registry = REGISTRIES.get(registry_name_)
    return registry.section_label(item) if registry is not None else item


def registry_name(entry: Mapping[str, Any]) -> str:
    """Return the registry an entry names.

    The committed EDGAR manifest predates this key, so an entry without one is EDGAR.
    """
    return str(entry.get("registry", DEFAULT_REGISTRY))


def resolve_registry(entry: Mapping[str, Any]) -> Registry:
    """Return the adapter for the registry an entry names.

    Raises
    ------
    ValueError
        If the entry names a registry this build has no reader for. Guessing would
        parse a filing with another registry's detection rules and still produce a
        contract-shaped result.
    """
    name = registry_name(entry)
    registry = REGISTRIES.get(name)
    if registry is None:
        known = ", ".join(sorted(REGISTRIES))
        raise ValueError(f"unknown registry {name!r}; known registries: {known}")
    return registry
