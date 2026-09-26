"""Async SQLAlchemy engine and session-factory tests."""

import asyncio

from sqlalchemy.orm import make_transient_to_detached

from app.config import get_settings
from app.db.models import Corpus
from app.db.session import Session, engine


def test_engine_uses_the_configured_database_url() -> None:
    """Bind the process-wide engine to the validated database URL."""
    assert engine.url.render_as_string(hide_password=False) == get_settings().database_url


def test_committed_rows_stay_readable_after_the_session_closes() -> None:
    """Sessions share the process engine and never expire what they commit.

    An expired attribute on a closed session needs a reload that async callers cannot
    run, so reading a committed row afterwards would raise instead of returning it.
    """
    corpus = Corpus(corpus_id="one", name="One")
    # A detached row becomes persistent on add, so the commit needs no database.
    make_transient_to_detached(corpus)

    async def commit_row() -> None:
        """Commit the row through one session from the shared factory."""
        async with Session() as session:
            assert session.bind is engine
            session.add(corpus)
            await session.commit()

    asyncio.run(commit_row())

    assert corpus.name == "One"
