"""Record what an operator decided each Item of an amendment does to its report."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AMENDMENT_ACTIONS,
    AmendmentEffect,
    Chunk,
    Document,
    DocumentParse,
    FilingVersion,
    ParsedStructure,
)

AmendmentAction = Literal["replace", "add", "withhold"]
ReviewErrorCode = Literal["not_found", "not_an_amendment", "not_indexed", "invalid_review"]
REVIEW_COLUMNS = ("reviewed_at", "reviewer", "rationale", "reviewed_source_sha256")


@dataclass(frozen=True, slots=True)
class ItemEffect:
    """One Item of an amendment and what the reviewer decided it does."""

    item: str
    action: AmendmentAction


class ReviewError(ValueError):
    """A review that cannot be recorded, with a stable code for the caller."""

    def __init__(self, code: ReviewErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def _indexed_amendment(session: AsyncSession, doc_id: str) -> tuple[FilingVersion, str]:
    """Return an indexed amendment's version and the digest of the source it was parsed from."""
    row = (
        await session.execute(
            select(Document.filing_registry, Document.filing_id, ParsedStructure.source_sha256)
            .join(DocumentParse, DocumentParse.doc_id == Document.doc_id)
            .join(ParsedStructure, ParsedStructure.structure_id == DocumentParse.structure_id)
            .where(Document.doc_id == doc_id)
        )
    ).one_or_none()
    if row is None:
        raise ReviewError("not_indexed", f"{doc_id} is not indexed, so it has no Items to review")
    version = await session.get(FilingVersion, (row.filing_registry, row.filing_id))
    if version is None:
        raise ReviewError("not_found", f"{doc_id} is not a recorded filing")
    if version.kind != "amendment":
        raise ReviewError("not_an_amendment", f"{doc_id} is a whole report and needs no review")
    return version, row.source_sha256


async def amendment_items(session: AsyncSession, doc_id: str) -> tuple[str, ...]:
    """Return the Items an indexed amendment's chunks belong to, as the filing orders them."""
    rows = await session.scalars(
        select(Chunk.item)
        .where(Chunk.doc_id == doc_id, Chunk.item.is_not(None))
        .group_by(Chunk.item)
        .order_by(func.min(Chunk.ordinal))
    )
    return tuple(item for item in rows if item is not None)


async def record_review(
    session: AsyncSession,
    doc_id: str,
    *,
    reviewer: str,
    rationale: str,
    effects: Sequence[ItemEffect],
) -> None:
    """Replace an amendment's review with the given decisions.

    The review must decide every Item the amendment's chunks belong to; otherwise text
    nobody judged would stay outside evidence without a recorded reason. It may also
    name an Item the amendment has no chunks for, to retire the report's text for it.

    Raises
    ------
    ReviewError
        If the document is not an indexed amendment, or the review is incomplete.
    """
    version, source_sha256 = await _indexed_amendment(session, doc_id)
    if not reviewer.strip() or not rationale.strip():
        raise ReviewError("invalid_review", "a review names its reviewer and gives a rationale")
    decided = [effect.item for effect in effects]
    if len(set(decided)) != len(decided):
        raise ReviewError("invalid_review", "a review decides each Item once")
    if unknown := sorted({effect.action for effect in effects} - set(AMENDMENT_ACTIONS)):
        raise ReviewError("invalid_review", f"unknown actions: {', '.join(unknown)}")
    if undecided := sorted(set(await amendment_items(session, doc_id)) - set(decided)):
        raise ReviewError(
            "invalid_review", f"the review leaves Items undecided: {', '.join(undecided)}"
        )
    identity = (
        AmendmentEffect.filing_registry == version.filing_registry,
        AmendmentEffect.filing_id == version.filing_id,
    )
    await session.execute(delete(AmendmentEffect).where(*identity))
    if effects:
        await session.execute(
            insert(AmendmentEffect).values(
                [
                    {
                        "registry": version.filing_registry,
                        "filing_id": version.filing_id,
                        "item": effect.item,
                        "action": effect.action,
                    }
                    for effect in effects
                ]
            )
        )
    version.reviewed_at = datetime.now(UTC)
    version.reviewer = reviewer.strip()
    version.rationale = rationale.strip()
    version.reviewed_source_sha256 = source_sha256
    await session.flush()


async def _clear(session: AsyncSession, versions: Collection[tuple[str, str]]) -> None:
    """Return the given amendments to the unreviewed state."""
    for registry, filing_id in versions:
        identity = (FilingVersion.filing_registry == registry, FilingVersion.filing_id == filing_id)
        await session.execute(
            delete(AmendmentEffect).where(
                AmendmentEffect.filing_registry == registry,
                AmendmentEffect.filing_id == filing_id,
            )
        )
        await session.execute(
            update(FilingVersion).where(*identity).values(dict.fromkeys(REVIEW_COLUMNS))
        )


async def clear_review(session: AsyncSession, doc_id: str) -> None:
    """Withdraw an amendment's review, which withholds its report period again.

    Raises
    ------
    ReviewError
        If the document is not an indexed amendment.
    """
    version, _source = await _indexed_amendment(session, doc_id)
    await _clear(session, [(version.filing_registry, version.filing_id)])
    await session.refresh(version)


async def reset_outdated_reviews(
    session: AsyncSession, doc_ids: Collection[str]
) -> tuple[str, ...]:
    """Withdraw the reviews of re-indexed amendments that no longer describe them.

    A review describes one source and decides the Items found in it. After the
    amendment is indexed from a different source, or its chunks belong to an Item the
    review did not decide, the review is withdrawn and the report period is withheld
    until someone reviews the amendment again.

    Returns
    -------
    tuple[str, ...]
        The documents whose reviews were withdrawn.
    """
    if not doc_ids:
        return ()
    rows = (
        await session.execute(
            select(Document.doc_id, FilingVersion, ParsedStructure.source_sha256)
            .join(
                FilingVersion,
                (FilingVersion.filing_registry == Document.filing_registry)
                & (FilingVersion.filing_id == Document.filing_id),
            )
            .join(DocumentParse, DocumentParse.doc_id == Document.doc_id)
            .join(ParsedStructure, ParsedStructure.structure_id == DocumentParse.structure_id)
            .where(Document.doc_id.in_(doc_ids), FilingVersion.reviewed_at.is_not(None))
        )
    ).all()
    outdated: dict[str, tuple[str, str]] = {}
    for doc_id, version, source_sha256 in rows:
        decided = set(
            await session.scalars(
                select(AmendmentEffect.item).where(
                    AmendmentEffect.filing_registry == version.filing_registry,
                    AmendmentEffect.filing_id == version.filing_id,
                )
            )
        )
        found = set(await amendment_items(session, doc_id))
        if version.reviewed_source_sha256 != source_sha256 or not found <= decided:
            outdated[doc_id] = (version.filing_registry, version.filing_id)
    await _clear(session, list(outdated.values()))
    return tuple(sorted(outdated))
