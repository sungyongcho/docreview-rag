"""First-run configuration and orchestration preserve existing user data."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from scripts import quickstart as setup


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Provide isolated configuration without inheriting any developer credentials."""
    for key in [
        "SEC_USER_AGENT",
        "DART_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_API_KEY_LOCAL",
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
    ]:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "SEC_USER_AGENT=Tester tester@company.test\nDART_API_KEY=test-dart\n"
        "OPENAI_API_KEY_LOCAL=test-openai\nEMBEDDING_PROVIDER=openai\n"
        "EMBEDDING_MODEL=text-embedding-3-large\nAPP_PORT=38010\nDB_PORT=38432\n"
        "DOCREVIEW_OPERATOR_PORT=38011\n"
    )
    return tmp_path


def test_missing_configuration_creates_private_template_once(tmp_path, monkeypatch, capsys):
    """A first invocation gives actionable names while retaining the new template on retry."""
    for key in ["SEC_USER_AGENT", "DART_API_KEY", "OPENAI_API_KEY", "OPENAI_API_KEY_LOCAL"]:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env.example").write_text(
        "SEC_USER_AGENT=Jane jane@example.com\nDART_API_KEY=<your-dart-key>\n"
        "OPENAI_API_KEY_LOCAL=<your-key>\n"
    )
    with pytest.raises(ValueError, match="DART_API_KEY"):
        setup.validate_configuration(tmp_path)
    original = (tmp_path / ".env").read_bytes()
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        setup.validate_configuration(tmp_path)
    assert (tmp_path / ".env").read_bytes() == original
    assert "<your-key>" not in capsys.readouterr().out


def test_valid_configuration_is_not_overwritten(configured):
    """Existing configuration and custom ports remain byte-for-byte intact."""
    original = (configured / ".env").read_bytes()
    bindings = setup.validate_configuration(configured)
    assert bindings["DB_PORT"] == "38432"
    assert (configured / ".env").read_bytes() == original


def test_effective_override_cannot_silently_select_fake_embeddings(configured, monkeypatch):
    """Catch shell overrides that would invalidate the documented real-embedding path."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
    with pytest.raises(ValueError, match="EMBEDDING_PROVIDER=openai"):
        setup.validate_configuration(configured)


def test_startup_prepares_only_project_database_before_app(configured, monkeypatch):
    """Use the project port instead of a potentially external DATABASE_URL."""
    calls = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://external.example/never-touch")
    monkeypatch.setattr(setup.subprocess, "check_output", lambda *a, **k: "2.39.0")
    monkeypatch.setattr(setup.subprocess, "run", lambda args, **kwargs: calls.append(args))
    schema = AsyncMock(return_value=False)
    monkeypatch.setattr(setup, "prepare_schema", schema)
    monkeypatch.setattr(setup, "run", lambda mode, args, **kwargs: calls.append(args) or 0)
    monkeypatch.setattr(setup, "wait_ready", lambda origin: calls.append(origin))
    assert setup.quickstart(configured) == 0
    schema.assert_awaited_once_with("postgresql+asyncpg://filing:filing@127.0.0.1:38432/filing")
    assert calls[0][-3:] == ["-d", "--wait", "db"]
    assert calls[1] == ["up", "--build", "-d"]
    assert calls[2] == "http://127.0.0.1:38010"


def test_existing_schema_is_inspected_without_bootstrap(monkeypatch):
    """Never run bootstrap or migrations against an already populated compatible schema."""

    class Connection:
        """Return an existing complete table inventory."""

        async def __aenter__(self):
            """Enter the read-only connection scope."""
            return self

        async def __aexit__(self, *args):
            """Leave without swallowing inspection failures."""
            return False

        async def run_sync(self, action):
            """Simulate the complete existing model table inventory."""
            return list(setup.Base.metadata.tables)

    class Engine:
        """Expose only the connection and cleanup needed for existing-schema inspection."""

        def connect(self):
            """Return the table inventory connection."""
            return Connection()

        async def dispose(self):
            """Release the fake engine."""

    monkeypatch.setattr(setup, "create_async_engine", lambda *a, **k: Engine())
    compatibility = AsyncMock()
    bootstrap = AsyncMock()
    monkeypatch.setattr(setup, "ensure_schema_compatibility", compatibility)
    monkeypatch.setattr(setup, "bootstrap_schema", bootstrap)
    assert asyncio.run(setup.prepare_schema("unused")) is False
    compatibility.assert_awaited_once()
    bootstrap.assert_not_awaited()
