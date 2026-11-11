"""Inspect or prepare schema objects while preserving existing database contents."""

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.db.bootstrap import SchemaDriftError, ensure_schema_compatibility
from app.db.models import Base, ParsedTable
from app.db.startup import prepare as prepare_schema
from app.ingestion.table_records import builder_identity, resolver_identity


async def stored_tables(connection: AsyncConnection) -> dict[str, object]:
    """Count the stored tables and those built or read by code other than the running code.

    A stale table serves no cell catalog and confirms no figure until its document is
    ingested again.
    """
    resolver, builder = resolver_identity(), builder_identity()
    total, stale = (
        await connection.execute(
            select(
                func.count(),
                func.count().filter(
                    (ParsedTable.resolver_identity != resolver)
                    | (ParsedTable.builder_identity != builder)
                ),
            ).select_from(ParsedTable)
        )
    ).one()
    return {
        "total": total,
        "stale": stale,
        "resolver_identity": resolver,
        "builder_identity": builder,
    }


async def schema_status(url: str, *, prepare: bool = False) -> dict[str, object]:
    """Inspect compatibility, optionally creating only an empty database's schema."""
    try:
        created = await prepare_schema(url) if prepare else False
        engine = create_async_engine(url, echo=False)
        try:
            async with engine.connect() as connection:
                await ensure_schema_compatibility(connection)
                tables = set(
                    await connection.run_sync(lambda sync: inspect(sync).get_table_names())
                )
                missing = sorted(set(Base.metadata.tables) - tables)
                status = "empty" if not tables else "incomplete" if missing else "compatible"
                result: dict[str, object] = {
                    "schema_status": status,
                    "created": created,
                    "missing_tables": missing,
                }
                if status == "compatible":
                    result["stored_tables"] = await stored_tables(connection)
            return result
        finally:
            await engine.dispose()
    except (SchemaDriftError, ValueError) as error:
        return {"schema_status": "drifted", "message": str(error), "created": False}
    except SQLAlchemyError as error:
        return {
            "schema_status": "unavailable",
            "message": f"Local database connection failed ({type(error).__name__}).",
            "created": False,
        }
