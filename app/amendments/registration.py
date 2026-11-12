"""Record the filings a registry holds for each report period."""

from collections.abc import Iterable
from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, FilingVersion
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


def stored_reference(document: Document) -> DocumentReference:
    """Rebuild the manifest entry a stored document was written from."""
    return DocumentReference.model_validate(
        {
            "document_id": document.doc_id,
            "registry": document.filing_registry,
            "language": document.language,
            "issuer": document.issuer,
            "issuer_id": document.issuer_id,
            "aliases": document.aliases,
            "filing_id": document.filing_id,
            "fiscal_year": document.fiscal_year,
            "form": document.form,
            "filing_date": document.filing_date,
            "report_period": document.report_period,
            "source_url": document.source_url,
            "sec": document.sec,
            "dart": document.dart,
        }
    )


async def register_filings(
    session: AsyncSession, documents: Iterable[DocumentReference], *, keep_recorded: bool = False
) -> int:
    """Record every given filing as a version of its report period.

    A filing is recorded as soon as it is known, before it is downloaded or indexed: an
    amendment nobody has reviewed must already withhold the report it amends. Recording
    a filing again refreshes its description and leaves a review in place.

    Parameters
    ----------
    session : AsyncSession
        Open session inside the caller's transaction.
    documents : Iterable[DocumentReference]
        The filings to record.
    keep_recorded : bool
        Leave a filing that is already recorded exactly as it is. A source that may
        know less than the record does, such as a stored document row, passes this.

    Returns
    -------
    int
        How many filings were recorded or refreshed: every given one, or with
        ``keep_recorded`` only those that were not on record yet.
    """
    values = [version_values(document) for document in documents]
    if not values:
        return 0
    statement = insert(FilingVersion).values(values)
    if keep_recorded:
        added = await session.scalars(
            statement.on_conflict_do_nothing().returning(FilingVersion.filing_id)
        )
        return len(added.all())
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


async def register_stored_documents(session: AsyncSession) -> int:
    """Record every stored document as a filing version.

    A database indexed before filing versions existed has documents and no versions,
    and a document without a version is not evidence. This records them from the rows
    themselves, so it needs no source files. A document row keeps what was known when
    it was indexed, which can lack an acceptance time the catalog learned since, so a
    version that is already recorded is left as it is.

    Returns
    -------
    int
        How many stored documents were not on record yet and are recorded now.
    """
    documents = await session.scalars(select(Document).order_by(Document.doc_id))
    return await register_filings(
        session, [stored_reference(document) for document in documents], keep_recorded=True
    )
