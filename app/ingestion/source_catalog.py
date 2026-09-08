"""Bound the Build acquisition flow to the project's tested filing companies."""

from dataclasses import dataclass
from typing import Literal


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
