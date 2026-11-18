"""The question's evidence ledger: every identity a tool returned, merged immutably.

A final answer may cite only what this ledger recorded in the current question. Chunks
are keyed by id with their complete :class:`~app.contracts.evidence.EvidenceCitation`;
table cells are keyed by ref with the identity their content and source version fix.
A key returned twice with different records is marked as a conflict that never heals,
and every path ends the run on it with the wording of :func:`ledger_failure`.
"""

from collections.abc import Iterable, Mapping
import hashlib
from typing import Any

from app.canonical_json import canonical_json
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


def cell_digest(cell: Mapping[str, Any]) -> str:
    """Identify one catalog cell's content, as the question's ledger records it."""
    return hashlib.sha256(canonical_json(dict(cell)).encode()).hexdigest()


def cell_record(cell: dict[str, Any], catalog: dict[str, Any], chunk_id: int) -> dict[str, Any]:
    """Record one returned cell by the identity its content and source version fix."""
    return {
        "chunk_id": chunk_id,
        "stable_key": catalog["stable_key"],
        "resolver_identity": catalog["resolver_identity"],
        "digest": cell_digest(cell),
    }


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
