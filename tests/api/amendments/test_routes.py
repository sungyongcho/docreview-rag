"""Administrator routes that list amended report periods and record their reviews."""

import asyncio
from types import SimpleNamespace

import pytest

from app.api.amendments.routes import (
    AmendmentReviewRequest,
    amended_periods,
    review_amendment,
    withdraw_amendment_review,
)
from app.api.errors import ApiProblemError
from app.ingestion.persistence import persist_seed_batch
from tests.amendments.support import amendment_document, batch, eligible, parsed, sec_document
from tests.api.support import _admin
from tests.live_postgres import isolated_session_factory

REPORT = sec_document(18)
AMENDMENT = amendment_document(21)


def review(*decisions: tuple[str, str]) -> AmendmentReviewRequest:
    """Build a review request from the JSON body a client sends for the given pairs."""
    return AmendmentReviewRequest.model_validate(
        {
            "reviewer": "operator",
            "rationale": "Read against the original.",
            "decisions": [{"item": item, "action": action} for item, action in decisions],
        }
    )


@pytest.mark.live_postgres
def test_a_review_releases_the_period_and_withdrawing_it_holds_it_again() -> None:
    """The routes commit the review, and each answer shows the period as it then stands."""

    async def scenario() -> None:
        async with isolated_session_factory() as factory:
            async with factory() as session:
                await persist_seed_batch(
                    session, batch(parsed(REPORT, ("1", "7")), parsed(AMENDMENT, ("7",)))
                )
            services = _admin(runtime=SimpleNamespace(session_factory=factory))

            (listed,) = (await amended_periods(services)).report_periods
            assert listed.hold == "amendment_pending"

            reviewed = await review_amendment(
                AMENDMENT.document_id, review(("7", "replace")), services
            )
            assert reviewed.hold is None
            assert reviewed.versions[1].review is not None
            async with factory() as session:
                assert await eligible(session) == {
                    (REPORT.document_id, "1"),
                    (AMENDMENT.document_id, "7"),
                }

            withdrawn = await withdraw_amendment_review(AMENDMENT.document_id, services)
            assert withdrawn.hold == "amendment_pending"
            assert withdrawn.versions[1].review is None
            async with factory() as session:
                assert await eligible(session) == set()

    asyncio.run(scenario())


@pytest.mark.live_postgres
def test_a_refused_review_answers_with_its_cause_and_records_nothing() -> None:
    """An unknown document is 404; a report or an incomplete review is a typed 400."""

    async def scenario() -> None:
        async with isolated_session_factory() as factory:
            async with factory() as session:
                await persist_seed_batch(
                    session, batch(parsed(REPORT, ("1", "7")), parsed(AMENDMENT, ("7", "15")))
                )
            services = _admin(runtime=SimpleNamespace(session_factory=factory))
            refusals = (
                ("missing", review(("7", "replace")), 404, "amendment_not_found"),
                (REPORT.document_id, review(("7", "replace")), 400, "not_an_amendment"),
                (AMENDMENT.document_id, review(("7", "replace")), 400, "invalid_review"),
            )
            for doc_id, request, status, code in refusals:
                with pytest.raises(ApiProblemError) as refused:
                    await review_amendment(doc_id, request, services)
                assert (refused.value.status_code, refused.value.error.code) == (status, code)
            with pytest.raises(ApiProblemError) as refused:
                await withdraw_amendment_review("missing", services)
            assert refused.value.status_code == 404

            (listed,) = (await amended_periods(services)).report_periods
            assert listed.versions[1].review is None

    asyncio.run(scenario())
