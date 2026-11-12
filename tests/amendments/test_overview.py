"""What an operator is shown about report periods with more than one filing."""

import asyncio

import pytest

from app.amendments.overview import ItemChunks, ItemDecision, amended_report_periods
from app.amendments.registration import register_filings
from app.amendments.review import ItemEffect, record_review
from app.ingestion.persistence import persist_seed_batch
from tests.amendments.support import (
    amendment_document,
    batch,
    dart_document,
    parsed,
    sec_document,
)
from tests.live_postgres import isolated_session

REPORT = sec_document(18)
AMENDMENT = amendment_document(21)


@pytest.mark.live_postgres
def test_only_periods_with_something_to_weigh_are_listed() -> None:
    """A lone report is left out; a known correction and an amendment are each listed."""

    async def scenario() -> None:
        async with isolated_session() as session:
            lone = sec_document(5, period=REPORT.report_period.replace(year=2024))
            original, correction = dart_document("20210322000782"), dart_document("20210330000776")
            await persist_seed_batch(
                session,
                batch(
                    parsed(lone, ("1",)),
                    parsed(REPORT, ("7", "1", None)),
                    parsed(original, ("I",)),
                ),
            )
            await register_filings(session, [AMENDMENT, correction])
            await session.commit()

            dart, sec = await amended_report_periods(session)

            assert (dart.registry, dart.issuer, dart.fiscal_year) == ("dart", "000660", 2020)
            assert dart.hold == "not_indexed"
            assert [version.doc_id for version in dart.versions] == [original.document_id, None]
            assert (sec.issuer, sec.fiscal_year, sec.hold) == ("AMD", 2025, "amendment_pending")
            report, amendment = sec.versions
            assert (report.kind, report.form, report.current) == ("report", "10-K", False)
            # Items keep the order the filing sets them out, not their spelling.
            assert report.items == (ItemChunks(item="7", chunks=1), ItemChunks(item="1", chunks=1))
            assert report.unnumbered_chunks == 1
            assert (amendment.kind, amendment.doc_id, amendment.items) == ("amendment", None, ())
            assert (report.parse_status, amendment.parse_status) == ("parsed", None)
            assert amendment.review is None

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_a_reviewed_amendment_shows_its_decisions_and_what_is_current() -> None:
    """The review is shown as recorded, and the period can be read by a member document."""

    async def scenario() -> None:
        async with isolated_session() as session:
            await persist_seed_batch(
                session, batch(parsed(REPORT, ("1", "7")), parsed(AMENDMENT, ("7", "15")))
            )
            await record_review(
                session,
                AMENDMENT.document_id,
                reviewer="operator",
                rationale="Item 7 restated in full.",
                effects=[ItemEffect("7", "replace"), ItemEffect("15", "withhold")],
            )
            await session.commit()

            (period,) = await amended_report_periods(session, doc_id=REPORT.document_id)

            assert period.hold is None
            report, amendment = period.versions
            assert (report.current, amendment.current) == (True, True)
            assert amendment.source_url == AMENDMENT.source_url
            assert amendment.review is not None
            assert (amendment.review.reviewer, amendment.review.rationale) == (
                "operator",
                "Item 7 restated in full.",
            )
            assert amendment.review.decisions == (
                ItemDecision(item="15", action="withhold"),
                ItemDecision(item="7", action="replace"),
            )
            assert await amended_report_periods(session, doc_id="unknown") == ()

    asyncio.run(scenario())
