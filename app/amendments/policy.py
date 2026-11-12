"""Decide which stored chunks are current evidence once filings have been amended.

One rule serves both registries. A later report replaces every earlier version of its
report period, an amendment accepted before it included; a reviewed amendment admits
and retires single Items; a report period whose versions cannot be ordered, whose
amendment nobody has reviewed, or whose latest report is not indexed, is withheld
whole. ``eligible_chunk`` states the rule in SQL for every query that ranks or reads
chunks, and ``period_hold`` states the withholding part again for one loaded report
period, so that an operator and a reader can be told why evidence is missing.
"""

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Select, and_, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.contracts.evidence import EvidenceHold, HoldReason
from app.db.models import AmendmentEffect, Chunk, Document, FilingVersion

FamilyHold = Literal["amendment_pending", "report_missing", "order_unknown"]
type FamilyKey = tuple[str, str, str]
ADMITTING_ACTIONS = ("replace", "add")
RETIRING_ACTIONS = ("replace", "withhold")
FAMILY_COLUMNS = ("filing_registry", "issuer_id", "report_period")


class EvidenceWithheldError(Exception):
    """Chunks named as evidence are not current evidence any more."""

    def __init__(self, chunk_ids: Collection[int]) -> None:
        self.chunk_ids = tuple(sorted(chunk_ids))
        super().__init__(
            "evidence was replaced or withheld by a later filing: "
            + ", ".join(str(chunk_id) for chunk_id in self.chunk_ids)
        )


def superseded(amendment: FilingVersion, versions: Sequence[FilingVersion]) -> bool:
    """Tell whether a later report replaced an amendment along with the report it amended.

    An amendment can only follow a report, so the first report of its report period
    never replaces it, whatever their order keys say. Any other report accepted after
    the amendment is a whole new version and replaces it.

    Parameters
    ----------
    amendment : FilingVersion
        The amendment to place.
    versions : Sequence[FilingVersion]
        Every recorded version of its report period.
    """
    reports = [version.filed_key for version in versions if version.kind == "report"]
    first = min(reports, default="")
    return any(key > amendment.filed_key and key > first for key in reports)


def family_hold(versions: Sequence[FilingVersion]) -> FamilyHold | None:
    """Return why one report period's evidence is withheld whole, if it is.

    When several reasons hold at once, the one named is the one to settle first: which
    report an amendment follows cannot be told before a report is known and the filings
    are ordered, and a review only matters after that.

    Parameters
    ----------
    versions : Sequence[FilingVersion]
        Every recorded version of one report period.
    """
    if not any(version.kind == "report" for version in versions):
        return "report_missing"
    positions = Counter((version.kind, version.filed_key) for version in versions)
    if any(count > 1 for count in positions.values()):
        return "order_unknown"
    if any(
        version.kind == "amendment"
        and version.reviewed_at is None
        and not superseded(version, versions)
        for version in versions
    ):
        return "amendment_pending"
    return None


def period_hold(members: Sequence[tuple[FilingVersion, bool]]) -> HoldReason | None:
    """Return why a report period's indexed evidence is held whole, if it is.

    Parameters
    ----------
    members : Sequence[tuple[FilingVersion, bool]]
        Every recorded version of one report period, each with whether it is indexed.

    Returns
    -------
    HoldReason | None
        ``family_hold``'s reason, or ``not_indexed`` when the latest report is not
        indexed while an earlier report or an amendment is. ``None`` when nothing is
        held, which includes a report period with no indexed filing: nothing of it was
        evidence.
    """
    if not any(indexed for _, indexed in members):
        return None
    if reason := family_hold([version for version, _ in members]):
        return reason
    _latest, indexed = max(
        (member for member in members if member[0].kind == "report"),
        key=lambda member: member[0].filed_key,
    )
    return None if indexed else "not_indexed"


def _same_family(left: type[FilingVersion], right: type[FilingVersion]) -> ColumnElement[bool]:
    """Match two versions of one report period."""
    return and_(*(getattr(left, name) == getattr(right, name) for name in FAMILY_COLUMNS))


def _held_families() -> Select[str, str, str]:
    """Select the report periods ``period_hold`` withholds, as family keys.

    A report period with no indexed filing is selected too. It has no chunk to keep out.
    """
    version = aliased(FilingVersion)
    family = (version.filing_registry, version.issuer_id, version.report_period)
    is_report = version.kind == "report"
    first_report = func.min(version.filed_key).filter(is_report)
    latest_report = func.max(version.filed_key).filter(is_report)
    latest_unreviewed = func.max(version.filed_key).filter(
        version.kind == "amendment", version.reviewed_at.is_(None)
    )
    indexed = select(Document.doc_id).where(_indexed(version)).exists()
    latest_indexed_report = func.max(version.filed_key).filter(is_report, indexed)
    position = version.kind + ":" + version.filed_key
    return (
        select(*family)
        .group_by(*family)
        .having(
            or_(
                # An unreviewed amendment that no later report replaced (``superseded``):
                # it follows the latest report, or the period has one report to follow.
                latest_unreviewed >= latest_report,
                and_(latest_unreviewed.is_not(None), first_report == latest_report),
                func.count().filter(is_report) == 0,
                func.count(position.distinct()) < func.count(),
                latest_indexed_report.is_distinct_from(latest_report),
            )
        )
    )


def _superseded(amendment: type[FilingVersion]) -> ColumnElement[bool]:
    """Match an amendment a later report replaced, as ``superseded`` decides it."""
    later, first = aliased(FilingVersion), aliased(FilingVersion)
    first_report = (
        select(func.min(first.filed_key))
        .where(_same_family(first, amendment), first.kind == "report")
        .scalar_subquery()
    )
    return (
        select(later.filing_id)
        .where(
            _same_family(later, amendment),
            later.kind == "report",
            later.filed_key > amendment.filed_key,
            later.filed_key > first_report,
        )
        .exists()
    )


def _indexed(version: type[FilingVersion]) -> ColumnElement[bool]:
    """Join a version to the document indexed from it."""
    return and_(
        Document.filing_registry == version.filing_registry,
        Document.filing_id == version.filing_id,
    )


def _not_held(version: type[FilingVersion]) -> ColumnElement[bool]:
    """Keep a version only when its report period is not withheld whole."""
    family = tuple_(*(getattr(version, name) for name in FAMILY_COLUMNS))
    return family.not_in(_held_families())


def _current_reports() -> Select[str]:
    """Select documents of the latest report of each report period that is not withheld."""
    report, later = aliased(FilingVersion), aliased(FilingVersion)
    replaced = (
        select(later.filing_id)
        .where(
            _same_family(later, report),
            later.kind == "report",
            later.filed_key > report.filed_key,
        )
        .exists()
    )
    return (
        select(Document.doc_id)
        .join(report, _indexed(report))
        .where(report.kind == "report", _not_held(report), ~replaced)
    )


def _admitted_items() -> Select[str, str]:
    """Select the (document, Item) pairs a reviewed amendment contributes as evidence."""
    amendment = aliased(FilingVersion)
    return (
        select(Document.doc_id, AmendmentEffect.item)
        .join(amendment, _indexed(amendment))
        .join(
            AmendmentEffect,
            and_(
                AmendmentEffect.filing_registry == amendment.filing_registry,
                AmendmentEffect.filing_id == amendment.filing_id,
            ),
        )
        .where(
            amendment.kind == "amendment",
            _not_held(amendment),
            ~_superseded(amendment),
            AmendmentEffect.action.in_(ADMITTING_ACTIONS),
        )
    )


def _retired_items() -> Select[str, str]:
    """Select the (document, Item) pairs a later amendment took out of evidence.

    An amendment a later report replaced retires nothing: that report is whole.
    """
    amendment, earlier = aliased(FilingVersion), aliased(FilingVersion)
    return (
        select(Document.doc_id, AmendmentEffect.item)
        .select_from(amendment)
        .join(
            AmendmentEffect,
            and_(
                AmendmentEffect.filing_registry == amendment.filing_registry,
                AmendmentEffect.filing_id == amendment.filing_id,
            ),
        )
        .join(
            earlier,
            and_(
                _same_family(earlier, amendment),
                # An amendment that no later report replaced follows every report of the
                # period, and every amendment accepted before it.
                or_(
                    earlier.kind == "report",
                    and_(earlier.kind == "amendment", earlier.filed_key < amendment.filed_key),
                ),
            ),
        )
        .join(Document, _indexed(earlier))
        .where(
            amendment.kind == "amendment",
            ~_superseded(amendment),
            AmendmentEffect.action.in_(RETIRING_ACTIONS),
        )
    )


def eligible_chunk() -> ColumnElement[bool]:
    """Return the predicate that keeps only chunks that are current evidence.

    A chunk is current evidence when its filing is recorded, its report period is not
    withheld, it belongs to the latest report or to an Item a reviewed amendment to
    that report contributes, and no later amendment retired that Item. A chunk outside
    every Item is retired only together with its whole report.

    Notes
    -----
    The three subqueries are uncorrelated and read two small tables, so PostgreSQL
    evaluates each once per statement and the predicate stays cheap inside a ranking
    query that scans many chunks.
    """
    located = tuple_(Chunk.doc_id, Chunk.item)
    return and_(
        or_(Chunk.doc_id.in_(_current_reports()), located.in_(_admitted_items())),
        or_(Chunk.item.is_(None), located.not_in(_retired_items())),
    )


async def eligible_ids(session: AsyncSession, chunk_ids: Collection[int]) -> set[int]:
    """Return which of the given chunks are current evidence right now."""
    if not chunk_ids:
        return set()
    rows = await session.scalars(select(Chunk.id).where(Chunk.id.in_(chunk_ids), eligible_chunk()))
    return set(rows)


async def require_eligible(session: AsyncSession, chunk_ids: Collection[int]) -> None:
    """Refuse chunks that exist but are not current evidence.

    A chunk id that names no stored chunk is not this rule's concern: the caller that
    reads the chunk reports it missing.

    Raises
    ------
    EvidenceWithheldError
        If any stored chunk among ``chunk_ids`` was replaced or is withheld.
    """
    if not chunk_ids:
        return
    stored = set(await session.scalars(select(Chunk.id).where(Chunk.id.in_(chunk_ids))))
    withheld = stored - await eligible_ids(session, stored)
    if withheld:
        raise EvidenceWithheldError(withheld)


async def evidence_holds(
    session: AsyncSession,
    *,
    registries: Collection[str] = (),
    issuers: Collection[str] = (),
    fiscal_years: Collection[int] = (),
    doc_ids: Collection[str] = (),
    within: Sequence[ColumnElement[bool]] = (),
) -> tuple[EvidenceHold, ...]:
    """List the evidence a search over this scope cannot use, and why.

    An empty scope dimension does not restrict. A document scope selects the report
    periods those documents belong to. A report period with no indexed filing is left
    out: nothing of it was ever evidence.

    Parameters
    ----------
    session : AsyncSession
        Open read session.
    registries, issuers, fiscal_years, doc_ids : Collection
        The report periods the search covers.
    within : Sequence[ColumnElement[bool]]
        Any further restriction of the search on ``Chunk`` joined to ``Document``,
        without the evidence rule. With ``doc_ids`` it decides which stored text the
        search could have reached, so that text a later filing replaced is reported
        when the search leaves that filing out, by document, form, Item or otherwise.

    Returns
    -------
    tuple[EvidenceHold, ...]
        One entry per report period withheld whole (an unreviewed amendment, versions
        that cannot be ordered, or a latest report that is not indexed yet). For any
        other report period, one entry for the Items a review left stored text and no
        evidence for, and one with the reason ``replaced`` when the evidence for text
        the search covers is in a filing it leaves out: for the whole period when that
        is true of everything it covers, else for the Items it is true of. Ordered by
        registry, issuer, year.
    """
    scope: list[ColumnElement[bool]] = []
    if registries:
        scope.append(FilingVersion.filing_registry.in_(registries))
    if issuers:
        scope.append(FilingVersion.issuer.in_(issuers))
    if fiscal_years:
        scope.append(FilingVersion.fiscal_year.in_(fiscal_years))
    if doc_ids:
        member = aliased(FilingVersion)
        scope.append(
            tuple_(*(getattr(FilingVersion, name) for name in FAMILY_COLUMNS)).in_(
                select(*(getattr(member, name) for name in FAMILY_COLUMNS))
                .join(Document, _indexed(member))
                .where(Document.doc_id.in_(doc_ids))
            )
        )
    indexed = select(Document.doc_id).where(_indexed(FilingVersion)).scalar_subquery()
    rows = (await session.execute(select(FilingVersion, indexed).where(*scope))).all()
    families: dict[FamilyKey, list[tuple[FilingVersion, bool]]] = {}
    for version, indexed_doc in rows:
        key = (version.filing_registry, version.issuer_id, version.report_period)
        families.setdefault(key, []).append((version, indexed_doc is not None))
    held: dict[FamilyKey, HoldReason | None] = {
        key: period_hold(members) for key, members in families.items()
    }
    # Only another filing of the period takes single Items or documents out of evidence.
    amended = {
        indexed_doc: key
        for version, indexed_doc in rows
        if indexed_doc is not None
        and len(
            families[key := (version.filing_registry, version.issuer_id, version.report_period)]
        )
        > 1
        and held[key] is None
    }
    covered = (*within, Chunk.doc_id.in_(doc_ids)) if doc_ids else tuple(within)
    text = await _text_by_item(session, amended, covered)
    retired = await _items_retired_by_review(
        session, {key: members for key, members in families.items() if key in text}
    )

    found: list[EvidenceHold] = []
    for key, members in families.items():
        # A report period with nothing indexed has no evidence to hold.
        if not any(is_indexed for _, is_indexed in members):
            continue
        named = max(
            (version for version, _ in members),
            key=lambda version: (version.kind == "report", version.filed_key),
        )
        if reason := held[key]:
            found.append(_hold(named, reason))
            continue
        items = text.get(key, {})
        # A review withheld an Item when it left stored text for it and no evidence.
        withheld = tuple(
            item
            for item in retired.get(key, ())
            if (found_text := items.get(item)) and found_text.stored and not found_text.current
        )
        if withheld:
            found.append(_hold(named, "item_withheld", withheld))
        reached = {item: entry for item, entry in items.items() if entry.covered}
        if not reached:
            continue
        # Text the search covers was replaced when the period's evidence for it is
        # elsewhere: in a filing the search leaves out.
        replaced = tuple(
            sorted(
                item
                for item, entry in reached.items()
                if item is not None and entry.current and not entry.covered_current
            )
        )
        if not any(entry.covered_current for entry in reached.values()) and not withheld:
            if any(entry.current for entry in items.values()):
                found.append(_hold(named, "replaced"))
        elif replaced:
            found.append(_hold(named, "replaced", replaced))
    return tuple(sorted(found, key=lambda entry: (entry.registry, entry.issuer, entry.fiscal_year)))


@dataclass(slots=True)
class _ItemText:
    """How many chunks of one Item a report period stores, and how many are evidence.

    ``covered`` and ``covered_current`` count the same within what a search covers.
    """

    stored: int = 0
    current: int = 0
    covered: int = 0
    covered_current: int = 0


async def _text_by_item(
    session: AsyncSession, documents: Mapping[str, FamilyKey], within: Sequence[ColumnElement[bool]]
) -> dict[FamilyKey, dict[str | None, _ItemText]]:
    """Count, per report period and Item, the stored chunks and those that are evidence.

    Parameters
    ----------
    session : AsyncSession
        Open read session.
    documents : Mapping[str, FamilyKey]
        The indexed documents to count, each with its report period.
    within : Sequence[ColumnElement[bool]]
        The search's restriction on ``Chunk`` joined to ``Document``.

    Returns
    -------
    dict[FamilyKey, dict[str | None, _ItemText]]
        The counts of every Item the given documents store text for; ``None`` is the
        text outside every Item.
    """
    if not documents:
        return {}
    current = eligible_chunk()
    rows = await session.execute(
        select(
            Chunk.doc_id,
            Chunk.item,
            func.count(),
            func.count().filter(current),
            func.count().filter(*within) if within else func.count(),
            func.count().filter(current, *within),
        )
        .join(Document, Document.doc_id == Chunk.doc_id)
        .where(Chunk.doc_id.in_(documents))
        .group_by(Chunk.doc_id, Chunk.item)
    )
    text: dict[FamilyKey, dict[str | None, _ItemText]] = {}
    for doc_id, item, stored, is_current, covered, covered_current in rows:
        entry = text.setdefault(documents[doc_id], {}).setdefault(item, _ItemText())
        entry.stored += stored
        entry.current += is_current
        entry.covered += covered
        entry.covered_current += covered_current
    return text


def _hold(version: FilingVersion, reason: HoldReason, items: tuple[str, ...] = ()) -> EvidenceHold:
    """Describe a hold on the report period one of its versions names."""
    return EvidenceHold(
        registry=version.filing_registry,
        issuer=version.issuer,
        fiscal_year=version.fiscal_year,
        reason=reason,
        items=items,
    )


async def _items_retired_by_review(
    session: AsyncSession, families: Mapping[FamilyKey, Sequence[tuple[FilingVersion, bool]]]
) -> dict[FamilyKey, tuple[str, ...]]:
    """Return, per report period, the Items its reviews took earlier text out for.

    Only an amendment that no later report replaced counts: its review is in force.
    """
    amendments = {
        (version.filing_registry, version.filing_id): key
        for key, members in families.items()
        for version, _ in members
        if version.kind == "amendment"
        and not superseded(version, [member for member, _ in members])
    }
    if not amendments:
        return {}
    rows = await session.execute(
        select(AmendmentEffect.filing_registry, AmendmentEffect.filing_id, AmendmentEffect.item)
        .where(
            tuple_(AmendmentEffect.filing_registry, AmendmentEffect.filing_id).in_(
                list(amendments)
            ),
            AmendmentEffect.action.in_(RETIRING_ACTIONS),
        )
        .order_by(AmendmentEffect.item)
    )
    items: dict[FamilyKey, list[str]] = {}
    for registry, filing_id, item in rows:
        items.setdefault(amendments[(registry, filing_id)], []).append(item)
    return {key: tuple(dict.fromkeys(values)) for key, values in items.items()}
