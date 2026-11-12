"""Decide which stored chunks are current evidence once filings have been amended.

One rule serves both registries. A later report replaces every earlier version of its
report period; a reviewed amendment admits and retires single Items; a report period
whose versions cannot be ordered, or whose amendment nobody has reviewed, is withheld
whole. ``eligible_chunk`` states the rule in SQL for every query that ranks or reads
chunks, and ``family_hold`` states the withholding part again for one loaded family, so
that an operator and a reader can be told why evidence is missing.
"""

from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Select, and_, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import AmendmentEffect, Chunk, Document, FilingVersion

HoldReason = Literal["amendment_pending", "report_missing", "order_unknown"]
WithheldReason = Literal[
    "amendment_pending", "report_missing", "order_unknown", "not_indexed", "item_withheld"
]
ADMITTING_ACTIONS = ("replace", "add")
RETIRING_ACTIONS = ("replace", "withhold")
FAMILY_COLUMNS = ("filing_registry", "issuer_id", "report_period")


@dataclass(frozen=True, slots=True)
class WithheldEvidence:
    """Evidence a search could not use, and why, for one issuer's report period.

    ``items`` names the withheld Items; an empty tuple means the whole report period.
    """

    registry: str
    issuer: str
    fiscal_year: int
    reason: WithheldReason
    items: tuple[str, ...] = ()


class EvidenceWithheldError(Exception):
    """Chunks named as evidence are not current evidence any more."""

    def __init__(self, chunk_ids: Collection[int]) -> None:
        self.chunk_ids = tuple(sorted(chunk_ids))
        super().__init__(
            "evidence was replaced or withheld by a later filing: "
            + ", ".join(str(chunk_id) for chunk_id in self.chunk_ids)
        )


def family_hold(versions: Sequence[FilingVersion]) -> HoldReason | None:
    """Return why one report period's evidence is withheld whole, if it is.

    Parameters
    ----------
    versions : Sequence[FilingVersion]
        Every recorded version of one report period.
    """
    if any(version.kind == "amendment" and version.reviewed_at is None for version in versions):
        return "amendment_pending"
    if not any(version.kind == "report" for version in versions):
        return "report_missing"
    positions = Counter((version.kind, version.filed_key) for version in versions)
    if any(count > 1 for count in positions.values()):
        return "order_unknown"
    return None


def _same_family(left: type[FilingVersion], right: type[FilingVersion]) -> ColumnElement[bool]:
    """Match two versions of one report period."""
    return and_(*(getattr(left, name) == getattr(right, name) for name in FAMILY_COLUMNS))


def _held_families() -> Select[tuple[str, str, str]]:
    """Select the report periods ``family_hold`` withholds, as family keys."""
    version = aliased(FilingVersion)
    family = tuple(getattr(version, name) for name in FAMILY_COLUMNS)
    pending = and_(version.kind == "amendment", version.reviewed_at.is_(None))
    position = version.kind + ":" + version.filed_key
    return (
        select(*family)
        .group_by(*family)
        .having(
            or_(
                func.bool_or(pending),
                func.count().filter(version.kind == "report") == 0,
                func.count(position.distinct()) < func.count(),
            )
        )
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


def _current_reports() -> Select[tuple[str]]:
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


def _admitted_items() -> Select[tuple[str, str]]:
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
            AmendmentEffect.action.in_(ADMITTING_ACTIONS),
        )
    )


def _retired_items() -> Select[tuple[str, str]]:
    """Select the (document, Item) pairs a later amendment took out of evidence."""
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
                # An amendment follows its report and every amendment accepted before it.
                or_(
                    earlier.kind == "report",
                    and_(earlier.kind == "amendment", earlier.filed_key < amendment.filed_key),
                ),
            ),
        )
        .join(Document, _indexed(earlier))
        .where(amendment.kind == "amendment", AmendmentEffect.action.in_(RETIRING_ACTIONS))
    )


def eligible_chunk() -> ColumnElement[bool]:
    """Return the predicate that keeps only chunks that are current evidence.

    A chunk is current evidence when its filing is recorded, its report period is not
    withheld, it belongs to the latest report or to an Item a reviewed amendment
    contributes, and no later amendment retired that Item. A chunk outside every Item
    is retired only together with its whole report.

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


async def withheld_evidence(
    session: AsyncSession,
    *,
    registries: Collection[str] = (),
    issuers: Collection[str] = (),
    fiscal_years: Collection[int] = (),
    doc_ids: Collection[str] = (),
) -> tuple[WithheldEvidence, ...]:
    """List the evidence a search over this scope cannot use, and why.

    An empty scope dimension does not restrict. A document scope selects the report
    periods those documents belong to. A report period with no indexed filing is left
    out: nothing of it was ever evidence.

    Returns
    -------
    tuple[WithheldEvidence, ...]
        One entry per report period withheld whole (an unreviewed amendment, versions
        that cannot be ordered, or a newer report that is not indexed yet), and one per
        report period with Items a review withheld. Ordered by registry, issuer, year.
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
    indexed = select(Document.doc_id).where(_indexed(FilingVersion)).exists()
    rows = (await session.execute(select(FilingVersion, indexed).where(*scope))).all()
    families: dict[tuple[str, str, str], list[tuple[FilingVersion, bool]]] = {}
    for version, is_indexed in rows:
        key = (version.filing_registry, version.issuer_id, version.report_period)
        families.setdefault(key, []).append((version, is_indexed))
    withheld_items = await _withheld_items(session, families)

    found: list[WithheldEvidence] = []
    for key, members in families.items():
        versions = [version for version, _ in members]
        named = max(versions, key=lambda version: (version.kind == "report", version.filed_key))
        # A report period with nothing indexed has no evidence to withhold.
        if not any(is_indexed for _, is_indexed in members):
            continue
        reason: WithheldReason | None = family_hold(versions)
        if reason is None:
            named, is_indexed = max(
                (member for member in members if member[0].kind == "report"),
                key=lambda member: member[0].filed_key,
            )
            if not is_indexed:
                reason = "not_indexed"
        if reason is not None:
            found.append(
                WithheldEvidence(named.filing_registry, named.issuer, named.fiscal_year, reason)
            )
        elif items := withheld_items.get(key):
            found.append(
                WithheldEvidence(
                    named.filing_registry, named.issuer, named.fiscal_year, "item_withheld", items
                )
            )
    return tuple(sorted(found, key=lambda entry: (entry.registry, entry.issuer, entry.fiscal_year)))


async def _withheld_items(
    session: AsyncSession, families: dict[tuple[str, str, str], list[tuple[FilingVersion, bool]]]
) -> dict[tuple[str, str, str], tuple[str, ...]]:
    """Return, per report period, the Items its reviews withheld from both filings."""
    amendments = {
        (version.filing_registry, version.filing_id): key
        for key, members in families.items()
        for version, _ in members
        if version.kind == "amendment"
    }
    if not amendments:
        return {}
    rows = await session.execute(
        select(AmendmentEffect.filing_registry, AmendmentEffect.filing_id, AmendmentEffect.item)
        .where(
            tuple_(AmendmentEffect.filing_registry, AmendmentEffect.filing_id).in_(
                list(amendments)
            ),
            AmendmentEffect.action == "withhold",
        )
        .order_by(AmendmentEffect.item)
    )
    items: dict[tuple[str, str, str], list[str]] = {}
    for registry, filing_id, item in rows:
        items.setdefault(amendments[(registry, filing_id)], []).append(item)
    return {key: tuple(dict.fromkeys(values)) for key, values in items.items()}
