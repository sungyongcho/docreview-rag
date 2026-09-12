"""First-run configuration and orchestration preserve existing user data."""

from unittest.mock import AsyncMock

import pytest

from scripts.stack import quickstart as setup


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
    monkeypatch.setattr(setup, "wait_ready", lambda origin, **kwargs: calls.append(origin))
    assert setup.quickstart(configured) == 0
    schema.assert_awaited_once_with("postgresql+asyncpg://filing:filing@127.0.0.1:38432/filing")
    assert calls[0][-5:] == ["-d", "--wait", "--wait-timeout", "120", "db"]
    assert calls[1] == ["up", "--build", "-d"]
    assert calls[2] == "http://127.0.0.1:38010"


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
    with pytest.raises(setup.ConfigurationError, match="unset EMBEDDING_PROVIDER") as failure:
        setup.quickstart(configured)
    assert str(configured / ".env") in str(failure.value)
    assert "No services were started by this configuration check" in str(failure.value)
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
    with pytest.raises(RuntimeError, match="Schema is still blocked"):
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
    diagnosis = Mock()
    monkeypatch.setattr(setup, "diagnose", diagnosis)
    with pytest.raises(RuntimeError, match="Readiness is unconfirmed"):
        setup.quickstart(configured)
    diagnosis.assert_called_once()
    readiness.assert_not_called()
    result = capsys.readouterr().out
    assert "Service ready:" not in result
    assert "Startup/readiness blocked" in result


def test_configuration_reports_sources_without_exposing_credentials(configured, monkeypatch):
    """Public selector conflicts show both sources while private values remain hidden."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
    monkeypatch.setenv("SEC_USER_AGENT", "private-invalid-contact")
    with pytest.raises(setup.ConfigurationError) as failure:
        setup.validate_configuration(configured)
    message = str(failure.value)
    assert '.env="openai"; shell="deterministic"; effective source=shell export' in message
    assert "unset EMBEDDING_PROVIDER" in message
    assert str(configured / ".env") in message
    assert "private-invalid-contact" not in message
    assert "test-openai" not in message and "test-dart" not in message


@pytest.mark.parametrize("choice", ["f", "e"])
def test_configuration_repairs_the_current_step_without_starting_services(
    configured, monkeypatch, choice
):
    """The user can remove an override or persist public defaults without rerunning setup."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
    monkeypatch.setattr(setup.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: choice)
    original = (configured / ".env").read_text()
    bindings = setup.configure(configured)
    assert bindings["APP_PORT"] == "38010"
    if choice == "f":
        assert "EMBEDDING_PROVIDER" not in setup.os.environ
        assert (configured / ".env").read_text() == original
    else:
        assert setup.os.environ["EMBEDDING_PROVIDER"] == "openai"
        assert (
            setup.dotenv_values(configured / ".env")["EMBEDDING_MODEL"] == "text-embedding-3-large"
        )
        assert "OPENAI_API_KEY_LOCAL=test-openai" in (configured / ".env").read_text()


def test_configuration_rechecks_after_an_external_edit(configured, monkeypatch):
    """Repairing the named file resumes the blocked check without recreating the template."""
    path = configured / ".env"
    path.write_text(
        path.read_text().replace("EMBEDDING_PROVIDER=openai", "EMBEDDING_PROVIDER=wrong")
    )
    monkeypatch.setattr(setup.sys.stdin, "isatty", lambda: True)

    def repair(_prompt):
        """Simulate the user's editor changing only the reported public selector."""
        path.write_text(
            path.read_text().replace("EMBEDDING_PROVIDER=wrong", "EMBEDDING_PROVIDER=openai")
        )
        return "r"

    monkeypatch.setattr("builtins.input", repair)
    assert setup.configure(configured)["DB_PORT"] == "38432"


@pytest.mark.parametrize(
    "outcome,expected", [("cancelled", 0), ("incomplete", 1), ("succeeded", 0)]
)
def test_host_clean_start_waits_for_verified_reset_before_starting(
    configured, monkeypatch, capsys, outcome, expected
):
    """Cancellation and partial reset stop before startup; success reaches the exact web step."""
    calls = []
    monkeypatch.setattr(setup.subprocess, "check_output", lambda *a, **k: "2.39.0")
    monkeypatch.setattr(setup, "ensure_database", lambda *a: calls.append("db"))

    def reset(root, **options):
        """Return the reset's explicit state after recording its caller intent."""
        assert root == configured
        assert options == {"keep_sources": True, "sample": False, "restart_planned": True}
        calls.append("reset")
        return outcome

    monkeypatch.setattr(setup, "recreate_schema", reset)
    monkeypatch.setattr(setup, "start_ready", lambda *a, **k: calls.append("ready"))
    assert setup.quickstart(configured, reset=True, keep_sources=True) == expected
    output = capsys.readouterr().out
    if outcome == "succeeded":
        assert calls == ["db", "reset", "ready"]
        assert "/docs/en/quickstart-dev/#qs-web-1" in output
        assert "/docs/ko/quickstart-dev/#qs-web-1" in output
        assert output.isascii()
        assert "\x1b" not in output
    else:
        assert calls == ["db", "reset"]
        assert "Service ready:" not in output


def test_startup_failure_diagnoses_and_restarts_once(configured, monkeypatch):
    """Recovery preserves volumes and runs only after an explicit restart choice."""
    from unittest.mock import Mock

    calls = []
    results = iter([7, 0, 0])

    def run(mode, args, *, root, quiet=False):
        """Fail the first start, then allow the confirmed down/up sequence."""
        calls.append(args)
        return next(results)

    diagnosis = Mock()
    monkeypatch.setattr(setup, "run", run)
    monkeypatch.setattr(setup, "diagnose", diagnosis)
    monkeypatch.setattr(setup, "confirm", lambda _: True)
    monkeypatch.setattr(setup, "report_services", lambda *a: None)
    ready = Mock()
    monkeypatch.setattr(setup, "wait_ready", ready)
    setup.start_ready(configured, setup.validate_configuration(configured))
    assert calls == [["up", "--build", "-d"], ["down"], ["up", "--build", "-d"]]
    diagnosis.assert_called_once_with(configured, "http://127.0.0.1:38010", details=True)
    ready.assert_called_once()


@pytest.mark.parametrize("choice", ["q", "", None])
def test_configuration_cancellation_stops_before_database_work(
    configured, monkeypatch, capsys, choice
):
    """Quit, default decline and EOF preserve configuration and block every later setup action."""
    from unittest.mock import Mock

    before = (configured / ".env").read_bytes()
    monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
    monkeypatch.setenv("SEC_USER_AGENT", "private-invalid-contact")
    monkeypatch.setattr(setup.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(setup.subprocess, "check_output", lambda *a, **k: "2.39.0")

    def reply(_prompt):
        """Represent an explicit answer or terminal EOF without accessing a user shell."""
        if choice is None:
            raise EOFError
        return choice

    forbidden = Mock(side_effect=AssertionError("cancellation must stop setup"))
    monkeypatch.setattr("builtins.input", reply)
    for name in ("ensure_database", "recreate_schema", "start_ready", "handoff"):
        monkeypatch.setattr(setup, name, forbidden)
    with pytest.raises(setup.SetupCancelledError):
        setup.quickstart(configured, reset=True)
    forbidden.assert_not_called()
    assert (configured / ".env").read_bytes() == before
    output = capsys.readouterr().out
    for secret in ("private-invalid-contact", "test-openai", "test-dart"):
        assert secret not in output


def test_startup_failure_after_reset_cannot_repeat_deletion_or_print_ready(configured, monkeypatch):
    """A verified reset is performed once even when the following startup remains blocked."""
    from unittest.mock import Mock

    monkeypatch.setattr(setup.subprocess, "check_output", lambda *a, **k: "2.39.0")
    monkeypatch.setattr(setup, "ensure_database", Mock())
    reset = Mock(return_value="succeeded")
    startup = Mock(side_effect=RuntimeError("fixture readiness failed"))
    handoff = Mock()
    monkeypatch.setattr(setup, "recreate_schema", reset)
    monkeypatch.setattr(setup, "start_ready", startup)
    monkeypatch.setattr(setup, "handoff", handoff)
    with pytest.raises(RuntimeError, match="fixture readiness failed"):
        setup.quickstart(configured, reset=True)
    reset.assert_called_once_with(
        configured, keep_sources=False, sample=False, restart_planned=True
    )
    startup.assert_called_once()
    handoff.assert_not_called()


@pytest.mark.parametrize("failure", ["command", "readiness"])
def test_second_startup_failure_never_offers_a_third_attempt(configured, monkeypatch, failure):
    """Both command and readiness failures receive at most one confirmed down/up recovery."""
    from unittest.mock import Mock

    launch = Mock(side_effect=[7, 0, 8] if failure == "command" else [0, 0, 0])
    ready = Mock(side_effect=RuntimeError("fixture readiness failed"))
    diagnose = Mock()
    confirm = Mock(return_value=True)
    monkeypatch.setattr(setup, "run", launch)
    monkeypatch.setattr(setup, "wait_ready", ready)
    monkeypatch.setattr(setup, "diagnose", diagnose)
    monkeypatch.setattr(setup, "confirm", confirm)
    monkeypatch.setattr(setup, "report_services", Mock())
    with pytest.raises(RuntimeError, match="Readiness is unconfirmed"):
        setup.start_ready(configured, setup.validate_configuration(configured))
    assert [call.args[1] for call in launch.call_args_list] == [
        ["up", "--build", "-d"],
        ["down"],
        ["up", "--build", "-d"],
    ]
    assert diagnose.call_count == 2
    confirm.assert_called_once()
    assert ready.call_count == (0 if failure == "command" else 2)


def test_failed_stop_prevents_another_startup_attempt(configured, monkeypatch):
    """A failed volume-preserving stop cannot be followed by another up command."""
    from unittest.mock import Mock

    launch = Mock(side_effect=[7, 9])
    monkeypatch.setattr(setup, "run", launch)
    monkeypatch.setattr(setup, "diagnose", Mock())
    monkeypatch.setattr(setup, "confirm", Mock(return_value=True))
    with pytest.raises(RuntimeError, match="Stopping this checkout failed"):
        setup.start_ready(configured, setup.validate_configuration(configured))
    assert [call.args[1] for call in launch.call_args_list] == [["up", "--build", "-d"], ["down"]]


def test_second_database_failure_stops_before_reset(configured, monkeypatch):
    """A failed second DB start cannot reach the irreversible preview or trigger a third retry."""
    from unittest.mock import Mock

    monkeypatch.setattr(setup.subprocess, "check_output", lambda *a, **k: "2.39.0")
    database = Mock(side_effect=setup.subprocess.CalledProcessError(1, ["docker", "compose"]))
    confirm = Mock(return_value=True)
    launch = Mock(return_value=0)
    reset = Mock()
    monkeypatch.setattr(setup, "ensure_database", database)
    monkeypatch.setattr(setup, "confirm", confirm)
    monkeypatch.setattr(setup, "run", launch)
    monkeypatch.setattr(setup, "recreate_schema", reset)
    with pytest.raises(setup.subprocess.CalledProcessError):
        setup.quickstart(configured, reset=True)
    assert database.call_count == 2
    confirm.assert_called_once()
    launch.assert_called_once_with("dev", ["down"], root=configured)
    reset.assert_not_called()


def test_second_schema_failure_cannot_reset_or_start_services(configured, monkeypatch):
    """Retrying a read-only schema check once never turns it into implicit recreation."""
    from unittest.mock import Mock

    monkeypatch.setattr(setup.subprocess, "check_output", lambda *a, **k: "2.39.0")
    database = Mock()
    prepare = AsyncMock(side_effect=setup.SchemaDriftError("fixture drift"))
    confirm = Mock(return_value=True)
    forbidden = Mock()
    monkeypatch.setattr(setup, "ensure_database", database)
    monkeypatch.setattr(setup, "prepare_schema", prepare)
    monkeypatch.setattr(setup, "confirm", confirm)
    monkeypatch.setattr(setup, "recreate_schema", forbidden)
    monkeypatch.setattr(setup, "start_ready", forbidden)
    with pytest.raises(RuntimeError, match="Schema is still blocked"):
        setup.quickstart(configured)
    assert database.call_count == prepare.await_count == 2
    confirm.assert_called_once()
    forbidden.assert_not_called()


def test_handoff_links_to_developer_quick_start(capsys):
    """Keep setup handoffs on the localized DEV guide and preserve its checkpoint."""
    setup.handoff({"DOCREVIEW_LOCAL_HOST": "127.0.0.1", "APP_PORT": "38010"})
    output = capsys.readouterr().out
    for locale in ("en", "ko"):
        assert (
            f"http://127.0.0.1:38010/docreview-rag/docs/{locale}/quickstart-dev/#qs-web-1"
            in output
        )
    assert "Quick Start - DEV ONLY" in output
    assert output.isascii()


@pytest.fixture(autouse=True)
def isolated_progress_io(monkeypatch):
    """Keep orchestration fixtures isolated; subprocess output has its own process tests."""
    monkeypatch.setattr(setup, "write_receipt", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        setup,
        "run_step",
        lambda title, command, **kwargs: setup.subprocess.run(command, check=True, **kwargs),
    )
