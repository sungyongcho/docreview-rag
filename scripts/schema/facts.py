"""Give stored table records the columns and statuses of fact-based cell readings.

Every stored reading so far was read from text, so the new columns are added and
each existing reading is marked ``text`` with no overrides; live tables get their
fact readings by being ingested again. The cell status and reading constraints are
replaced by the ones the models now declare, and the fact tables are created.
"""

from sqlalchemy import CheckConstraint, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.db.bootstrap import bootstrap_schema
from app.db.models import SnapshotTableCell, TableCell, TableSourceCell

READING_COLUMNS = (
    ("reading_basis", "varchar(8)"),
    ("reading_overrides", "varchar(16)[]"),
    ("reading_scope", "text"),
    ("reading_measure", "varchar(16)"),
)
SOURCE_CELL_TABLES = ("table_source_cells", "snapshot_table_source_cells")


def _constraints(model: type, names: tuple[str, ...]) -> list[tuple[str, str]]:
    """Return the named CHECK constraints a model declares, as (name, SQL) pairs."""
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in model.__table__.constraints  # pyright: ignore[reportAttributeAccessIssue]
        if isinstance(constraint, CheckConstraint)
    }
    return [(name, checks[name]) for name in names]


async def migrate_facts(connection: AsyncConnection) -> dict[str, object]:
    """Add the reading columns, mark existing readings as text, and replace checks."""
    marked: dict[str, int] = {}
    for table in SOURCE_CELL_TABLES:
        for column, kind in READING_COLUMNS:
            await connection.execute(
                text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {kind}")
            )
        result = await connection.execute(
            text(
                f"UPDATE {table} SET reading_basis = 'text', reading_overrides = '{{}}' "
                "WHERE reading_values IS NOT NULL AND reading_basis IS NULL"
            )
        )
        marked[table] = result.rowcount
    replaced = [
        ("table_source_cells", name, sql)
        for name, sql in _constraints(
            TableSourceCell,
            (
                "ck_table_source_cells_reading",
                "ck_table_source_cells_basis",
                "ck_table_source_cells_measure",
            ),
        )
    ]
    replaced += [
        ("table_cells", name, sql)
        for name, sql in _constraints(TableCell, ("ck_table_cells_status",))
    ]
    replaced += [
        ("snapshot_table_cells", name, sql)
        for name, sql in _constraints(SnapshotTableCell, ("ck_snapshot_table_cells_status",))
    ]
    for table, name, sql in replaced:
        await connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}"))
        await connection.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({sql})"))
    return {"status": "migrated", "readings_marked_text": marked}


async def run(url: str) -> dict[str, object]:
    """Migrate the stored records in one transaction, then create the fact tables."""
    engine = create_async_engine(url, echo=False)
    try:
        async with engine.begin() as connection:
            report = await migrate_facts(connection)
        await bootstrap_schema(engine)
        return report
    finally:
        await engine.dispose()
