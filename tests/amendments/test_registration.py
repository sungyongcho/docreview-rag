"""How a manifest entry is recorded as a version of its report period."""

import asyncio
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.amendments.registration import (
    filed_key,
    register_filings,
    register_stored_documents,
)
from app.amendments.review import ItemEffect, record_review
from app.db.models import AmendmentEffect, FilingVersion
from app.ingestion.persistence import persist_seed_batch
from tests.amendments.support import (
    amendment_document,
    batch,
    dart_document,
    parsed,
    sec_document,
)
from tests.live_postgres import isolated_session


def test_the_order_key_is_the_receipt_number_or_the_acceptance_time() -> None:
    """An entry with no recorded acceptance time sorts at the start of its filing day."""
    assert filed_key(dart_document("20210330000776")) == "20210330000776"
    assert filed_key(amendment_document(21)) == "20260204200657"
    assert filed_key(sec_document(18, filed=date(2026, 2, 4))) == "20260204000000"


def test_an_entry_without_an_acceptance_time_serializes_as_before() -> None:
    """Existing manifests and stored documents must not change when the field is unset."""
    assert "accepted_at" not in sec_document(18).model_dump(mode="json")["sec"]
    assert amendment_document(21).model_dump(mode="json")["sec"]["accepted_at"] == (
        "2026-02-04T20:06:57Z"
    )


@pytest.mark.live_postgres
def test_recording_a_filing_again_keeps_its_review() -> None:
    """A later acquisition or ingestion refreshes the description, not the decision."""

    async def scenario() -> None:
        async with isolated_session() as session:
            report, amendment = sec_document(18), amendment_document(21)
            await persist_seed_batch(
                session, batch(parsed(report, ("7",)), parsed(amendment, ("7",)))
            )
            await record_review(
                session,
                amendment.document_id,
                reviewer="operator",
                rationale="Item 7 restated in full.",
                effects=[ItemEffect("7", "replace")],
            )
            await session.commit()

            renamed = amendment.model_copy(update={"issuer": "AMDX"})
            assert await register_filings(session, [report, renamed]) == 2
            await session.commit()

            version = await session.get(FilingVersion, ("sec", amendment.filing_id))
            assert version is not None
            assert (version.issuer, version.reviewer) == ("AMDX", "operator")
            assert (await session.scalars(select(AmendmentEffect.action))).all() == ["replace"]
            assert await register_filings(session, []) == 0

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_stored_documents_fill_missing_versions_without_changing_recorded_ones() -> None:
    """A stored row that lacks an acceptance time does not undo one the catalog learned."""

    async def scenario() -> None:
        async with isolated_session() as session:
            report = sec_document(18)
            await persist_seed_batch(session, batch(parsed(report, ("7",))))
            accepted = datetime(2026, 2, 4, 21, 30, 0, tzinfo=UTC)
            assert report.sec is not None
            timed = report.model_copy(
                update={"sec": report.sec.model_copy(update={"accepted_at": accepted})}
            )
            await register_filings(session, [timed])
            await session.commit()

            assert await register_stored_documents(session) == 0
            await session.commit()
            version = await session.get(FilingVersion, ("sec", report.filing_id))
            assert version is not None
            assert version.filed_key == "20260204213000"

            await session.delete(version)
            await session.commit()
            assert await register_stored_documents(session) == 1
            await session.commit()
            restored = await session.get(FilingVersion, ("sec", report.filing_id))
            assert restored is not None
            assert restored.filed_key == "20260204000000"

    asyncio.run(scenario())
