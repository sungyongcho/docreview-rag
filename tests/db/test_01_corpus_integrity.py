"""Live referential integrity for corpus artifacts and processing selections."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db.bootstrap import ensure_vector_extension
from app.db.models import Base, Corpus, ProcessingSelection, SelectionArtifact, SourceArtifact


@pytest.mark.live_postgres
def test_corpus_references_are_enforced_by_postgres():
    """The database rejects dangling artifacts and cross-corpus selections."""

    async def exercise():
        """Keep all schema and test rows inside one rolled-back transaction."""
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.connect() as connection:
                await ensure_vector_extension(connection)
                await connection.commit()
                transaction = await connection.begin()
                try:
                    schema = f"corpus_contract_{uuid4().hex}"
                    await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                    await connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
                    await connection.run_sync(Base.metadata.create_all)
                    await connection.execute(insert(Corpus).values(corpus_id="one", name="One"))
                    await connection.execute(insert(Corpus).values(corpus_id="two", name="Two"))
                    await connection.execute(
                        insert(ProcessingSelection).values(corpus_id="one", selection_id="selected")
                    )
                    with pytest.raises(IntegrityError):
                        async with connection.begin_nested():
                            await connection.execute(
                                insert(SourceArtifact).values(
                                    corpus_id="one",
                                    artifact_id="source",
                                    doc_id="missing",
                                    role="primary",
                                    path="source.html",
                                    sha256="a" * 64,
                                    byte_length=1,
                                    encoding="utf-8",
                                    acquisition={},
                                )
                            )
                    with pytest.raises(IntegrityError):
                        async with connection.begin_nested():
                            await connection.execute(
                                insert(SelectionArtifact).values(
                                    corpus_id="two", selection_id="selected", artifact_id="missing"
                                )
                            )
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(exercise())
