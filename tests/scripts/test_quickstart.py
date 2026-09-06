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
    monkeypatch.setattr(
        setup.subprocess, "check_output", lambda args, **k: "2.39.0" if "version" in args else "[]"
    )
    monkeypatch.setattr(setup.subprocess, "run", lambda args, **kwargs: calls.append(args))
    schema = AsyncMock(return_value=False)
    monkeypatch.setattr(setup, "prepare_schema", schema)
    monkeypatch.setattr(setup, "run", lambda mode, args, **kwargs: calls.append(args) or 0)
    monkeypatch.setattr(setup, "wait_ready", lambda origin: calls.append(origin))
    assert setup.quickstart(configured) == 0
    schema.assert_awaited_once_with("postgresql+asyncpg://filing:filing@127.0.0.1:38432/filing")
    assert calls[0][-5:] == ["-d", "--wait", "--wait-timeout", "120", "db"]
    assert calls[1] == ["up", "--build", "-d"]
    assert calls[2] == "http://127.0.0.1:38010"


def test_schema_preparation_uses_shared_startup_contract(monkeypatch):
    """Quickstart delegates to the same non-destructive implementation as the container."""
    from unittest.mock import Mock

    engine = Mock(dispose=AsyncMock())
    shared = AsyncMock(return_value=False)
    monkeypatch.setattr(setup, "create_async_engine", lambda *a, **k: engine)
    monkeypatch.setattr(setup, "prepare_empty_schema", shared)
    assert asyncio.run(setup.prepare_schema("unused")) is False
    shared.assert_awaited_once_with(engine)
    engine.dispose.assert_awaited_once()


@pytest.mark.parametrize("array", [True, False])
def test_service_states_are_project_scoped(configured, monkeypatch, capsys, array):
    """Handle Compose array and JSON-lines formats without claiming web health."""
    import json

    rows = [
        {"Service": "db", "State": "running", "Health": "healthy"},
        {"Service": "app", "State": "running", "Health": "unhealthy"},
        {"Service": "web", "State": "running", "Health": ""},
    ]
    commands = []

    def output(args, **kwargs):
        """Capture the actual project-scoped inspection command."""
        commands.append(args)
        return json.dumps(rows) if array else "\n".join(map(json.dumps, rows))

    monkeypatch.setattr(setup.subprocess, "check_output", output)
    setup.report_services(configured, {})
    result = capsys.readouterr().out
    assert "db: already running / healthy" in result
    assert "app: unhealthy; inspect rag-dev logs --tail 50 app" in result
    assert "web: running (no health check" in result
    assert commands[0][commands[0].index("-p") + 1] == configured.name
    assert commands[0][-4:] == ["ps", "--all", "--format", "json"]


def test_stopped_and_starting_states(configured, monkeypatch, capsys):
    """Do not confuse a missing container, an exited one, and pending health."""
    monkeypatch.setattr(
        setup.subprocess,
        "check_output",
        lambda *a, **k: (
            '[{"Service":"db","State":"exited"},'
            '{"Service":"app","State":"running","Health":"starting"}]'
        ),
    )
    setup.report_services(configured, {})
    result = capsys.readouterr().out
    assert "db: stopped (exited)" in result
    assert "app: starting (health check pending)" in result
    assert "web: stopped (not created)" in result


def test_configuration_block_does_not_start_services(configured, monkeypatch):
    """Stop before Compose mutations and provide the precise resume command."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
    monkeypatch.setattr(setup.subprocess, "check_output", lambda *a, **k: "2.39.0")
    from unittest.mock import Mock

    start = Mock()
    monkeypatch.setattr(setup.subprocess, "run", start)
    with pytest.raises(ValueError, match="Then rerun rag-quickstart") as failure:
        setup.quickstart(configured)
    assert str(configured / ".env") in str(failure.value)
    assert "No services were started by this invocation" in str(failure.value)
    start.assert_not_called()


def test_schema_drift_blocks_application_start(configured, monkeypatch):
    """Keep incompatible data intact and hand off to schema diagnosis."""
    from unittest.mock import Mock

    monkeypatch.setattr(
        setup.subprocess, "check_output", lambda args, **k: "2.39.0" if "version" in args else "[]"
    )
    monkeypatch.setattr(setup.subprocess, "run", Mock())
    monkeypatch.setattr(
        setup, "prepare_schema", AsyncMock(side_effect=setup.SchemaDriftError("drift"))
    )
    start = Mock()
    monkeypatch.setattr(setup, "run", start)
    with pytest.raises(RuntimeError, match="scripts.schema_status check"):
        setup.quickstart(configured)
    start.assert_not_called()


def test_readiness_timeout_never_reports_success(monkeypatch):
    """Unconfirmed readiness remains a failure with an actionable diagnostic command."""
    monkeypatch.setattr(setup.time, "monotonic", iter([0, 181]).__next__)
    with pytest.raises(RuntimeError, match="DEV readiness was not confirmed"):
        setup.wait_ready("http://127.0.0.1:38010")


def test_failed_startup_does_not_print_ready(configured, monkeypatch, capsys):
    """A failed Compose command cannot emit working tutorial or application claims."""
    from unittest.mock import Mock

    monkeypatch.setattr(
        setup.subprocess, "check_output", lambda args, **k: "2.39.0" if "version" in args else "[]"
    )
    monkeypatch.setattr(setup.subprocess, "run", Mock())
    monkeypatch.setattr(setup, "prepare_schema", AsyncMock(return_value=False))
    monkeypatch.setattr(setup, "run", lambda *a, **k: 1)
    readiness = Mock()
    monkeypatch.setattr(setup, "wait_ready", readiness)
    assert setup.quickstart(configured) == 1
    readiness.assert_not_called()
    result = capsys.readouterr().out
    assert "Service ready:" not in result
    assert "readiness was not confirmed" in result
