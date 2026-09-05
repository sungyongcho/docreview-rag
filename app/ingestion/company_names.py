"""Read optional company display names from the existing corpus manifests."""

from collections.abc import Iterable, Mapping
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

type CompanyNames = dict[tuple[str, str], str]


def company_names_from_entries(entries: Iterable[Mapping[str, object]]) -> CompanyNames:
    """Keep source-provided names only when repeated issuer metadata agrees."""
    candidates: dict[tuple[str, str], set[str]] = {}
    for entry in entries:
        issuer = entry.get("issuer") or entry.get("ticker")
        registry = entry.get("registry", "sec")
        if not isinstance(issuer, str) or not isinstance(registry, str):
            continue
        aliases = entry.get("aliases")
        values = [entry.get("issuer_name"), entry.get("company_name"), entry.get("corp_name")]
        if isinstance(aliases, list):
            values.extend(aliases)
        name = next(
            (
                value.strip()
                for value in values
                if isinstance(value, str)
                and value.strip()
                and value.strip().casefold() != issuer.strip().casefold()
            ),
            None,
        )
        if name is not None:
            candidates.setdefault((registry, issuer), set()).add(name)
    return {key: next(iter(names)) for key, names in candidates.items() if len(names) == 1}


def read_company_names(corpus_root: Path) -> CompanyNames:
    """Refresh display metadata without requiring source documents or a database write."""
    entries: list[Mapping[str, object]] = []
    paths = sorted(
        path
        for path in corpus_root.glob("*.json")
        if path.name == "manifest.json" or path.name.endswith("-manifest.json")
    )
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
                raise ValueError("manifest must contain an array of entries")
        except (OSError, UnicodeDecodeError, ValueError) as error:
            logger.warning(
                "Company labels unavailable for %s (%s)", path.name, type(error).__name__
            )
            continue
        entries.extend(payload)
    return company_names_from_entries(entries)
