"""Verify Oracle artifact selection without connecting to a remote host."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def launcher(tmp_path):
    """Run real deployment scripts with a test dotenv and recorded fake SSH commands."""
    checkout = tmp_path / "checkout"
    scripts = checkout / "deploy/oracle"
    scripts.mkdir(parents=True)
    for name in ("deploy_backend.sh", "deploy_env_config.sh"):
        shutil.copy2(ROOT / "deploy/oracle" / name, scripts / name)
    shutil.copytree(ROOT / "deploy/gcp/lib", checkout / "deploy/gcp/lib")
    dotenv = checkout / ".env"
    dotenv.write_text(
        "DEPLOY_ORACLE_HOST=192.0.2.1\n"
        "OPENAI_API_KEY_PROD=fixture-key\n"
        "DEPLOY_POSTGRES_PASSWORD=fixture-password\n"
        "DEPLOY_ORACLE_IMAGE=docreview-rag:fixture\n"
    )
    subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "add", "--", "deploy"], check=True)
    tools = tmp_path / "tools"
    tools.mkdir()
    for command in ("ssh", "scp", "rsync"):
        path = tools / command
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, subprocess, sys\n"
            "from pathlib import Path\n"
            "with open(os.environ['COMMAND_LOG'], 'a') as out:\n"
            "    out.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + '\\n')\n"
            "if Path(sys.argv[0]).name == 'rsync':\n"
            "    source_list = Path(sys.argv[sys.argv.index('--files-from') + 1])\n"
            "    Path(os.environ['SOURCE_LIST_LOG']).write_bytes(source_list.read_bytes())\n"
            "    if os.environ.get('FAIL_SYNC'): sys.exit(23)\n"
            "    if os.environ.get('LOCAL_SYNC'):\n"
            "        args = [os.environ['REAL_RSYNC'], *sys.argv[1:-1], os.environ['LOCAL_SYNC']]\n"
            "        sys.exit(subprocess.run(args).returncode)\n"
            "if '/build.XXXXXXXX' in sys.argv[-1]:\n"
            "    print('/home/ubuntu/build/docreview-rag/build.TEST')\n"
            "elif 'mktemp -d' in sys.argv[-1]:\n"
            "    print('/tmp/docreview-deploy.TEST')\n"
        )
        path.chmod(0o755)
    log = tmp_path / "commands.jsonl"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = {
        **{key: value for key, value in os.environ.items() if key != "DEPLOY_ARTIFACT_DIR"},
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "COMMAND_LOG": str(log),
        "SOURCE_LIST_LOG": str(tmp_path / "source-list"),
        "TMPDIR": str(scratch),
        "DOTENV_PATH": str(dotenv),
        "DEPLOY_SUMMARY": "0",
    }
    return scripts / "deploy_backend.sh", env, log


@pytest.mark.parametrize("mode", ["first-install", "update", "rollback"])
def test_artifacts_are_required_only_for_first_install(launcher, mode):
    """An omitted bundle blocks installation before writes but does not block image changes."""
    script, env, log = launcher
    result = subprocess.run(["bash", str(script), mode], env=env, capture_output=True, text=True)
    commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    if mode == "first-install":
        assert result.returncode != 0
        assert "DEPLOY_ARTIFACT_DIR is required for first-install" in result.stderr
        assert commands == []
    else:
        assert result.returncode == 0, result.stderr
        assert any(
            cmd[0] == "ssh" and "apply_backend.sh" in cmd[-1] and f"'{mode}'" in cmd[-1]
            for cmd in commands
        )
        assert not any("database.public.dump" in " ".join(cmd) for cmd in commands)
        assert any(cmd[0] == "rsync" for cmd in commands) == (mode == "update")


def test_update_stages_caddy_and_keeps_the_build_context_isolated(launcher):
    """Update sends the proxy config and syncs into a fresh context without deleting old work."""
    script, env, log = launcher
    result = subprocess.run(
        ["bash", str(script), "update"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(
        cmd[0] == "scp" and any(value.endswith("/deploy/Caddyfile") for value in cmd)
        for cmd in commands
    )
    sync = next(cmd for cmd in commands if cmd[0] == "rsync")
    assert "--delete" not in sync
    assert "--from0" in sync
    assert "--files-from" in sync
    assert "deploy/cloudflare/" in sync
    assert sync[-1] == "ubuntu@192.0.2.1:/home/ubuntu/build/docreview-rag/build.TEST/"
    build = next(cmd[-1] for cmd in commands if "docker build" in cmd[-1])
    assert "cd /home/ubuntu/build/docreview-rag/build.TEST &&" in build
    apply = next(cmd[-1] for cmd in commands if "sudo bash" in cmd[-1])
    assert "; then sudo rm -rf" in apply
    assert "else status=$?; echo 'Deployment failed; staging preserved" in apply
    assert "Build context retained" in result.stdout


def test_build_sync_uses_only_tracked_files_without_reading_private_untracked_data(launcher):
    """A real local rsync preserves tracked public assets and excludes unreadable private files."""
    script, env, log = launcher
    checkout = script.parents[2]
    golden = checkout / "data/golden"
    golden.mkdir(parents=True)
    public = golden / "public examples.json"
    public.write_text('{"public": true}\n')
    asset = checkout / "web/public/public\nasset.txt"
    asset.parent.mkdir(parents=True)
    asset.write_text("public asset\n")
    ignored = [golden / ".datasets.lock", golden / "testing.json"]
    (checkout / ".gitignore").write_text("data/golden/.datasets.lock\ndata/golden/testing.json\n")
    for path in ignored:
        path.write_text("private test fixture\n")
        path.chmod(0)
    (checkout / "untracked-notes.txt").write_text("local-only test fixture\n")
    subprocess.run(
        ["git", "-C", str(checkout), "add", "--", ".gitignore", str(public), str(asset)],
        check=True,
    )
    destination = checkout.parent / "synced"
    destination.mkdir()
    rsync = shutil.which("rsync")
    assert rsync is not None, "The real rsync executable is required for source-selection coverage."
    result = subprocess.run(
        ["bash", str(script), "update"],
        env={**env, "LOCAL_SYNC": str(destination) + "/", "REAL_RSYNC": rsync},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (destination / public.relative_to(checkout)).read_text() == public.read_text()
    assert (destination / asset.relative_to(checkout)).read_text() == asset.read_text()
    assert not any((destination / path.relative_to(checkout)).exists() for path in ignored)
    assert not (destination / "untracked-notes.txt").exists()
    assert not (destination / ".env").exists()
    listed = Path(env["SOURCE_LIST_LOG"]).read_bytes().split(b"\0")
    assert b"data/golden/public examples.json" in listed
    assert b"web/public/public\nasset.txt" in listed
    assert all(str(path.relative_to(checkout)).encode() not in listed for path in ignored)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    sync = next(command for command in calls if command[0] == "rsync")
    assert not Path(sync[sync.index("--files-from") + 1]).exists()


def test_git_listing_failure_stops_before_remote_actions_and_removes_the_private_list(launcher):
    """An unavailable Git index cannot trigger remote staging or a partial source sync."""
    script, env, log = launcher
    git = Path(env["PATH"].split(os.pathsep)[0]) / "git"
    git.write_text("#!/bin/sh\nexit 42\n")
    git.chmod(0o755)
    result = subprocess.run(
        ["bash", str(script), "update"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 42
    assert not log.exists()
    assert list(Path(env["TMPDIR"]).iterdir()) == []


def test_sync_failure_preserves_its_exit_status_and_removes_the_private_list(launcher):
    """A failed copy neither starts a build nor leaves the private Git file list behind."""
    script, env, log = launcher
    result = subprocess.run(
        ["bash", str(script), "update"],
        env={**env, "FAIL_SYNC": "1"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 23
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    assert not any("docker build" in cmd[-1] or "apply_backend.sh" in cmd[-1] for cmd in commands)
    assert list(Path(env["TMPDIR"]).iterdir()) == []


def test_selected_ssh_config_keeps_strict_host_verification_for_every_transport(launcher, tmp_path):
    """One selected client config and quoted key path reach SSH, SCP and rsync consistently."""
    script, env, log = launcher
    config = tmp_path / "ssh client config"
    key = tmp_path / "private key"
    env = {**env, "DEPLOY_ORACLE_SSH_CONFIG": str(config), "DEPLOY_ORACLE_SSH_KEY": str(key)}
    result = subprocess.run(
        ["bash", str(script), "update"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    for command in (json.loads(line) for line in log.read_text().splitlines()):
        args = shlex.split(command[command.index("-e") + 1]) if command[0] == "rsync" else command
        assert args[args.index("-F") + 1] == str(config)
        assert args[args.index("-i") + 1] == str(key)
        assert "StrictHostKeyChecking=yes" in args


@pytest.fixture
def installed_backend(tmp_path):
    """Execute the remote apply script against private files and a recorded container boundary."""
    install_dir = tmp_path / "install"
    data_dir = tmp_path / "data"
    stage = tmp_path / "stage"
    tools = tmp_path / "tools"
    for directory in (install_dir / "deploy", data_dir, stage, tools):
        directory.mkdir(parents=True)
    (install_dir / "image.env").write_text("DOCREVIEW_IMAGE=docreview-rag:old\n")
    (install_dir / ".env").write_text("FIXTURE=true\n")
    (install_dir / "docker-compose.yml").write_text("services: {}\n")
    (install_dir / "deploy/Caddyfile").write_text(':80 { respond "old" }\n')
    (stage / "Caddyfile").write_text(':80 { respond "new" }\n')
    persistent = {
        ".restore-complete": b"completed",
        "postgres/PG_VERSION": b"16",
        "corpus/source.txt": b"preserved source",
        "eval-runs/result.json": b"{}",
        "runtime/public-ai-limits.sqlite3": b"preserved usage ledger",
    }
    for name, content in persistent.items():
        path = data_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    script = tmp_path / "apply_backend.sh"
    script.write_text(
        (ROOT / "deploy/oracle/apply_backend.sh")
        .read_text()
        .replace("install_dir=/opt/docreview", f"install_dir={shlex.quote(str(install_dir))}")
        .replace("data_dir=/var/lib/docreview", f"data_dir={shlex.quote(str(data_dir))}")
    )
    (tools / "id").write_text("#!/bin/sh\nprintf '0\\n'\n")
    (tools / "id").chmod(0o755)
    (tools / "docker").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "validate = 'validate' in args\n"
        "row = {'args': args, 'image': os.environ.get('DOCREVIEW_IMAGE')}\n"
        "row['caddy'] = (Path(os.environ['INSTALL_DIR']) / 'deploy/Caddyfile').read_text()\n"
        "if validate: row['stdin'] = sys.stdin.read()\n"
        "with open(os.environ['COMMAND_LOG'], 'a') as out:\n"
        "    out.write(json.dumps(row) + '\\n')\n"
        "if validate and os.environ.get('FAIL_VALIDATION'): sys.exit(1)\n"
        "if 'up' in args and os.environ.get('FAIL_APP'): sys.exit(1)\n"
        "if 'reload' in args and os.environ.get('FAIL_RELOAD'): sys.exit(1)\n"
        "if args[-3:] == ['images', '-q', 'app']: print('sha256:previous-app')\n"
    )
    (tools / "docker").chmod(0o755)
    log = tmp_path / "apply-commands.jsonl"
    env = {
        **os.environ,
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "COMMAND_LOG": str(log),
        "INSTALL_DIR": str(install_dir),
    }
    return script, install_dir, data_dir, stage, env, log, persistent


def apply(installed_backend, mode, **failures):
    """Invoke one update or rollback with optional failures at the actual command boundaries."""
    script, _, _, stage, env, _, _ = installed_backend
    return subprocess.run(
        ["bash", str(script), mode, str(stage), "docreview-rag:new"],
        env={**env, **failures},
        capture_output=True,
        text=True,
    )


def assert_persistent_data_preserved(installed_backend):
    """Verify every original persistent file and directory membership after an operation."""
    _, _, data_dir, _, _, _, persistent = installed_backend
    assert {
        str(path.relative_to(data_dir)): path.read_bytes()
        for path in data_dir.rglob("*")
        if path.is_file()
    } == persistent


def test_update_and_rollback_restore_app_and_proxy_without_replacing_mounted_inode(
    installed_backend,
):
    """A verified update and later rollback reload matching proxy bytes and preserve all data."""
    _, install_dir, _, stage, _, log, _ = installed_backend
    caddy = install_dir / "deploy/Caddyfile"
    inode = caddy.stat().st_ino
    original = caddy.read_text()
    result = apply(installed_backend, "update")
    assert result.returncode == 0, result.stderr
    assert caddy.read_text() == (stage / "Caddyfile").read_text()
    assert caddy.stat().st_ino == inode
    assert (install_dir / "rollback-Caddyfile").read_text() == original
    assert (install_dir / "image.env").read_text() == "DOCREVIEW_IMAGE=docreview-rag:new\n"
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    validation = next(i for i, row in enumerate(calls) if "validate" in row["args"])
    app_swap = next(i for i, row in enumerate(calls) if "up" in row["args"])
    reload = next(i for i, row in enumerate(calls) if "reload" in row["args"])
    assert validation < app_swap < reload
    assert calls[validation]["stdin"] == (stage / "Caddyfile").read_text()
    assert calls[reload]["caddy"] == (stage / "Caddyfile").read_text()
    assert calls[app_swap]["args"][-7:] == [
        "up",
        "-d",
        "--no-deps",
        "--wait",
        "--wait-timeout",
        "180",
        "app",
    ]
    rollback_image = (install_dir / "rollback-image").read_text().strip()
    result = apply(installed_backend, "rollback")
    assert result.returncode == 0, result.stderr
    assert caddy.read_text() == original
    assert caddy.stat().st_ino == inode
    assert (install_dir / "image.env").read_text() == f"DOCREVIEW_IMAGE={rollback_image}\n"
    assert not (install_dir / ".update-in-progress").exists()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [row for row in calls if "reload" in row["args"]][-1]["caddy"] == original
    assert_persistent_data_preserved(installed_backend)


def test_invalid_staged_caddy_fails_before_app_or_backup_changes(installed_backend):
    """A rejected config cannot swap the running app, installed config, or rollback evidence."""
    _, install_dir, _, _, _, log, _ = installed_backend
    original = (install_dir / "deploy/Caddyfile").read_text()
    result = apply(installed_backend, "update", FAIL_VALIDATION="1")
    assert result.returncode != 0
    assert (install_dir / "deploy/Caddyfile").read_text() == original
    assert (install_dir / "image.env").read_text() == "DOCREVIEW_IMAGE=docreview-rag:old\n"
    assert not (install_dir / ".update-in-progress").exists()
    assert not (install_dir / "rollback-image").exists()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert any("validate" in row["args"] for row in calls)
    assert not any("up" in row["args"] or "tag" in row["args"] for row in calls)
    assert_persistent_data_preserved(installed_backend)


@pytest.mark.parametrize("failure", ["FAIL_APP", "FAIL_RELOAD"])
def test_failed_update_remains_recoverable_and_blocks_another_update(installed_backend, failure):
    """App or reload failure preserves the complete prior pair until an explicit rollback."""
    _, install_dir, _, _, _, _, _ = installed_backend
    original = (install_dir / "deploy/Caddyfile").read_text()
    assert apply(installed_backend, "update", **{failure: "1"}).returncode != 0
    assert (install_dir / ".update-in-progress").is_file()
    assert (install_dir / "rollback-Caddyfile").read_text() == original
    assert (install_dir / "rollback-image").is_file()
    assert apply(installed_backend, "update").returncode != 0
    result = apply(installed_backend, "rollback")
    assert result.returncode == 0, result.stderr
    assert (install_dir / "deploy/Caddyfile").read_text() == original
    assert not (install_dir / ".update-in-progress").exists()
    assert_persistent_data_preserved(installed_backend)


def test_failed_rollback_keeps_its_checkpoint_for_retry(installed_backend):
    """A rollback from a completed update also remains marked until its reload succeeds."""
    _, install_dir, _, _, _, _, _ = installed_backend
    assert apply(installed_backend, "update").returncode == 0
    rollback_image = (install_dir / "rollback-image").read_text()
    rollback_caddy = (install_dir / "rollback-Caddyfile").read_text()
    assert apply(installed_backend, "rollback", FAIL_RELOAD="1").returncode != 0
    assert (install_dir / ".update-in-progress").is_file()
    assert (install_dir / "rollback-image").read_text() == rollback_image
    assert (install_dir / "rollback-Caddyfile").read_text() == rollback_caddy
    assert apply(installed_backend, "rollback").returncode == 0
    assert not (install_dir / ".update-in-progress").exists()
    assert_persistent_data_preserved(installed_backend)
