"""Which stored chunks stay current evidence once a report period has several filings."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.amendments.policy import (
    EvidenceWithheldError,
    WithheldEvidence,
    eligible_ids,
    family_hold,
    require_eligible,
    withheld_evidence,
)
from app.amendments.registration import register_filings
from app.amendments.review import ItemEffect, record_review
from app.db.models import Chunk, FilingVersion
from app.ingestion.persistence import persist_seed_batch
from tests.amendments.support import (
    amendment_document,
    batch,
    dart_document,
    eligible,
    parsed,
    sec_document,
)
from tests.live_postgres import isolated_session

REPORT = sec_document(18)
AMENDMENT = amendment_document(21)
LATER_AMENDMENT = amendment_document(30, hour=22)
ORIGINAL = dart_document("20210322000782")
CORRECTION = dart_document("20210330000776")


def version(kind: str, filed_key: str, *, reviewed: bool = False) -> FilingVersion:
    """Build an unsaved version carrying only what the hold rule reads."""
    return FilingVersion(
        kind=kind, filed_key=filed_key, reviewed_at=datetime.now(UTC) if reviewed else None
    )


def test_a_report_period_is_withheld_until_its_versions_are_settled() -> None:
    """An unreviewed amendment, a missing report and an unknown order each withhold."""
    report = version("report", "20260204000000")

    assert family_hold([report]) is None
    assert family_hold([report, version("amendment", "20260204200657")]) == "amendment_pending"
    assert family_hold([report, version("amendment", "20260204200657", reviewed=True)]) is None
    assert family_hold([version("amendment", "20260204200657", reviewed=True)]) == "report_missing"
    assert family_hold([report, version("report", "20260204000000")]) == "order_unknown"


@pytest.mark.live_postgres
def test_only_a_recorded_filing_is_evidence() -> None:
    """A report is evidence once indexed, and stops being evidence without its record."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(session, batch(parsed(REPORT, ("1", "7", None))))
            assert await eligible(session) == {
                (REPORT.document_id, "1"),
                (REPORT.document_id, "7"),
                (REPORT.document_id, None),
            }
            assert await withheld_evidence(session) == ()

            await session.execute(delete(FilingVersion))
            assert await eligible(session) == set()

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_a_later_report_replaces_the_whole_earlier_report() -> None:
    """A DART correction retires its original as soon as it is known, indexed or not."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(session, batch(parsed(ORIGINAL, ("I", "II", None))))
            await register_filings(session, [CORRECTION])
            await session.commit()

            assert await eligible(session) == set()
            assert await withheld_evidence(session, issuers=["000660"]) == (
                WithheldEvidence("dart", "000660", 2020, "not_indexed"),
            )

            await session.rollback()
            await persist_seed_batch(session, batch(parsed(CORRECTION, ("I", "II"))))
            assert await eligible(session) == {
                (CORRECTION.document_id, "I"),
                (CORRECTION.document_id, "II"),
            }
            assert await withheld_evidence(session) == ()

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_an_unreviewed_amendment_withholds_its_report_period() -> None:
    """Knowing of an amendment is enough to withhold; indexing it does not release."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(session, batch(parsed(REPORT, ("1", "7"))))
            await register_filings(session, [AMENDMENT])
            await session.commit()
            pending = (WithheldEvidence("sec", "AMD", 2025, "amendment_pending"),)

            assert await eligible(session) == set()
            assert await withheld_evidence(session, fiscal_years=[2025]) == pending
            assert await withheld_evidence(session, doc_ids=[REPORT.document_id]) == pending
            assert await withheld_evidence(session, fiscal_years=[2024]) == ()

            await session.rollback()
            await persist_seed_batch(session, batch(parsed(AMENDMENT, ("7", "15"))))
            assert await eligible(session) == set()

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_a_review_decides_each_item() -> None:
    """Replace swaps the Item, add keeps both, withhold removes both, the rest stays."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(
                session,
                batch(parsed(REPORT, ("1", "7", "8", "15", None)), parsed(AMENDMENT, ("7", "15"))),
            )
            await record_review(
                session,
                AMENDMENT.document_id,
                reviewer="operator",
                rationale="Item 7 restated in full; Item 8 only in part.",
                effects=[
                    ItemEffect("7", "replace"),
                    ItemEffect("15", "add"),
                    ItemEffect("8", "withhold"),
                ],
            )
            await session.commit()

            assert await eligible(session) == {
                (REPORT.document_id, "1"),
                (REPORT.document_id, "15"),
                (REPORT.document_id, None),
                (AMENDMENT.document_id, "7"),
                (AMENDMENT.document_id, "15"),
            }
            assert await withheld_evidence(session) == (
                WithheldEvidence("sec", "AMD", 2025, "item_withheld", ("8",)),
            )

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_a_later_amendment_retires_an_earlier_amendment_item() -> None:
    """Amendments apply in acceptance order, each over everything accepted before it."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(
                session,
                batch(
                    parsed(REPORT, ("1", "7")),
                    parsed(AMENDMENT, ("7",)),
                    parsed(LATER_AMENDMENT, ("7",)),
                ),
            )
            for document in (AMENDMENT, LATER_AMENDMENT):
                await record_review(
                    session,
                    document.document_id,
                    reviewer="operator",
                    rationale="Item 7 restated in full.",
                    effects=[ItemEffect("7", "replace")],
                )
            await session.commit()

            assert await eligible(session) == {
                (REPORT.document_id, "1"),
                (LATER_AMENDMENT.document_id, "7"),
            }

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_versions_that_cannot_be_ordered_or_lack_a_report_are_withheld() -> None:
    """Two reports accepted at one time, and an amendment alone, are both withheld."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(
                session, batch(parsed(REPORT, ("1",)), parsed(sec_document(19), ("1",)))
            )
            assert await eligible(session) == set()
            assert await withheld_evidence(session) == (
                WithheldEvidence("sec", "AMD", 2025, "order_unknown"),
            )

        async with isolated_session() as session:
            await persist_seed_batch(session, batch(parsed(AMENDMENT, ("7",))))
            await record_review(
                session,
                AMENDMENT.document_id,
                reviewer="operator",
                rationale="Item 7 restated in full.",
                effects=[ItemEffect("7", "replace")],
            )
            await session.commit()
            assert await eligible(session) == set()
            assert await withheld_evidence(session) == (
                WithheldEvidence("sec", "AMD", 2025, "report_missing"),
            )

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_named_chunks_are_refused_once_they_are_replaced() -> None:
    """A chunk id read back later is checked against the policy as it stands then."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(session, batch(parsed(REPORT, ("1", "7"))))
            rows = await session.execute(select(Chunk.item, Chunk.id))
            ids = {item: chunk_id for item, chunk_id in rows}
            await session.commit()
            await require_eligible(session, [*ids.values(), 10**9])

            await session.rollback()
            await persist_seed_batch(session, batch(parsed(AMENDMENT, ("7",))))
            await record_review(
                session,
                AMENDMENT.document_id,
                reviewer="operator",
                rationale="Item 7 restated in full.",
                effects=[ItemEffect("7", "replace")],
            )
            await session.commit()

            assert await eligible_ids(session, ids.values()) == {ids["1"]}
            with pytest.raises(EvidenceWithheldError) as refused:
                await require_eligible(session, ids.values())
            assert refused.value.chunk_ids == (ids["7"],)

    asyncio.run(scenario())
