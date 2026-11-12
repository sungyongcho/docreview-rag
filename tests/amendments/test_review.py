"""Recording, withdrawing and outdating an operator's review of an amendment."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.amendments.registration import register_filings
from app.amendments.review import ItemEffect, ReviewError, clear_review, record_review
from app.db.models import FilingVersion
from app.ingestion.persistence import persist_seed_batch
from tests.amendments.support import amendment_document, batch, eligible, parsed, sec_document
from tests.live_postgres import isolated_session

REPORT = sec_document(18)
AMENDMENT = amendment_document(21)


async def review(session: AsyncSession, doc_id: str, *effects: ItemEffect, by: str = "operator"):
    """Record a review with a fixed rationale and commit it."""
    await record_review(
        session, doc_id, reviewer=by, rationale="Read against the original.", effects=effects
    )
    await session.commit()


@pytest.mark.live_postgres
def test_a_review_must_be_complete_and_about_an_indexed_amendment() -> None:
    """Each refusal carries the code the operator surface reports."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(
                session, batch(parsed(REPORT, ("7", "15")), parsed(AMENDMENT, ("7", "15")))
            )
            later = amendment_document(30, hour=22)
            await register_filings(session, [later])
            await session.commit()
            replace = ItemEffect("7", "replace")

            refusals = {
                "not_an_amendment": (REPORT.document_id, (replace,), "operator"),
                "not_indexed": (later.document_id, (replace,), "operator"),
                "invalid_review": (AMENDMENT.document_id, (replace,), "operator"),
            }
            for code, (doc_id, effects, reviewer) in refusals.items():
                with pytest.raises(ReviewError) as refused:
                    await review(session, doc_id, *effects, by=reviewer)
                assert refused.value.code == code
                await session.rollback()
            with pytest.raises(ReviewError, match="undecided: 15"):
                await review(session, AMENDMENT.document_id, replace)
            await session.rollback()
            with pytest.raises(ReviewError, match="each Item once"):
                await review(session, AMENDMENT.document_id, replace, ItemEffect("7", "add"))
            await session.rollback()
            with pytest.raises(ReviewError, match="names its reviewer"):
                await review(
                    session, AMENDMENT.document_id, replace, ItemEffect("15", "add"), by=" "
                )

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_a_review_replaces_the_previous_one_and_can_be_withdrawn() -> None:
    """The last recorded review is the one in force; withdrawing it withholds again."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(
                session, batch(parsed(REPORT, ("1", "7")), parsed(AMENDMENT, ("7",)))
            )
            await session.rollback()
            await review(session, AMENDMENT.document_id, ItemEffect("7", "add"))
            assert (REPORT.document_id, "7") in await eligible(session)
            await session.rollback()

            await review(session, AMENDMENT.document_id, ItemEffect("7", "replace"), by="second")
            assert await eligible(session) == {
                (REPORT.document_id, "1"),
                (AMENDMENT.document_id, "7"),
            }
            version = await session.get(FilingVersion, ("sec", AMENDMENT.filing_id))
            assert version is not None and version.reviewer == "second"
            assert version.reviewed_source_sha256 == "a" * 64

            await clear_review(session, AMENDMENT.document_id)
            await session.commit()
            assert version.reviewed_at is None
            assert await eligible(session) == set()

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_indexing_an_amendment_again_keeps_or_withdraws_its_review() -> None:
    """Same source and Items keep the review; a new source or a new Item withdraws it."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(
                session, batch(parsed(REPORT, ("1", "7")), parsed(AMENDMENT, ("7",)))
            )
            await session.rollback()
            await review(session, AMENDMENT.document_id, ItemEffect("7", "replace"))
            reviewed = {(REPORT.document_id, "1"), (AMENDMENT.document_id, "7")}

            await persist_seed_batch(session, batch(parsed(AMENDMENT, ("7",))))
            assert await eligible(session) == reviewed
            await session.rollback()

            await persist_seed_batch(session, batch(parsed(AMENDMENT, ("7", "9A"))))
            assert await eligible(session) == set()
            await session.rollback()

            await review(
                session, AMENDMENT.document_id, ItemEffect("7", "replace"), ItemEffect("9A", "add")
            )
            await persist_seed_batch(session, batch(parsed(AMENDMENT, ("7", "9A"), digest="b")))
            assert await eligible(session) == set()

    asyncio.run(scenario())
