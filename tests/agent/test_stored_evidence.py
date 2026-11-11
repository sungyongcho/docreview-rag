"""Cited evidence read as stored now, for the agent's final-answer figure check."""

import asyncio

import pytest
from sqlalchemy import select, update

from app.agent.stored_evidence import read_cited_evidence
from app.db.models import Chunk, ParsedTable
from app.figures.answers import EvidenceText, check_figures
from app.ingestion.persistence import persist_seed_batch
from tests.ingestion.seed.support import sample_batch, table_batch
from tests.live_postgres import isolated_session_factory

TABLE_ANSWER = "Net revenue was $25,785 million in fiscal 2024."
PROSE = "Net revenue increased 14% compared with the prior year."


@pytest.mark.live_postgres
@pytest.mark.parametrize("identity", ["resolver_identity", "builder_identity"])
def test_a_stale_table_confirms_no_figure_and_its_body_is_not_read_as_prose(identity):
    """Verify from a current table; leave the same answer unverified once it is stale."""

    async def exercise() -> None:
        """Store a table and a prose chunk, check, mark the table stale, check again."""
        async with isolated_session_factory() as factory:
            async with factory() as session:
                await persist_seed_batch(session, table_batch(doc_id="AMD-FY2024"))
                await persist_seed_batch(session, sample_batch())
                table_id = await session.scalar(
                    select(Chunk.id).where(Chunk.doc_id == "AMD-FY2024")
                )
                text_id = await session.scalar(select(Chunk.id).where(Chunk.kind == "text"))
                assert table_id is not None and text_id is not None
                await session.execute(update(Chunk).where(Chunk.id == text_id).values(body=PROSE))
                await session.commit()

            current = await read_cited_evidence(factory, (table_id, text_id))
            assert current[table_id].table_cells
            assert check_figures(TABLE_ANSWER, [current[table_id]], [2024]).verdict == "verified"
            assert check_figures("Revenue grew 14%.", [current[text_id]], []).verdict == (
                "verified"
            )

            async with factory() as session:
                await session.execute(update(ParsedTable).values({identity: "0" * 64}))
                # A body that would confirm the answer if it were read as running text.
                await session.execute(
                    update(Chunk)
                    .where(Chunk.id == table_id)
                    .values(body="Revenue grew 14% in fiscal 2024.")
                )
                await session.commit()

            stale = await read_cited_evidence(factory, (table_id, text_id))
            table = stale[table_id]
            assert (table.body, table.table_cells) == ("", ())
            assert check_figures(TABLE_ANSWER, [table], [2024]).verdict == "unverified"
            assert check_figures("Revenue grew 14%.", [table], []).verdict == "unverified"
            as_prose = EvidenceText(table_id, "Revenue grew 14% in fiscal 2024.", "", None)
            assert check_figures("Revenue grew 14%.", [as_prose], []).verdict == "verified"
            assert stale[text_id] == current[text_id]
            assert check_figures("Revenue grew 14%.", [stale[text_id]], []).verdict == ("verified")

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_a_table_chunk_stored_without_its_table_is_not_read_as_prose():
    """Give a table chunk with no table rows no body and no cells, so it confirms nothing."""

    async def exercise() -> None:
        """Store a table chunk without rows whose body would confirm the answer as prose."""
        async with isolated_session_factory() as factory:
            async with factory() as session:
                await persist_seed_batch(session, sample_batch())
                table_id = await session.scalar(select(Chunk.id).where(Chunk.kind == "table"))
                assert table_id is not None
                await session.execute(
                    update(Chunk)
                    .where(Chunk.id == table_id)
                    .values(body="Revenue grew 14% in fiscal 2024.")
                )
                await session.commit()
            evidence = (await read_cited_evidence(factory, (table_id,)))[table_id]
            assert (evidence.body, evidence.table_cells) == ("", ())
            assert check_figures("Revenue grew 14%.", [evidence], []).verdict == "unverified"

    asyncio.run(exercise())
