"""Give a database indexed before filing versions existed the records they need.

The two tables that record filing versions and amendment reviews are created, and
every stored document is recorded as a version of its report period. Without that
record a stored document is not evidence, so this is what keeps an existing index
searchable. Amendments and corrections are recorded by the next acquisition.
"""

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from app.amendments.registration import register_stored_documents
from app.db.bootstrap import bootstrap_schema
from app.db.models import AmendmentEffect, Base, FilingVersion


async def record_filings(connection: AsyncConnection) -> dict[str, object]:
    """Create the version tables when absent and record every stored document."""
    tables = [FilingVersion.__table__, AmendmentEffect.__table__]
    await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))  # pyright: ignore[reportArgumentType]
    async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as session:
        recorded = await register_stored_documents(session)
        await session.commit()
    return {"status": "recorded", "filings_recorded": recorded}


async def run(url: str) -> dict[str, object]:
    """Record the stored documents in one transaction, then complete the schema."""
    engine = create_async_engine(url, echo=False)
    try:
        async with engine.begin() as connection:
            report = await record_filings(connection)
        await bootstrap_schema(engine)
        return report
    finally:
        await engine.dispose()
