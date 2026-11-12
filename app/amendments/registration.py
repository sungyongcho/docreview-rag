"""Record the filings a registry holds for each report period."""

from collections.abc import Iterable
from datetime import UTC
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FilingVersion
from app.ingestion.sources.models import DocumentReference


def filed_key(document: DocumentReference) -> str:
    """Return the fourteen digits that order this filing among others of its kind.

    A DART receipt number is the receipt date followed by that day's sequence. EDGAR
    states when it accepted a filing; a manifest entry written before that was recorded
    has only its filing date, which sorts at the start of that day.
    """
    if document.dart is not None:
        return document.dart.receipt_number
    accepted = document.sec.accepted_at if document.sec is not None else None
    if accepted is not None:
        return accepted.astimezone(UTC).strftime("%Y%m%d%H%M%S")
    return document.filing_date.strftime("%Y%m%d") + "000000"


def version_values(document: DocumentReference) -> dict[str, Any]:
    """Project one manifest entry onto the columns that describe a filing version."""
    return {
        "registry": document.registry,
        "filing_id": document.filing_id,
        "issuer_id": document.issuer_id,
        "report_period": document.report_period.isoformat(),
        "issuer": document.issuer,
        "fiscal_year": document.fiscal_year,
        "form": document.form,
        "filing_date": document.filing_date.isoformat(),
        "kind": document.kind,
        "filed_key": filed_key(document),
    }


async def register_filings(session: AsyncSession, documents: Iterable[DocumentReference]) -> int:
    """Record every given filing as a version of its report period.

    A filing is recorded as soon as it is known, before it is downloaded or indexed: an
    amendment nobody has reviewed must already withhold the report it amends. Recording
    a filing again refreshes its description and leaves a review in place.

    Returns
    -------
    int
        How many filings were given.
    """
    values = [version_values(document) for document in documents]
    if not values:
        return 0
    statement = insert(FilingVersion).values(values)
    described = (
        "issuer_id",
        "report_period",
        "issuer",
        "fiscal_year",
        "form",
        "filing_date",
        "kind",
        "filed_key",
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[FilingVersion.filing_registry, FilingVersion.filing_id],
            set_={name: statement.excluded[name] for name in described},
        )
    )
    return len(values)
