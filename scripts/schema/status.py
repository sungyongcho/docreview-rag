"""Inspect or prepare schema objects while preserving existing database contents."""

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.bootstrap import SchemaDriftError, ensure_schema_compatibility
from app.db.models import Base
from app.db.startup import prepare as prepare_schema


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
            return {"schema_status": status, "created": created, "missing_tables": missing}
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
