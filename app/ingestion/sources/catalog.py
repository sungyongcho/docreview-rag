"""Bound the Build acquisition flow to the project's tested filing companies."""

from collections.abc import Iterable
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Literal

from app.ingestion.sources.models import CorpusIdentity, DocumentReference, Manifest


@dataclass(frozen=True, slots=True)
class AcquisitionCompany:
    """Identify an approved issuer independently of downloaded source availability."""

    registry: Literal["sec", "dart"]
    issuer: str
    name: str


ACQUISITION_COMPANIES = (
    AcquisitionCompany("sec", "NVDA", "NVIDIA"),
    AcquisitionCompany("sec", "AMD", "Advanced Micro Devices"),
    AcquisitionCompany("sec", "INTC", "Intel"),
    AcquisitionCompany("sec", "MU", "Micron Technology"),
    AcquisitionCompany("dart", "005930", "Samsung Electronics"),
    AcquisitionCompany("dart", "000660", "SK hynix"),
    AcquisitionCompany("dart", "035420", "NAVER"),
)

# Everyday spellings users type for a catalog company: the name in the other script,
# transliterations, and widely used short forms (삼전, 하닉, 엔비, 암드). Matching is
# case-insensitive (NFKC + casefold), so one spelling covers Samsung/SAMSUNG/samsung.
# Keep every entry unambiguous inside this catalog: the scope index refuses to start
# when two issuers claim one alias. Derogatory nicknames are deliberately excluded.
# These aliases attach only to issuers that have filings in the corpus manifest.
COMPANY_ALIASES: dict[tuple[str, str], tuple[str, ...]] = {
    ("sec", "NVDA"): ("Nvidia", "Nvidia Corporation", "엔비디아", "엔비"),
    ("sec", "AMD"): ("에이엠디", "암드"),
    ("sec", "INTC"): ("Intel Corporation", "인텔"),
    ("sec", "MU"): ("Micron", "마이크론", "마이크론 테크놀로지"),
    ("dart", "005930"): (
        "Samsung",
        "Samsung Electronics Co., Ltd.",
        "삼성",
        "삼성 전자",
        "삼전",
    ),
    ("dart", "000660"): (
        "SK Hynix Inc.",
        "Hynix",
        "SK하이닉스",
        "SK 하이닉스",
        "에스케이하이닉스",
        "하이닉스",
        "하닉",
    ),
    ("dart", "035420"): ("Naver Corporation", "네이버"),
}


def catalog_aliases(registry: str, issuer: str) -> tuple[str, ...]:
    """Return the approved display name plus everyday spellings for one catalog issuer."""
    names = tuple(
        c.name for c in ACQUISITION_COMPANIES if (c.registry, c.issuer) == (registry, issuer)
    )
    return (*names, *COMPANY_ALIASES.get((registry, issuer), ()))


def approved_company(registry: str, issuer: str) -> bool:
    """Accept only exact registry/issuer identities from the tested catalog."""
    return any(c.registry == registry and c.issuer == issuer.upper() for c in ACQUISITION_COMPANIES)


def default_acquisition_draft(*, sample: bool = False) -> dict[str, list]:
    """Return intended sparse pairs, including filings that have not been downloaded."""
    pairs = [
        {"registry": "sec", "issuer": issuer, "year": year}
        for issuer in ("NVDA", "AMD")
        for year in (range(2023, 2025) if sample else range(2019, 2025))
    ]
    if not sample:
        pairs.extend(
            {"registry": "dart", "issuer": issuer, "year": year}
            for issuer in ("005930", "000660")
            for year in range(2022, 2025)
        )
    return {
        "identifiers": sorted({p["issuer"] for p in pairs}),
        "years": sorted({p["year"] for p in pairs}),
        "pairs": pairs,
    }


def read_catalog(path: Path) -> Manifest:
    """Read the canonical manifest or initialize a new corpus identity."""
    if path.name != "manifest.json":
        raise ValueError("acquisition requires the canonical manifest.json")
    if path.exists():
        return Manifest.read(path)
    return Manifest(corpus=CorpusIdentity(corpus_id="filings", name="Filing corpus"))


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


def acquired_catalog(root: Path) -> Manifest | None:
    """Read only the canonical catalog written by the two acquisition adapters."""
    path = root / "manifest.json"
    if path.is_symlink():
        raise ValueError("acquisition manifest must not be a symlink")
    return Manifest.read(path) if path.exists() else None
