"""Resolve one corpus manifest entry to the registry adapter that can read it."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from app.ingestion.dart import dart_section_label, parse_dart_filing
from app.ingestion.edgar import edgar_section_label, parse_filing
from app.ingestion.manifest import FilingSource
from app.ingestion.parser import ParsedFiling


@dataclass(frozen=True, slots=True)
class Registry:
    """The readers one publishing registry supplies for its own manifest entries.

    Each adapter receives the same verified ``FilingSource`` contract. Only source
    markup parsing and citation labels vary by publishing registry; document identity,
    source decoding, selections, and processing budgets are shared.
    """

    name: str
    language: str
    parse: Callable[[FilingSource], tuple[ParsedFiling, dict[str, Any]]]
    section_label: Callable[[str], str]


EDGAR: Final[Registry] = Registry(
    name="sec",
    language="en",
    parse=parse_filing,
    section_label=edgar_section_label,
)

DART: Final[Registry] = Registry(
    name="dart",
    language="ko",
    parse=parse_dart_filing,
    section_label=dart_section_label,
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


def resolve_registry(source: FilingSource) -> Registry:
    """Resolve the explicit publishing registry of a selected typed source."""
    return registry_for(source.document.registry)
