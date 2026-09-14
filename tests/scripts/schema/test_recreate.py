"""Explicit database recreation uses confirmation and atomic, non-cascading deletion."""

import asyncio
import os
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.schema import recreate as command


@pytest.mark.parametrize("answer", ["", "yes", "confirm"])
def test_wrong_confirmation_never_stops_or_deletes(tmp_path, monkeypatch, answer):
    """Only the single uppercase Y can progress beyond the read-only preview."""
    target = {"port": "12345", "apps": ["app"], "volume": "fixture", "docker": ["docker"]}
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(command, "local_target", lambda root: (target, {}))
    operation = AsyncMock(return_value={"documents": 1})
    stop = Mock()
    monkeypatch.setattr(command, "recreate", operation)
    monkeypatch.setattr(command.subprocess, "run", stop)
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    assert command.run(tmp_path) == "cancelled"
    assert operation.await_count == 1
    assert operation.await_args.args == (
        "postgresql+asyncpg://filing:filing@127.0.0.1:12345/filing",
    )
    stop.assert_not_called()


def test_noninteractive_recreate_does_not_inspect_or_mutate(tmp_path, monkeypatch):
    """Piped confirmation is never accepted."""
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: False)
    target = Mock()
    monkeypatch.setattr(command, "local_target", target)
    with pytest.raises(ValueError, match="interactive"):
        command.run(tmp_path)
    target.assert_not_called()


def test_remote_docker_is_rejected_before_contact(tmp_path, monkeypatch):
    """An external Docker daemon cannot redirect the local destructive operation."""
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.example:2375")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    contact = Mock()
    monkeypatch.setattr(command.subprocess, "check_output", contact)
    with pytest.raises(ValueError, match="local Docker"):
        command.local_target(tmp_path)
    contact.assert_not_called()


@pytest.mark.live_postgres
def test_recreate_rolls_back_foreign_dependencies_and_preserves_unrelated_data():
    """Use a disposable legacy DB to verify actual rollback and then successful ORM creation."""
    url = os.environ.get("SCHEMA_TEST_ADMIN_URL")
    if not url:
        pytest.skip("SCHEMA_TEST_ADMIN_URL must identify an isolated test server")
    name = "recreate_" + uuid4().hex

    async def scenario():
        """Own one fixture DB; never connect to the user's database for destructive checks."""
        admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
        target = url.rsplit("/", 1)[0] + "/" + name
        engine = create_async_engine(target)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("CREATE TABLE documents (id integer PRIMARY KEY)"))
                await connection.execute(text("INSERT INTO documents VALUES (1)"))
                await connection.execute(
                    text(
                        "CREATE TABLE user_sentinel (id integer REFERENCES documents(id), "
                        "value text)"
                    )
                )
                await connection.execute(text("INSERT INTO user_sentinel VALUES (1, 'keep')"))
            await engine.dispose()
            preview = await command.recreate(target)
            assert preview == {"documents": 1}
            with pytest.raises(SQLAlchemyError):
                await command.recreate(target, preview)
            async with engine.begin() as connection:
                assert (
                    await connection.execute(text("SELECT count(*) FROM documents"))
                ).scalar_one() == 1
                assert (
                    await connection.execute(text("SELECT value FROM user_sentinel"))
                ).scalar_one() == "keep"
                await connection.execute(
                    text("ALTER TABLE user_sentinel DROP CONSTRAINT user_sentinel_id_fkey")
                )
            await engine.dispose()
            result = await command.recreate(target, preview)
            assert "chunk_embeddings" in result and not any(result.values())
            async with engine.connect() as connection:
                assert (
                    await connection.execute(text("SELECT value FROM user_sentinel"))
                ).scalar_one() == "keep"
        finally:
            await engine.dispose()
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{name}"'))
            await admin.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["expired", "changed"])
def test_stale_preview_never_stops_or_deletes(tmp_path, monkeypatch, boundary):
    """Confirmation cannot authorize a stale preview or another database target."""
    target = {"port": "12345", "apps": ["app"], "volume": "fixture", "docker": ["docker"]}
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: True)
    replies = [(target, {}), ({**target, "port": "12346"}, {})]
    monkeypatch.setattr(command, "local_target", Mock(side_effect=replies))
    operation = AsyncMock(return_value={"documents": 1})
    stop = Mock()
    monkeypatch.setattr(command, "recreate", operation)
    monkeypatch.setattr(command.subprocess, "run", stop)
    monkeypatch.setattr("builtins.input", lambda prompt: "Y")
    from types import SimpleNamespace

    monkeypatch.setattr(
        command,
        "time",
        SimpleNamespace(monotonic=iter([0, 301 if boundary == "expired" else 1]).__next__),
    )
    with pytest.raises(ValueError, match="expired" if boundary == "expired" else "changed"):
        command.run(tmp_path)
    assert operation.await_count == 1
    stop.assert_not_called()


@pytest.mark.parametrize("retry", [False, True])
def test_permission_preview_offers_exact_owner_fix_before_one_retry(
    tmp_path, monkeypatch, capsys, retry
):
    """Source permission recovery never applies ACLs or enters a destructive operation."""
    import errno

    source = tmp_path / "data/raw source.html"
    source.parent.mkdir()
    source.write_text("preserve")
    clean_preview = command.source_preview(tmp_path)
    preview = Mock(
        side_effect=[PermissionError(errno.EACCES, "denied", str(source)), clean_preview]
    )
    apply = Mock()
    monkeypatch.setattr(command, "source_preview", preview)
    monkeypatch.setattr(command, "confirm", lambda _: retry)
    monkeypatch.setattr(command.subprocess, "run", apply)
    if retry:
        assert command.preview_sources(tmp_path) == clean_preview
        assert preview.call_count == 2
    else:
        with pytest.raises(ValueError, match="no deletion was submitted"):
            command.preview_sources(tmp_path)
        assert preview.call_count == 1
    output = capsys.readouterr().out
    assert "sudo setfacl -R -m" in output
    assert str(source) in output
    assert source.read_text() == "preserve"
    apply.assert_not_called()


@pytest.mark.parametrize("restart_planned", [False, True])
def test_successful_reset_reports_the_callers_restart_intent(
    tmp_path, monkeypatch, capsys, restart_planned
):
    """The host caller may plan a later restart, but recreation itself only stops the API."""
    target = {"port": "12345", "apps": ["fixture-app"], "volume": "fixture", "docker": ["docker"]}
    operation = AsyncMock(side_effect=[{"documents": 1}, {"documents": 0}])
    stop = Mock()
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(command, "local_target", lambda root: (target, {}))
    monkeypatch.setattr(command, "recreate", operation)
    monkeypatch.setattr(command.subprocess, "run", stop)
    monkeypatch.setattr("builtins.input", lambda _: "Y")
    assert command.run(tmp_path, keep_sources=True, restart_planned=restart_planned) == "succeeded"
    assert operation.await_count == 2
    stop.assert_called_once_with(
        ["docker", "stop", "fixture-app"], env={}, check=True, stdout=command.subprocess.DEVNULL
    )
    output = capsys.readouterr().out
    if restart_planned:
        assert "Guided setup will now rebuild/start DEV and verify readiness" in output
        assert "not restarted automatically" not in output
    else:
        assert "not restarted automatically" in output
        assert "Run rag-dev start" in output


@pytest.mark.parametrize("owner_repairs", [False, True])
def test_real_unreadable_source_offers_quoted_owner_paths_and_one_retry(
    tmp_path, monkeypatch, capsys, owner_repairs
):
    """A real mode denial needs an owner repair; the command never applies access changes itself."""
    import shlex

    if os.geteuid() == 0:
        pytest.skip("Root bypasses the Unix mode-denial fixture.")
    source = tmp_path / "data/corpus/sec/owner/source owner's report.html"
    source.parent.mkdir(parents=True)
    source.write_text("preserve these real bytes")
    source.chmod(0)
    preview = Mock(wraps=command.source_preview)
    apply = Mock(side_effect=AssertionError("permission commands must not run automatically"))

    def owner_choice(_message):
        """Let this fixture's owner grant actual read access only for the successful retry case."""
        if owner_repairs:
            source.chmod(0o600)
        return True

    confirm = Mock(side_effect=owner_choice)
    monkeypatch.setattr(command, "source_preview", preview)
    monkeypatch.setattr(command, "confirm", confirm)
    monkeypatch.setattr(command.subprocess, "run", apply)
    try:
        with pytest.raises(PermissionError):
            source.read_bytes()
        if owner_repairs:
            result = command.preview_sources(tmp_path)
            assert set(result["files"]) == {str(source.relative_to(tmp_path / "data/corpus"))}
            assert source.read_text() == "preserve these real bytes"
        else:
            with pytest.raises(ValueError, match="no deletion was submitted"):
                command.preview_sources(tmp_path)
        assert preview.call_count == 2
        confirm.assert_called_once()
        apply.assert_not_called()
        hints = [
            line.strip()
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("  sudo setfacl")
        ]
        assert hints
        assert all(
            shlex.split(line)
            == [
                "sudo",
                "setfacl",
                "-R",
                "-m",
                f"u:{os.geteuid()}:rwX",
                "--",
                str(source.parent),
                str(source),
            ]
            for line in hints
        )
    finally:
        source.chmod(0o600)


def test_permission_hint_never_targets_another_checkout(tmp_path, monkeypatch, capsys):
    """An outside-path denial cannot suggest broad ACL changes or offer a retry."""
    import errno

    outside = tmp_path.parent / "another-checkout/private-source.html"
    monkeypatch.setattr(
        command,
        "source_preview",
        Mock(side_effect=PermissionError(errno.EACCES, "denied", str(outside))),
    )
    confirm = Mock()
    monkeypatch.setattr(command, "confirm", confirm)
    with pytest.raises(ValueError, match="outside this checkout"):
        command.preview_sources(tmp_path)
    confirm.assert_not_called()
    assert "setfacl" not in capsys.readouterr().out


def test_declined_permission_repair_precedes_docker_and_deletion_confirmation(
    tmp_path, monkeypatch, capsys
):
    """An unreadable real source blocks all Docker, database and typed-deletion activity."""
    if os.geteuid() == 0:
        pytest.skip("Root bypasses the Unix mode-denial fixture.")
    source = tmp_path / "data/corpus/sec/private/private.html"
    source.parent.mkdir(parents=True)
    source.write_text("keep")
    source.chmod(0)
    forbidden = Mock(side_effect=AssertionError("permission preview must stop first"))
    confirm = Mock(return_value=False)
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(command, "confirm", confirm)
    monkeypatch.setattr(command, "local_target", forbidden)
    monkeypatch.setattr(command, "recreate", forbidden)
    monkeypatch.setattr(command.subprocess, "run", forbidden)
    monkeypatch.setattr("builtins.input", forbidden)
    try:
        with pytest.raises(ValueError, match="no deletion was submitted"):
            command.run(tmp_path)
        confirm.assert_called_once()
        forbidden.assert_not_called()
        assert "DANGER:" not in capsys.readouterr().out
    finally:
        source.chmod(0o600)
    assert source.read_text() == "keep"


def test_keep_sources_requires_readable_journal_state_before_docker(tmp_path, monkeypatch):
    """Keeping raw files never allows an inaccessible unfinished journal to be ignored."""
    if os.geteuid() == 0:
        pytest.skip("Root bypasses the Unix mode-denial fixture.")
    data = tmp_path / "data"
    (data / ".schema-recreate-journal").mkdir(parents=True)
    data.chmod(0)
    forbidden = Mock(side_effect=AssertionError("unconfirmed journal state must stop setup"))
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(command, "confirm", Mock(return_value=False))
    monkeypatch.setattr(command, "source_preview", forbidden)
    monkeypatch.setattr(command, "local_target", forbidden)
    monkeypatch.setattr(command.subprocess, "run", forbidden)
    monkeypatch.setattr("builtins.input", forbidden)
    try:
        with pytest.raises(ValueError, match="no deletion was submitted"):
            command.run(tmp_path, keep_sources=True)
        forbidden.assert_not_called()
    finally:
        data.chmod(0o700)


@pytest.mark.parametrize("repair", [False, True])
def test_unwritable_source_parents_block_confirmation_until_one_repair(
    tmp_path, monkeypatch, capsys, repair
):
    """Readable container-style directories must be writable before confirmation or API stop."""
    if os.geteuid() == 0:
        pytest.skip("Root bypasses the Unix write-permission fixture.")
    corpus = tmp_path / "data/corpus"
    blocked = [corpus / "sec", corpus / "sec/filing", corpus / "dart/receipt"]
    for directory in (blocked[1], blocked[2]):
        directory.mkdir(parents=True)
        (directory / "source.html").write_text("original source")
    for directory in blocked:
        directory.chmod(0o555)
    stop = Mock()
    target = Mock(
        return_value=(
            {"port": "1", "apps": ["fixture-app"], "volume": "fixture", "docker": ["docker"]},
            {},
        )
    )
    confirm_input = Mock(return_value="Y")

    def owner_repair(_prompt):
        """Only the fixture owner changes access; the reset code never executes the hint."""
        if _prompt.startswith("Confirm"):
            return confirm_input(_prompt) == "Y"
        if repair:
            for directory in blocked:
                directory.chmod(0o755)
        return repair

    repair_prompt = Mock(side_effect=owner_repair)
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(command, "confirm", repair_prompt)
    monkeypatch.setattr(command, "local_target", target)
    monkeypatch.setattr(command, "recreate", AsyncMock(return_value={}))
    monkeypatch.setattr(command.subprocess, "run", stop)
    monkeypatch.setattr("builtins.input", confirm_input)
    try:
        if repair:
            assert command.run(tmp_path) == "succeeded"
            confirm_input.assert_called_once()
            stop.assert_called_once()
        else:
            with pytest.raises(ValueError, match="permissions remain blocked"):
                command.run(tmp_path)
            confirm_input.assert_not_called()
            target.assert_not_called()
            stop.assert_not_called()
            assert all(
                (directory / "source.html").read_text() == "original source"
                for directory in (blocked[1], blocked[2])
            )
        output = capsys.readouterr().out
        assert "sudo setfacl -R -m" in output
        assert all(f"Blocked: {directory}" in output for directory in blocked)
        assert repair_prompt.call_count == (2 if repair else 1)
    finally:
        for directory in blocked:
            directory.chmod(0o755)


def test_permission_failure_after_stop_restores_sources_and_explains_recovery(
    tmp_path, monkeypatch, capsys
):
    """A late filesystem failure cannot strand the API behind a bare errno message."""
    corpus = tmp_path / "data/corpus"
    corpus.mkdir(parents=True)
    source = corpus / "original.html"
    source.write_text("preserve original bytes")
    stage = command.SourceReset.stage

    def fail_after_staging(reset):
        """Move real fixture files, then simulate a late permission loss before DB work."""
        stage(reset)
        raise PermissionError(13, "fixture denied", str(source))

    target = {"port": "1", "apps": ["fixture-app"], "volume": "fixture", "docker": ["docker"]}
    operation = AsyncMock(return_value={})
    stop = Mock()
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(command, "local_target", lambda _: (target, {}))
    monkeypatch.setattr(command, "recreate", operation)
    monkeypatch.setattr(command.subprocess, "run", stop)
    monkeypatch.setattr(command.SourceReset, "stage", fail_after_staging)
    monkeypatch.setattr("builtins.input", lambda _: "Y")
    with pytest.raises(ValueError, match="filesystem permissions") as caught:
        command.run(tmp_path, restart_planned=True)
    assert "[Errno" not in str(caught.value)
    assert source.read_text() == "preserve original bytes"
    assert not (tmp_path / "data/.schema-recreate-journal").exists()
    assert operation.await_count == 1
    stop.assert_called_once_with(
        ["docker", "stop", "fixture-app"], env={}, check=True, stdout=command.subprocess.DEVNULL
    )
    output = capsys.readouterr().err
    assert "database and sources are unchanged" in output
    assert "rag-dev up -d" in output


def test_api_stop_failure_also_explains_the_unchanged_data_and_recovery(
    tmp_path, monkeypatch, capsys
):
    """A failed stop request may have stopped a container and must still give recovery steps."""
    target = {"port": "1", "apps": ["fixture-app"], "volume": "fixture", "docker": ["docker"]}
    operation = AsyncMock(return_value={})
    monkeypatch.setattr(command.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(command, "local_target", lambda _: (target, {}))
    monkeypatch.setattr(command, "recreate", operation)
    monkeypatch.setattr(
        command.subprocess,
        "run",
        Mock(side_effect=command.subprocess.CalledProcessError(1, ["docker", "stop"])),
    )
    monkeypatch.setattr("builtins.input", lambda _: "Y")
    with pytest.raises(command.subprocess.CalledProcessError):
        command.run(tmp_path)
    assert operation.await_count == 1
    output = capsys.readouterr().err
    assert "database and sources are unchanged" in output
    assert "rag-dev up -d" in output


def test_keep_sources_does_not_require_source_directory_write_access(tmp_path):
    """The explicit source-preserving reset remains usable on a read-only source directory."""
    corpus = tmp_path / "data/corpus"
    corpus.mkdir(parents=True)
    source = corpus / "keep.html"
    source.write_text("keep these bytes")
    corpus.chmod(0o555)
    try:
        assert command.preview_sources(tmp_path, keep_sources=True) is None
        assert source.read_text() == "keep these bytes"
    finally:
        corpus.chmod(0o755)
