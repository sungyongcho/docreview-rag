"""Resolve one corpus manifest entry to the registry adapter that can read it."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from app.ingestion.dart import dart_section_label, dart_section_title, parse_dart_filing
from app.ingestion.edgar import edgar_section_label, edgar_section_title, parse_filing
from app.ingestion.manifest import FilingSource
from app.ingestion.parser import ParsedFiling


@dataclass(frozen=True, slots=True)
class Registry:
    """The readers one publishing registry supplies for its own manifest entries.

    Each adapter receives the same verified ``FilingSource`` contract. Only source
    markup parsing, citation labels, and section titles vary by publishing registry;
    document identity, source decoding, selections, and processing budgets are shared.
    """

    name: str
    language: str
    parse: Callable[[FilingSource], tuple[ParsedFiling, dict[str, Any]]]
    section_label: Callable[[str], str]
    section_title: Callable[[str], str | None]


EDGAR: Final[Registry] = Registry(
    name="sec",
    language="en",
    parse=parse_filing,
    section_label=edgar_section_label,
    section_title=edgar_section_title,
)

DART: Final[Registry] = Registry(
    name="dart",
    language="ko",
    parse=parse_dart_filing,
    section_label=dart_section_label,
    section_title=dart_section_title,
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


def section_title(item: str | None, registry_name_: str | None = None) -> str | None:
    """Return the registry's own title for a section code, or ``None`` when it has none.

    A caller that knows the publishing registry consults only that adapter, so a DART
    numeral never borrows an EDGAR title. Without a known registry every adapter is tried
    in registration order; the code spaces are disjoint (EDGAR codes start with a digit,
    DART codes are Roman numerals), so the first match is the only possible match.
    """
    if not item:
        return None
    registry = REGISTRIES.get(registry_name_) if registry_name_ is not None else None
    if registry is not None:
        return registry.section_title(item)
    for candidate in REGISTRIES.values():
        title = candidate.section_title(item)
        if title:
            return title
    return None


def resolve_registry(source: FilingSource) -> Registry:
    """Resolve the explicit publishing registry of a selected typed source."""
    return registry_for(source.document.registry)
