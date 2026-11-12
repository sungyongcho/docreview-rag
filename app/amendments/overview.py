"""Show an operator the report periods that have more than one filing to weigh."""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.amendments.policy import eligible_chunk, period_hold
from app.amendments.review import AmendmentAction
from app.contracts.evidence import HoldReason
from app.contracts.validation import NonBlank, NonNegativeInt, PositiveInt, StrictSchema
from app.db.models import (
    AmendmentEffect,
    Chunk,
    Document,
    DocumentParse,
    FilingVersion,
    ParsedStructure,
)

type IndexedFiling = tuple[FilingVersion, str | None, str | None, str | None]


class ItemDecision(StrictSchema):
    """What a review decided one Item of an amendment does to the filings before it."""

    item: NonBlank
    action: AmendmentAction


class ItemChunks(StrictSchema):
    """How many indexed chunks of one filing belong to one Item."""

    item: NonBlank
    chunks: PositiveInt


class ReviewRecord(StrictSchema):
    """Who reviewed an amendment, when, why, and what they decided."""

    reviewed_at: datetime
    reviewer: NonBlank
    rationale: NonBlank
    decisions: tuple[ItemDecision, ...]


class FilingVersionView(StrictSchema):
    """One filing of a report period, with what is indexed from it.

    ``doc_id``, ``source_url`` and ``parse_status`` are ``None`` until the filing is
    indexed. A ``parse_status`` other than ``parsed`` means the parser could not bound
    every Item, so the Items listed may be incomplete. ``items`` lists its Items in the
    order the filing sets them out, and ``current`` says whether any of its chunks is
    evidence right now.
    """

    filing_id: NonBlank
    form: NonBlank
    kind: Literal["report", "amendment"]
    filing_date: NonBlank
    doc_id: NonBlank | None
    source_url: NonBlank | None
    parse_status: NonBlank | None
    items: tuple[ItemChunks, ...]
    unnumbered_chunks: NonNegativeInt
    current: bool
    review: ReviewRecord | None


class ReportPeriodView(StrictSchema):
    """Every recorded filing of one issuer's report period, oldest first.

    ``hold`` is why the whole period is kept out of evidence, when it is.
    """

    registry: NonBlank
    issuer: NonBlank
    fiscal_year: PositiveInt
    report_period: NonBlank
    hold: HoldReason | None
    versions: tuple[FilingVersionView, ...]


def _in_policy_order(members: Sequence[IndexedFiling]) -> list[IndexedFiling]:
    """Order a period's filings as the policy applies them.

    Filings follow their order keys, and an amendment follows a report it shares a key
    with. An amendment is never listed before the first report: it can only amend one.
    """
    first = min(
        (version.filed_key for version, *_ in members if version.kind == "report"), default=""
    )
    return sorted(
        members,
        key=lambda member: (max(member[0].filed_key, first), member[0].kind == "amendment"),
    )


def _in_filing_order(
    decisions: Sequence[ItemDecision], stored: Sequence[ItemChunks]
) -> tuple[ItemDecision, ...]:
    """Order a review's decisions as the filing sets out its Items.

    A decision for an Item the filing has no text for follows them, by Item code.
    """
    place = {entry.item: index for index, entry in enumerate(stored)}
    return tuple(
        sorted(
            decisions, key=lambda decision: (place.get(decision.item, len(place)), decision.item)
        )
    )


async def amended_report_periods(
    session: AsyncSession, *, doc_id: str | None = None
) -> tuple[ReportPeriodView, ...]:
    """List the report periods that hold an amendment or more than one filing.

    Parameters
    ----------
    session : AsyncSession
        Open read session.
    doc_id : str | None
        Restrict the list to the report period this indexed document belongs to.

    Returns
    -------
    tuple[ReportPeriodView, ...]
        Report periods ordered by registry, issuer and descending fiscal year. A period
        with a single unamended report is left out: it has nothing to weigh.
    """
    statement = (
        select(FilingVersion, Document.doc_id, Document.source_url, ParsedStructure.parse_status)
        .outerjoin(
            Document,
            (Document.filing_registry == FilingVersion.filing_registry)
            & (Document.filing_id == FilingVersion.filing_id),
        )
        .outerjoin(DocumentParse, DocumentParse.doc_id == Document.doc_id)
        .outerjoin(ParsedStructure, ParsedStructure.structure_id == DocumentParse.structure_id)
    )
    families: dict[tuple[str, str, str], list[IndexedFiling]] = {}
    for version, indexed_doc, source_url, parse_status in (await session.execute(statement)).all():
        key = (version.filing_registry, version.issuer_id, version.report_period)
        families.setdefault(key, []).append((version, indexed_doc, source_url, parse_status))
    listed = {
        key: _in_policy_order(members)
        for key, members in families.items()
        if (len(members) > 1 or any(member[0].kind == "amendment" for member in members))
        and (doc_id is None or any(member[1] == doc_id for member in members))
    }
    doc_ids = [member[1] for members in listed.values() for member in members if member[1]]
    filing_ids = [
        (member[0].filing_registry, member[0].filing_id)
        for members in listed.values()
        for member in members
    ]
    items: dict[str, list[ItemChunks]] = {}
    unnumbered: dict[str, int] = {}
    current: set[str] = set()
    decisions: dict[tuple[str, str], list[ItemDecision]] = {}
    if doc_ids:
        first = func.min(Chunk.ordinal)
        rows = await session.execute(
            select(Chunk.doc_id, Chunk.item, func.count())
            .where(Chunk.doc_id.in_(doc_ids))
            .group_by(Chunk.doc_id, Chunk.item)
            .order_by(Chunk.doc_id, first)
        )
        for chunk_doc, item, count in rows:
            if item is None:
                unnumbered[chunk_doc] = count
            else:
                items.setdefault(chunk_doc, []).append(ItemChunks(item=item, chunks=count))
        current = set(
            await session.scalars(
                select(Chunk.doc_id).where(Chunk.doc_id.in_(doc_ids), eligible_chunk()).distinct()
            )
        )
    if filing_ids:
        rows = await session.execute(
            select(AmendmentEffect)
            .where(
                tuple_(AmendmentEffect.filing_registry, AmendmentEffect.filing_id).in_(filing_ids)
            )
            .order_by(AmendmentEffect.item)
        )
        for effect in rows.scalars():
            decisions.setdefault((effect.filing_registry, effect.filing_id), []).append(
                ItemDecision(item=effect.item, action=effect.action)  # pyright: ignore[reportArgumentType]
            )

    periods = []
    for members in listed.values():
        named = members[0][0]
        periods.append(
            ReportPeriodView(
                registry=named.filing_registry,
                issuer=named.issuer,
                fiscal_year=named.fiscal_year,
                report_period=named.report_period,
                hold=period_hold([(member[0], member[1] is not None) for member in members]),
                versions=tuple(
                    FilingVersionView(
                        filing_id=version.filing_id,
                        form=version.form,
                        kind=version.kind,  # pyright: ignore[reportArgumentType]
                        filing_date=version.filing_date,
                        doc_id=doc,
                        source_url=source_url,
                        parse_status=parse_status,
                        items=tuple(items.get(doc or "", ())),
                        unnumbered_chunks=unnumbered.get(doc or "", 0),
                        current=doc in current,
                        review=(
                            None
                            if version.reviewed_at is None
                            else ReviewRecord(
                                reviewed_at=version.reviewed_at,
                                reviewer=version.reviewer or "",
                                rationale=version.rationale or "",
                                decisions=_in_filing_order(
                                    decisions.get((version.filing_registry, version.filing_id), ()),
                                    items.get(doc or "", ()),
                                ),
                            )
                        ),
                    )
                    for version, doc, source_url, parse_status in members
                ),
            )
        )
    return tuple(
        sorted(periods, key=lambda period: (period.registry, period.issuer, -period.fiscal_year))
    )
