"""Question-scoped immutable identity merging for every agent execution path."""

from collections.abc import Iterable, Mapping
from typing import Any

from app.contracts.evidence import EvidenceCitation


def merge_identities[K](
    left: Mapping[K, dict[str, Any]] | None, right: Mapping[K, dict[str, Any]] | None
) -> dict[K, dict[str, Any]]:
    """Keep identical repeats, mark disagreements irreversibly, or reset on ``None``."""
    if right is None:
        return {}
    merged = dict(left or {})
    for key, record in right.items():
        known = merged.get(key)
        merged[key] = record if known is None or known == record else {"conflict": True}
    return merged


def citation_records(citations: Iterable[EvidenceCitation]) -> dict[int, dict[str, Any]]:
    """Record all returned identities without losing duplicate-key disagreements."""
    records: dict[int, dict[str, Any]] = {}
    for citation in citations:
        records = merge_identities(records, {citation.chunk_id: citation.model_dump(mode="json")})
    return records


def ledger_failure[K](ledger: Mapping[K, dict[str, Any]], *, cells: bool = False) -> str | None:
    """Describe the first identity conflict, using the same wording on every path."""
    for key, record in ledger.items():
        if record.get("conflict"):
            return (
                f"conflicting stored content for cell {key}"
                if cells
                else f"conflicting immutable identity for chunk {key}"
            )
    return None
