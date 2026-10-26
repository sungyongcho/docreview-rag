"""Adding the fact-reading columns and statuses to stored table records."""

import asyncio

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.db.models import TableCell, TableSourceCell
from app.ingestion.persistence import persist_seed_batch
from scripts.schema.facts import READING_COLUMNS, SOURCE_CELL_TABLES, migrate_facts
from tests.ingestion.seed.support import table_batch
from tests.live_postgres import isolated_session

# The cell statuses stored before fact readings existed.
OLD_STATUSES = (
    "'known', 'blank', 'not_numeric', 'conflicting', 'scale_unknown', "
    "'currency_unconfirmed', 'period_unknown', 'item_unknown'"
)


@pytest.mark.live_postgres
def test_stored_readings_gain_the_fact_columns_marked_as_text_readings():
    """Mark every stored reading as text, accept the new statuses, and rerun as a no-op."""

    async def exercise() -> None:
        """Store a table on the pre-fact schema, then migrate it twice."""
        async with isolated_session() as session:
            await persist_seed_batch(session, table_batch())
            for table in SOURCE_CELL_TABLES:
                for column, _ in READING_COLUMNS:
                    await session.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
            await session.execute(
                text("ALTER TABLE table_cells DROP CONSTRAINT ck_table_cells_status")
            )
            await session.execute(
                text(
                    "ALTER TABLE table_cells ADD CONSTRAINT ck_table_cells_status "
                    f"CHECK (status IN ({OLD_STATUSES}))"
                )
            )
            readings = await session.scalar(
                text("SELECT count(*) FROM table_source_cells WHERE reading_values IS NOT NULL")
            )

            report = await migrate_facts(await session.connection())

            assert report["readings_marked_text"] == {
                "table_source_cells": readings,
                "snapshot_table_source_cells": 0,
            }
            stored = await session.execute(
                select(TableSourceCell.reading_basis, TableSourceCell.reading_overrides)
                .where(TableSourceCell.reading_values.is_not(None))
                .distinct()
            )
            assert [tuple(row) for row in stored] == [("text", [])]
            async with session.begin_nested():
                await session.execute(
                    update(TableCell)
                    .where(TableCell.status == "known")
                    .values(status="scope_qualified")
                )
            for values in ({"status": "guessed"},):
                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        await session.execute(update(TableCell).values(**values))
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(
                        update(TableSourceCell)
                        .where(TableSourceCell.reading_values.is_not(None))
                        .values(reading_basis=None)
                    )
            again = await migrate_facts(await session.connection())
            assert again["readings_marked_text"] == {
                "table_source_cells": 0,
                "snapshot_table_source_cells": 0,
            }

    asyncio.run(exercise())
