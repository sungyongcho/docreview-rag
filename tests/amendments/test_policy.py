"""Which stored chunks stay current evidence once a report period has several filings."""

import asyncio
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, select

from app.amendments.policy import (
    EvidenceWithheldError,
    eligible_ids,
    evidence_holds,
    family_hold,
    require_eligible,
    superseded,
)
from app.amendments.registration import register_filings
from app.amendments.review import ItemEffect, record_review
from app.db.models import Chunk, Document, FilingVersion
from app.ingestion.persistence import persist_seed_batch
from tests.amendments.support import (
    amendment_document,
    batch,
    dart_document,
    eligible,
    hold,
    parsed,
    sec_document,
)
from tests.live_postgres import isolated_session

REPORT = sec_document(18)
AMENDMENT = amendment_document(21)
LATER_AMENDMENT = amendment_document(30, hour=22)
REFILED_REPORT = sec_document(
    40, filed=date(2026, 3, 2), accepted=datetime(2026, 3, 2, 21, 0, 0, tzinfo=UTC)
)
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
    # What must be settled first is named first: a review cannot place an amendment
    # before its report is known and the filings are ordered.
    pending = version("amendment", "20260204200657")
    assert family_hold([pending]) == "report_missing"
    assert family_hold([report, version("report", "20260204000000"), pending]) == "order_unknown"


def test_a_later_report_replaces_an_amendment_accepted_before_it() -> None:
    """Only a report other than the period's first can replace an amendment."""
    first = version("report", "20260204230000")
    refiled = version("report", "20260302210000")
    amendment = version("amendment", "20260204200657")
    late_amendment = version("amendment", "20260305120000")

    # The key of the only report is later, yet an amendment can only follow a report.
    assert not superseded(amendment, [first, amendment])
    assert superseded(amendment, [first, amendment, refiled])
    assert not superseded(late_amendment, [first, refiled, late_amendment])
    assert family_hold([first, amendment, refiled]) is None
    assert family_hold([first, refiled, late_amendment]) == "amendment_pending"


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
            assert await evidence_holds(session) == ()

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
            assert await evidence_holds(session, issuers=["000660"]) == (
                hold("dart", "000660", 2020, "not_indexed"),
            )

            await session.rollback()
            await persist_seed_batch(session, batch(parsed(CORRECTION, ("I", "II"))))
            assert await eligible(session) == {
                (CORRECTION.document_id, "I"),
                (CORRECTION.document_id, "II"),
            }
            assert await evidence_holds(session) == ()
            # A search that names only the replaced filing is told so, not left empty.
            assert await evidence_holds(session, doc_ids=[ORIGINAL.document_id]) == (
                hold("dart", "000660", 2020, "replaced"),
            )
            both = [ORIGINAL.document_id, CORRECTION.document_id]
            assert await evidence_holds(session, doc_ids=both) == ()

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_an_unreviewed_amendment_withholds_its_report_period() -> None:
    """Knowing of an amendment is enough to withhold; indexing it does not release."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(session, batch(parsed(REPORT, ("1", "7"))))
            await register_filings(session, [AMENDMENT])
            await session.commit()
            pending = (hold("sec", "AMD", 2025, "amendment_pending"),)

            assert await eligible(session) == set()
            assert await evidence_holds(session, fiscal_years=[2025]) == pending
            assert await evidence_holds(session, doc_ids=[REPORT.document_id]) == pending
            assert await evidence_holds(session, fiscal_years=[2024]) == ()

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
            assert await evidence_holds(session) == (
                hold("sec", "AMD", 2025, "item_withheld", ("8",)),
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
def test_a_refiled_report_replaces_the_amendment_to_the_report_before_it() -> None:
    """An amendment follows its own report: a report accepted after it is whole again."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(
                session, batch(parsed(REPORT, ("1", "7")), parsed(AMENDMENT, ("7",)))
            )
            await register_filings(session, [REFILED_REPORT])
            await session.commit()
            # The amendment is unreviewed, and the report that replaced it is not indexed.
            assert await eligible(session) == set()
            assert await evidence_holds(session) == (hold("sec", "AMD", 2025, "not_indexed"),)

            await session.rollback()
            await persist_seed_batch(session, batch(parsed(REFILED_REPORT, ("1", "7"))))
            refiled = {(REFILED_REPORT.document_id, "1"), (REFILED_REPORT.document_id, "7")}
            assert await eligible(session) == refiled
            assert await evidence_holds(session) == ()

            await record_review(
                session,
                AMENDMENT.document_id,
                reviewer="operator",
                rationale="Item 7 restated in full.",
                effects=[ItemEffect("7", "replace")],
            )
            await session.commit()
            assert await eligible(session) == refiled

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_an_amendment_is_not_evidence_while_its_report_is_not_indexed() -> None:
    """What a search returns and what its hold says agree when only the amendment is stored."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await register_filings(session, [REPORT])
            await session.commit()
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
            assert await evidence_holds(session) == (hold("sec", "AMD", 2025, "not_indexed"),)

            await session.rollback()
            await persist_seed_batch(session, batch(parsed(REPORT, ("1", "7"))))
            assert await eligible(session) == {
                (REPORT.document_id, "1"),
                (AMENDMENT.document_id, "7"),
            }
            assert await evidence_holds(session) == ()

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_a_scope_that_leaves_out_the_replacing_filing_is_told_what_was_replaced() -> None:
    """Replaced text a search covers is named, whole or by Item, whatever narrowed the search."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(
                session,
                batch(parsed(REPORT, ("1", "7", "8", None)), parsed(AMENDMENT, ("7",))),
            )
            await record_review(
                session,
                AMENDMENT.document_id,
                reviewer="operator",
                rationale="Item 7 restated in full; Item 8 only in part.",
                effects=[ItemEffect("7", "replace"), ItemEffect("8", "withhold")],
            )
            await session.commit()
            withheld = hold("sec", "AMD", 2025, "item_withheld", ("8",))
            item_seven = hold("sec", "AMD", 2025, "replaced", ("7",))

            assert await evidence_holds(session) == (withheld,)
            original_form = [Document.form == "10-K"]
            assert await evidence_holds(session, within=original_form) == (withheld, item_seven)
            assert await evidence_holds(session, doc_ids=[REPORT.document_id]) == (
                withheld,
                item_seven,
            )
            # The amendment's Item 7 is inside this scope, so nothing of it is missing.
            assert await evidence_holds(session, within=[Chunk.item == "7"]) == (withheld,)
            assert await evidence_holds(session, within=[Document.form == "10-Q"]) == (withheld,)

        async with isolated_session() as session:
            await persist_seed_batch(
                session, batch(parsed(REPORT, ("1", "7")), parsed(AMENDMENT, ("7",)))
            )
            await record_review(
                session,
                AMENDMENT.document_id,
                reviewer="operator",
                rationale="Item 7 restated in full.",
                effects=[ItemEffect("7", "replace")],
            )
            await session.commit()
            # Everything this scope covers of the period was replaced.
            only_item_seven = [Document.form == "10-K", Chunk.item == "7"]
            assert await evidence_holds(session, within=only_item_seven) == (
                hold("sec", "AMD", 2025, "replaced"),
            )

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_a_hold_names_an_item_only_while_stored_text_has_no_evidence() -> None:
    """Replacing an Item with no text withholds it; a later amendment's text ends that."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(
                session,
                batch(
                    parsed(REPORT, ("1", "7", "8")),
                    parsed(AMENDMENT, ("7",)),
                    parsed(LATER_AMENDMENT, ("8",)),
                ),
            )
            await record_review(
                session,
                AMENDMENT.document_id,
                reviewer="operator",
                rationale="Item 7 restated; Items 8 and 9 no longer stand.",
                effects=[
                    ItemEffect("7", "replace"),
                    ItemEffect("8", "replace"),
                    ItemEffect("9", "withhold"),
                ],
            )
            await session.commit()
            # Item 9 has no stored text to keep out, and the later amendment is unreviewed.
            assert await evidence_holds(session) == (hold("sec", "AMD", 2025, "amendment_pending"),)

            await session.execute(
                delete(FilingVersion).where(FilingVersion.filing_id == LATER_AMENDMENT.filing_id)
            )
            await session.commit()
            assert await evidence_holds(session) == (
                hold("sec", "AMD", 2025, "item_withheld", ("8",)),
            )

            await register_filings(session, [LATER_AMENDMENT])
            await record_review(
                session,
                LATER_AMENDMENT.document_id,
                reviewer="operator",
                rationale="Item 8 set out again.",
                effects=[ItemEffect("8", "add")],
            )
            await session.commit()
            assert (LATER_AMENDMENT.document_id, "8") in await eligible(session)
            assert await evidence_holds(session) == ()

        async with isolated_session() as session:
            # A correction that drops a section replaced it with nothing a search can add.
            await persist_seed_batch(
                session, batch(parsed(ORIGINAL, ("I", "III")), parsed(CORRECTION, ("I",)))
            )
            both = [ORIGINAL.document_id, CORRECTION.document_id]
            assert await evidence_holds(session, doc_ids=both) == ()

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_an_amendment_that_sets_out_no_item_is_released_by_an_empty_review() -> None:
    """A stored amendment without Items can still be reviewed, so its period is not stuck."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(
                session, batch(parsed(REPORT, ("1", "7")), parsed(AMENDMENT, ()))
            )
            assert await eligible(session) == set()

            await record_review(
                session,
                AMENDMENT.document_id,
                reviewer="operator",
                rationale="The amendment only files an exhibit.",
                effects=[],
            )
            await session.commit()
            assert await eligible(session) == {(REPORT.document_id, "1"), (REPORT.document_id, "7")}
            assert await evidence_holds(session) == ()

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
            assert await evidence_holds(session) == (hold("sec", "AMD", 2025, "order_unknown"),)

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
            assert await evidence_holds(session) == (hold("sec", "AMD", 2025, "report_missing"),)

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
