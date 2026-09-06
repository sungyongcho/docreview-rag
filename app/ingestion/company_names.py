"""Read optional company display names from the existing corpus manifests."""

from collections.abc import Iterable
import logging
from pathlib import Path

from app.ingestion.manifest import DocumentReference, Manifest

logger = logging.getLogger(__name__)

type CompanyNames = dict[tuple[str, str], str]


def company_names_from_entries(entries: Iterable[DocumentReference]) -> CompanyNames:
    """Keep source aliases only when repeated typed issuer metadata agrees."""
    candidates: dict[tuple[str, str], set[str]] = {}
    for document in entries:
        name = next(
            (
                alias.strip()
                for alias in document.aliases
                if alias.strip() and alias.strip().casefold() != document.issuer.casefold()
            ),
            None,
        )
        if name is not None:
            candidates.setdefault((document.registry, document.issuer), set()).add(name)
    return {key: next(iter(names)) for key, names in candidates.items() if len(names) == 1}


def read_company_names(corpus_root: Path) -> CompanyNames:
    """Read optional display aliases from the single canonical manifest."""
    path = corpus_root / "manifest.json"
    try:
        manifest = Manifest.read(path)
    except (OSError, UnicodeError, ValueError) as error:
        logger.warning("Company labels unavailable for %s (%s)", path.name, type(error).__name__)
        return {}
    return company_names_from_entries(manifest.documents)
