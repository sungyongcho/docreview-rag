"""Recording stored documents as filing versions in a database that predates them."""

import asyncio

import pytest
from sqlalchemy import func, select, text

from app.db.models import FilingVersion
from app.ingestion.persistence import persist_seed_batch
from scripts.schema.filings import record_filings
from tests.amendments.support import batch, dart_document, eligible, parsed, sec_document
from tests.live_postgres import isolated_session


@pytest.mark.live_postgres
def test_stored_documents_become_evidence_again_once_recorded():
    """Without the tables nothing is recorded; recording restores every stored chunk."""

    async def exercise() -> None:
        """Store two filings, drop the version tables, then record twice."""
        async with isolated_session() as session:
            report, annual = sec_document(18), dart_document("20210322000782")
            await persist_seed_batch(
                session, batch(parsed(report, ("1", None)), parsed(annual, ("I",)))
            )
            stored = await eligible(session)
            assert len(stored) == 3
            keys = dict(
                (
                    await session.execute(select(FilingVersion.filing_id, FilingVersion.filed_key))
                ).all()
            )
            await session.execute(text("DROP TABLE amendment_effects, filing_versions"))
            # The disposable schema falls back to public, where another test may have
            # left these tables: only this schema may answer whether they exist.
            await session.execute(text("SELECT set_config('search_path', current_schema(), true)"))

            for _ in range(2):
                assert await record_filings(await session.connection()) == {
                    "status": "recorded",
                    "filings_recorded": 2,
                }
            assert await eligible(session) == stored
            assert await session.scalar(select(func.count()).select_from(FilingVersion)) == 2
            assert keys == dict(
                (
                    await session.execute(select(FilingVersion.filing_id, FilingVersion.filed_key))
                ).all()
            )

    asyncio.run(exercise())
