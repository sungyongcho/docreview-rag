"""Persisting one batch's tables and their tagged facts."""

import asyncio

import pytest
from sqlalchemy import select

from app.db.models import TableSourceCell, TableSourceFact
from app.ingestion.persistence import _declared_facts, persist_seed_batch
from tests.ingestion.seed.support import TAGGED_TABLE_HTML, tagged_table_batch
from tests.live_postgres import isolated_session

# The tagged table with its FY2023 revenue tag naming a context the filing never
# declares, and its FY2023 EPS tag naming an undeclared unit.
UNDECLARED_HTML = TAGGED_TABLE_HTML.replace(
    'contextRef="fy23" unitRef="usd"', 'contextRef="missingCtx" unitRef="usd"'
).replace('contextRef="fy23" unitRef="usdPerShare"', 'contextRef="fy23" unitRef="missingUnit"')


@pytest.mark.live_postgres
def test_facts_naming_undeclared_contexts_or_units_do_not_abort_the_batch():
    """Store the batch, leaving out the undeclared context's fact and its unit's reference."""

    async def exercise() -> None:
        """Persist the table whose tags name declarations the filing lacks."""
        async with isolated_session() as session:
            await persist_seed_batch(session, tagged_table_batch(html=UNDECLARED_HTML))
            facts = (
                await session.execute(
                    select(
                        TableSourceFact.grid_row,
                        TableSourceFact.grid_column,
                        TableSourceFact.ordinal,
                        TableSourceFact.context_id,
                        TableSourceFact.unit_id,
                    ).order_by(TableSourceFact.grid_row, TableSourceFact.grid_column)
                )
            ).all()
            assert [tuple(row) for row in facts] == [
                (1, 1, 0, "fy24", "usd"),
                (2, 1, 0, "fy24", "usdPerShare"),
                (2, 2, 0, "fy23", None),
                (3, 1, 0, "dc24", "usd"),
            ]
            bases = {
                text: basis
                for text, basis in await session.execute(
                    select(TableSourceCell.text, TableSourceCell.reading_basis).where(
                        TableSourceCell.reading_values.is_not(None)
                    )
                )
            }
            assert bases["$ 26,974"] == "fact"
            assert bases["$ 1.74"] == "fact"

    asyncio.run(exercise())


@pytest.mark.live_postgres
def test_facts_naming_declared_contexts_and_units_are_all_stored():
    """Store every tag of a filing that declares all it names, with its unit."""

    async def exercise() -> None:
        """Persist the ordinary tagged table and count its facts and units."""
        async with isolated_session() as session:
            await persist_seed_batch(session, tagged_table_batch())
            units = (await session.scalars(select(TableSourceFact.unit_id))).all()
            assert sorted(units) == ["usd", "usd", "usd", "usdPerShare", "usdPerShare"]

    asyncio.run(exercise())


def test_fact_rows_keep_declared_references_and_drop_undeclared_ones():
    """Drop a row with an undeclared context and the unit a row names undeclared."""
    facts = tagged_table_batch(html=UNDECLARED_HTML).filings[0].facts
    rows = [
        {"context_id": "fy24", "unit_id": "usd"},
        {"context_id": "missingCtx", "unit_id": "usd"},
        {"context_id": "fy23", "unit_id": "missingUnit"},
        {"context_id": "fy23", "unit_id": None},
    ]
    assert _declared_facts(rows, facts) == [
        {"context_id": "fy24", "unit_id": "usd"},
        {"context_id": "fy23", "unit_id": None},
        {"context_id": "fy23", "unit_id": None},
    ]
