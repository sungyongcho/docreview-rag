"""Resolve one corpus manifest entry to the registry adapter that can read it."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

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


def _edgar_sort_key(entry: dict[str, Any]) -> tuple[str, ...]:
    """Order EDGAR entries by issuer symbol, then report date."""
    return (str(entry.get("ticker", "")), str(entry.get("report_date", "")))


EDGAR: Final[Registry] = Registry(
    name="sec",
    language="en",
    doc_id=doc_id,
    parse=parse_filing,
    sort_key=_edgar_sort_key,
)

REGISTRIES: Final[Mapping[str, Registry]] = MappingProxyType({EDGAR.name: EDGAR})


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
