"""Async SQLAlchemy engine and session-factory tests."""

from app.config import get_settings
from app.db.session import Session, engine


def test_engine_uses_the_configured_database_url() -> None:
    """Bind the process-wide engine to the validated database URL."""
    assert engine.url.render_as_string(hide_password=False) == get_settings().database_url


def test_session_factory_uses_the_shared_engine() -> None:
    """Bind sessions to the shared engine without expiring committed state."""
    assert Session.kw["bind"] is engine
    assert Session.kw["expire_on_commit"] is False
