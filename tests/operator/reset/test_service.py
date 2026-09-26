"""Reset confirmation boundaries and disposable Docker recovery verification."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from app.ingestion.sources.models import CorpusIdentity, Manifest
from app.operator.reset.commands import WipeError
from app.operator.reset.service import WipeService
from tests.live_postgres import live_postgres_unavailable


@pytest.mark.parametrize(
    "recorded",
    [
        {"status": "running", "completed": []},
        {"result": None, "lease": None, "lease_instance": None, "lease_daemon": None},
    ],
)
def test_old_or_invalid_audit_never_becomes_idle_state(tmp_path, recorded):
    """Reject unsupported audit shapes without changing evidence or starting reset work."""
    service = WipeService(tmp_path, lambda: False)
    service._audit.write_text(json.dumps(recorded))
    before = service._audit.read_bytes()

    with pytest.raises(WipeError):
        WipeService(tmp_path, lambda: False)

    assert service._audit.read_bytes() == before


def test_confirmation_rejects_changed_expired_and_duplicate_previews(tmp_path, monkeypatch):
    """A preview cannot authorize another state or be consumed twice."""
    service = WipeService(tmp_path, lambda: False)
    target = {"version": 1}

    async def inspect():
        """Return a controlled target fingerprint without accessing Docker."""
        return dict(target)

    async def execute(_target):
        """Finish an isolated authorization test without any destructive commands."""
        service._result["status"] = "succeeded"
        service._release_operation()

    monkeypatch.setattr(service, "inspect", inspect)
    monkeypatch.setattr(service, "_execute", execute)

    async def scenario():
        """Exercise all confirmation paths against the production state machine."""
        preview = await service.preview()
        with pytest.raises(WipeError, match="does not match"):
            await service.start(preview["token"], "wrong")
        target["version"] = 2
        with pytest.raises(WipeError, match="changed"):
            await service.start(preview["token"], preview["confirmation"])
        preview = await service.preview()
        assert service._preview is not None
        service._preview["expires"] = 0
        with pytest.raises(WipeError, match="expired"):
            await service.start(preview["token"], preview["confirmation"])
        preview = await service.preview()
        await service.start(preview["token"], preview["confirmation"])
        assert service._task is not None
        await service._task
        with pytest.raises(WipeError, match="missing"):
            await service.start(preview["token"], preview["confirmation"])

    asyncio.run(scenario())


def test_active_operations_block_inspection(tmp_path):
    """No Docker inspection or reset begins while a managed command runs."""
    with pytest.raises(WipeError, match="active local operations"):
        asyncio.run(WipeService(tmp_path, lambda: True).inspect())


@pytest.mark.live_postgres
def test_disposable_compose_reset_recreates_empty_schema(tmp_path, monkeypatch):
    """Erase only an isolated test volume and verify a real empty pgvector schema."""
    image = os.environ.get("DOCREVIEW_WIPE_TEST_IMAGE")
    if not image:
        live_postgres_unavailable(
            "Set DOCREVIEW_WIPE_TEST_IMAGE to a freshly built application image."
        )
    root = tmp_path / "docreview-wipe-test"
    root.mkdir()
    (root / "docker").mkdir()
    repository = Path(__file__).resolve().parents[3]
    (root / "app").symlink_to(repository / "app", target_is_directory=True)
    (root / ".venv").symlink_to(repository / ".venv", target_is_directory=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    project = f"wipe-test-{hashlib.sha256(str(root).encode()).hexdigest()[:10]}"
    # Give each disposable checkout its own Compose project name through its basename.
    destination = root.with_name(project)
    root.rename(destination)
    root = destination
    (root / ".env").write_text("# preserved test configuration\n")
    for name in (
        "data/corpus/raw.html",
        "data/eval_runs/result.json",
        "data/local-settings/local-llm.json",
    ):
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("disposable data")
    # Match local Compose: the non-root app shares writable data with the host group.
    for name in ("data", "data/corpus", "data/eval_runs", "data/local-settings"):
        (root / name).chmod(0o775)
    preserved = root / "data/corpus/manifest.json"
    Manifest(corpus=CorpusIdentity(corpus_id="reset-test", name="Reset test")).write(preserved)
    preserved_manifest = preserved.read_text()
    preserved_sources = (
        "data/golden/untracked.json",
        "data/corpus/sec/TEST/profile.json",
        "docs/TUTORIAL/ko/test.md",
        "docs/images/test.svg",
        "keys/test.key",
        "unrelated.txt",
    )
    for name in preserved_sources:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("preserved source")
    (root / "docker/docker-compose.yml").write_text(f"""services:
  db:
    cpuset: 0-1
    cpus: 2
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: filing
      POSTGRES_PASSWORD: filing
      POSTGRES_DB: filing
    ports: ['127.0.0.1:{port}:5432']
    volumes: ['pg_data:/var/lib/postgresql/data']
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U filing -d filing']
      interval: 1s
      retries: 30
  app:
    cpuset: 0-1
    cpus: 2
    user: "10001:{os.getgid()}"
    image: {json.dumps(image)}
    pull_policy: never
    command:
      - sh
      - -c
      - 'umask 0002; exec "$$@"'
      - --
      - /app/.venv/bin/python
      - -m
      - uvicorn
      - app.release.space:app
      - --host
      - 0.0.0.0
      - --port
      - '8000'
      - --workers
      - '1'
      - --log-level
      - warning
    volumes:
      - {repository}/app:/app/app:ro
      - {root}/data:/app/data
    environment:
      MODE: dev
      DOCREVIEW_MODE: runtime
      DOCREVIEW_ADMIN_MODE: live
      DOCREVIEW_HOST: 127.0.0.1
      DATABASE_URL: postgresql+asyncpg://filing:filing@db:5432/filing
      CORPUS_DIR: /app/data/corpus
      EMBEDDING_PROVIDER: deterministic
      LOCAL_LLM_BASE_URL: ''
      OPENAI_API_KEY_LOCAL: ''
      OPENAI_API_KEY_PROD: ''
      DART_API_KEY: ''
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ['CMD', 'python', '-c', "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]
      interval: 1s
      retries: 30
volumes:
  pg_data:
""")
    (root / "docker/docker-compose.dev.yml").write_text("services: {}\n")
    service = WipeService(root, lambda: False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    async def scenario():
        """Run the destructive path solely against the declared disposable checkout."""
        try:
            await service.commands.verify_docker_identity()
            await service.commands.run(*service.commands.compose_command("up", "-d", "--wait"))
            target = await service.inspect()
            assert (await service.capability())["available"] is True
            await service.commands.run(
                "docker",
                "exec",
                target["app_container"],
                "python",
                "-c",
                "import json, pathlib; "
                "p = pathlib.Path('/tmp/docreview-runtime-gate-1-test.json'); "
                "p.write_text(json.dumps({'pid': 1, 'token': 'disposable-token'})); p.chmod(0o600)",
            )
            assert (await service.capability())["available"] is False
            await service.commands.run(
                "docker",
                "exec",
                target["app_container"],
                "python",
                "-c",
                "import pathlib; pathlib.Path('/tmp/docreview-runtime-gate-1-test.json').unlink()",
            )
            overlay = root / "docker/docker-compose.dev.yml"
            overlay.write_text(
                "services: {}\nvolumes:\n  pg_data:\n    driver: local\n"
                "    driver_opts:\n      type: none\n      o: bind\n      device: /unapproved\n"
            )
            with pytest.raises(WipeError, match="Compose configuration differs"):
                await service.preview()
            overlay.write_text("services: {}\n")
            await service.commands.query_database(
                target["database_container"],
                "CREATE TABLE wipe_probe(id int); INSERT INTO wipe_probe VALUES(1); "
                "INSERT INTO operator_jobs "
                "(job_id, domain, kind, request_json, status, stage, "
                "current, message, result_refs) "
                "VALUES ('fixture-active-job', 'corpus', 'ingest_manifest', '{}', 'running', "
                "'starting', 0, 'Fixture active job', '{}')",
            )
            with pytest.raises(WipeError, match="Finish active jobs"):
                await service.preview()
            await service.commands.query_database(
                target["database_container"], "DELETE FROM operator_jobs"
            )
            preview = await service.preview()
            overlay.write_text(
                "services:\n  app:\n    environment:\n      DOCREVIEW_TEST: changed\n"
            )
            with pytest.raises(WipeError, match="changed"):
                await service.start(preview["token"], preview["confirmation"])
            overlay.write_text("services: {}\n")
            preview = await service.preview()
            assert preview["target"]["tables"]["wipe_probe"] == 1
            await service.start(preview["token"], preview["confirmation"])
            assert service._task is not None
            await service._task
            assert service.result()["status"] == "succeeded", service.result()
            after = await service.inspect()
            assert after["tables"]["documents"] == 0
            assert "wipe_probe" not in after["tables"]
            assert not after["files"]
            assert preserved.read_text() == preserved_manifest
            assert (root / ".env").exists()
            assert (root / "app").is_symlink()
            assert all(
                (root / name).read_text() == "preserved source" for name in preserved_sources
            )
        except WipeError as error:
            logs = await service.commands.run(
                *service.commands.compose_command("logs", "--no-color", "--tail", "50", "app")
            )
            raise AssertionError(f"Disposable app failed: {logs}") from error
        finally:
            await service.commands.run(*service.commands.compose_command("down", "-v"))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mode,database_url",
    [
        ("prod", "postgresql://filing:filing@db:5432/filing"),
        ("dev", "postgresql://filing:filing@remote:5432/filing"),
    ],
)
def test_preview_refuses_production_and_external_database(
    tmp_path, monkeypatch, mode, database_url
):
    """Reject a dangerous runtime identity before any database or filesystem writes."""
    service = WipeService(tmp_path, lambda: False)
    calls = []

    async def run(*args, **_kwargs):
        """Provide Docker identity metadata while recording any unexpected operation."""
        calls.append(args)
        if args[:3] == ("docker", "ps", "-aq"):
            return "db" if args[-1].endswith("=db") else "app"
        if args[:2] == ("docker", "inspect"):
            env = (
                ["POSTGRES_USER=filing", "POSTGRES_DB=filing", "POSTGRES_PASSWORD=filing"]
                if args[-1] == "db"
                else [f"MODE={mode}", "DOCREVIEW_ADMIN_MODE=live", f"DATABASE_URL={database_url}"]
            )
            return json.dumps(
                [
                    {
                        "Config": {
                            "Cmd": ["uvicorn", "app.release.space:app", "--workers", "1"],
                            "Env": env,
                            "Labels": {"com.docker.compose.project.working_dir": str(tmp_path)},
                        }
                    }
                ]
            )
        raise AssertionError(f"Unexpected operation: {args}")

    monkeypatch.setattr(service.commands, "run", run)

    async def local_daemon():
        """Keep this test focused on application rather than Docker endpoint validation."""
        return {"id": "test-local-daemon"}

    monkeypatch.setattr(service.commands, "verify_docker_identity", local_daemon)
    with pytest.raises(WipeError):
        asyncio.run(service.preview())
    assert len(calls) == 4


@pytest.mark.parametrize("endpoint", ["ssh://remote", "tcp://127.0.0.1:2375", "tcp://remote:2375"])
def test_docker_context_refuses_non_unix_targets(tmp_path, monkeypatch, endpoint):
    """Reject remote or forwarded Docker endpoints before inspecting any containers."""
    service = WipeService(tmp_path, lambda: False)
    monkeypatch.setenv("DOCKER_CONTEXT", "isolated-context")
    calls = []

    async def run(*args, **_kwargs):
        """Return only context metadata and fail if Docker data-plane access begins."""
        calls.append(args)
        assert args == ("docker", "context", "inspect", "isolated-context")
        return json.dumps([{"Endpoints": {"docker": {"Host": endpoint}}}])

    monkeypatch.setattr(service.commands, "run", run)
    with pytest.raises(WipeError, match="local Docker Unix socket"):
        asyncio.run(service.preview())
    assert len(calls) == 1


def test_operation_lock_serializes_other_operator_processes(tmp_path):
    """A second service cannot execute reset while another service owns the checkout lock."""
    first = WipeService(tmp_path, lambda: False)
    second = WipeService(tmp_path, lambda: False)
    first._acquire_operation()
    try:
        with pytest.raises(WipeError, match="Another operator"):
            second._acquire_operation()
    finally:
        first._release_operation()
    second._acquire_operation()
    second._release_operation()


def test_failed_hold_is_released_before_any_stop_and_restart_keeps_evidence(tmp_path, monkeypatch):
    """Reject a changed worker after hold and preserve a durable failed result without deletion."""
    service = WipeService(tmp_path, lambda: False)
    target = {"app_container": "test-app", "gate_instance": "old-worker", "daemon": {"id": "local"}}
    events = []

    async def run(*args, **_kwargs):
        """Permit only bootstrap import preflight; stop and deletion must never be reached."""
        assert args[0].endswith("/.venv/bin/python")
        return ""

    async def request(_container, action, payload=None):
        """Acquire a lease on a replacement worker to exercise the real identity rejection."""
        events.append(action)
        assert payload is not None
        return {"lease": payload["lease"], "instance": "new-worker"}

    monkeypatch.setattr(service.commands, "run", run)
    monkeypatch.setattr(service.commands, "request_runtime_gate", request)
    service._result = {"status": "running", "completed": []}
    asyncio.run(service._execute(target))
    assert events == ["hold", "release"]
    assert service.result()["status"] == "failed"
    assert service.result()["completed"] == []
    assert service.result()["recovery_required"] is False
    assert WipeService(tmp_path, lambda: False).result()["status"] == "failed"


def test_close_terminates_child_and_persists_interrupted_status(tmp_path, monkeypatch):
    """Shutdown joins the running reset and leaves terminal evidence outside the database."""
    service = WipeService(tmp_path, lambda: False)

    async def exercise():
        """Cancel a harmless disposable sleeping child through the production close path."""
        ready = tmp_path / "child.pid"

        async def execute():
            """Run a real process with no database or Docker operations."""
            try:
                await service.commands.run(
                    sys.executable,
                    "-c",
                    "import os, pathlib, sys, time; "
                    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)",
                    str(ready),
                )
            except asyncio.CancelledError:
                service._result.update(status="interrupted")
                service._persist()

        service._result = {"status": "running", "completed": []}
        service._task = asyncio.create_task(execute())
        for _ in range(100):
            if ready.exists():
                break
            await asyncio.sleep(0.01)
        assert ready.exists()
        pid = ready.read_text()
        await service.close()
        assert not Path(f"/proc/{pid}").exists()

    asyncio.run(exercise())
    assert WipeService(tmp_path, lambda: False).result()["status"] == "interrupted"


@pytest.mark.parametrize("same_daemon,present", [(True, True), (True, False), (False, True)])
def test_explicit_recovery_releases_only_the_recorded_daemon_and_lease(
    tmp_path, monkeypatch, same_daemon, present
):
    """An operator restart never resumes deletion and releases only its own authenticated hold."""
    service = WipeService(tmp_path, lambda: False)
    daemon = {"id": "local-daemon", "endpoint": "unix:///tmp/recorded.sock"}
    service._lease = ("app-id", "recorded-lease")
    service._lease_instance = "recorded-worker"
    service._lease_daemon = daemon
    service._result = {"status": "running", "stage": "hold_requests", "completed": []}
    service._persist()
    recovered = WipeService(tmp_path, lambda: False)
    assert recovered.result()["status"] == "interrupted"
    assert recovered.result()["recovery_required"] is True
    assert "recorded-lease" not in json.dumps(recovered.result())
    calls = []

    async def identity():
        """Return the same or a replaced daemon without consulting real Docker."""
        return daemon if same_daemon else {**daemon, "id": "different-daemon"}

    async def run(*args, **_kwargs):
        """Permit container inspection only; recovery must never stop or remove anything."""
        if args == ("docker", "ps", "-aq", "--no-trunc", "--filter", "id=app-id"):
            return "app-id" if present else ""
        assert args == ("docker", "inspect", "app-id")
        assert present
        return json.dumps([{"State": {"Running": True}}])

    async def request(container, action, payload=None):
        """Verify that the persisted exact lease is the only mutation sent during recovery."""
        calls.append(action)
        assert container == "app-id"
        if action == "activity":
            return {"instance": "recorded-worker", "held": True, "active_requests": 0}
        assert action == "release"
        assert payload == {"lease": "recorded-lease"}
        return {"released": True}

    monkeypatch.setattr(recovered.commands, "verify_docker_identity", identity)
    monkeypatch.setattr(recovered.commands, "run", run)
    monkeypatch.setattr(recovered.commands, "request_runtime_gate", request)
    if same_daemon:
        result = asyncio.run(recovered.recover())
        assert result["recovery_required"] is False
        assert calls == (["activity", "release"] if present else [])
        assert WipeService(tmp_path, lambda: False).result()["recovery_required"] is False
    else:
        with pytest.raises(WipeError, match="Docker target changed"):
            asyncio.run(recovered.recover())
        assert calls == []
        assert recovered.result()["recovery_required"] is True


def test_partial_volume_failure_never_deletes_files_or_automatically_restarts(
    tmp_path, monkeypatch
):
    """Report the exact destructive stage and leave subsequent steps untouched after failure."""
    service = WipeService(tmp_path, lambda: False)
    compose_json = '{"services": {}}'
    target = {
        "app_container": "app-id",
        "database_container": "db-id",
        "volume": "test-volume",
        "gate_instance": "worker-id",
        "daemon": {"id": "local"},
        "compose_sha256": hashlib.sha256(compose_json.encode()).hexdigest(),
        "files": [],
    }
    service._compose_json = compose_json
    service._result = {"status": "running", "completed": []}
    commands = []

    async def inspect():
        """Keep target identity unchanged while checking real failure-stage behavior."""
        return target

    async def run(*args, **_kwargs):
        """Fail volume deletion without launching any command or touching runtime data."""
        commands.append(args)
        if args == ("docker", "volume", "rm", "test-volume"):
            raise WipeError("Test volume removal failed")
        return ""

    async def request(_container, _action, payload):
        """Grant a matching lease without accessing an application."""
        return {"lease": payload["lease"], "instance": "worker-id"}

    monkeypatch.setattr(service, "inspect", inspect)
    monkeypatch.setattr(service.commands, "run", run)
    monkeypatch.setattr(service.commands, "request_runtime_gate", request)
    asyncio.run(service._execute(target))
    result = service.result()
    assert result["status"] == "failed"
    assert result["stage"] == "database_volume"
    assert result["completed"] == ["app_stopped"]
    assert result["recovery"]
    assert commands[-1] == ("docker", "volume", "rm", "test-volume")
    assert service._stopped_app is None


@pytest.mark.parametrize("blocker", [None, "permissions", "queued_jobs"])
def test_capability_checks_complete_preview_prerequisites_without_writes(
    tmp_path, monkeypatch, blocker
):
    """Availability includes real file checks and job activity without tokens, holds, or deletes."""
    service = WipeService(tmp_path, lambda: False)
    runtime = tmp_path / "data/local-settings/local-llm.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("preserve runtime")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if blocker == "permissions":
        monkeypatch.setattr("app.operator.reset.files.os.access", lambda *_args, **_kwargs: False)
    labels = {"com.docker.compose.project.working_dir": str(tmp_path)}
    database = {
        "Id": "db-id",
        "Config": {
            "Labels": labels,
            "Env": ["POSTGRES_USER=filing", "POSTGRES_DB=filing", "POSTGRES_PASSWORD=filing"],
        },
        "Mounts": [
            {"Destination": "/var/lib/postgresql/data", "Type": "volume", "Name": "test-pg"}
        ],
        "NetworkSettings": {"Ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5432"}]}},
    }
    app = {
        "Id": "app-id",
        "Config": {
            "Labels": labels,
            "Env": [
                "MODE=dev",
                "DOCREVIEW_ADMIN_MODE=live",
                "DATABASE_URL=postgresql://filing:filing@db:5432/filing",
                "CORPUS_DIR=/app/data/corpus",
            ],
            "Cmd": ["uvicorn", "app.api.app:app"],
        },
        "Mounts": [{"Destination": "/app/data", "Type": "bind", "Source": str(tmp_path / "data")}],
        "State": {"Running": True},
    }
    compose = {
        "services": {
            "db": {
                "ports": [{"host_ip": "127.0.0.1", "published": "5432", "target": 5432}],
                "volumes": [
                    {"target": "/var/lib/postgresql/data", "type": "volume", "source": "pg_data"}
                ],
            }
        },
        "volumes": {"pg_data": {"name": "test-pg"}},
    }
    queries = []

    async def run(*args, **_kwargs):
        """Allow only the external reads used by the complete production inspection."""
        if args[:3] == ("docker", "ps", "-aq"):
            return "db-id" if args[-1].endswith("=db") else "app-id"
        if args[:2] == ("docker", "inspect"):
            return json.dumps([database if args[-1] == "db-id" else app])
        if args == ("docker", "volume", "inspect", "test-pg"):
            return json.dumps(
                [
                    {
                        "Labels": {"com.docker.compose.project": tmp_path.name},
                        "Driver": "local",
                        "Options": {},
                    }
                ]
            )
        if args == service.commands.compose_command("config", "--format", "json"):
            return json.dumps(compose)
        if args == ("git", "ls-files", "-z"):
            return ""
        raise AssertionError(f"Unexpected operation: {args}")

    async def sql(_container, query):
        """Provide table metadata and active queue state without a database mutation."""
        queries.append(query)
        if query.startswith("SELECT tablename"):
            return "operator_jobs"
        if "WHERE status IN" in query:
            return "1" if blocker == "queued_jobs" else "0"
        assert query == 'SELECT count(*) FROM "operator_jobs"'
        return "1"

    async def identity():
        """Provide the isolated daemon identity without contacting user infrastructure."""
        return {"id": "test-daemon"}

    async def activity(container, action, payload=None):
        """Reject request holds or releases during the read-only availability check."""
        assert (container, action, payload) == ("app-id", "activity", None)
        return {"active_requests": 0, "held": False, "instance": "test-gate"}

    monkeypatch.setattr(service.commands, "run", run)
    monkeypatch.setattr(service.commands, "query_database", sql)
    monkeypatch.setattr(service.commands, "verify_docker_identity", identity)
    monkeypatch.setattr(service.commands, "request_runtime_gate", activity)
    capability = asyncio.run(service.capability())
    assert capability["available"] is (blocker is None)
    assert capability["checked_at"]
    assert any("WHERE status IN" in query for query in queries)
    if blocker:
        assert capability["diagnosis"]["code"] == (
            "runtime_file_permission" if blocker == "permissions" else "active_jobs"
        )
    else:
        assert capability["reason"] is None
    assert service._preview is None
    assert service._lease is None
    assert service._task is None
    assert service._operation_fd is None
    assert not service._audit.exists()
    assert runtime.read_text() == "preserve runtime"
