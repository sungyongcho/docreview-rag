"""Validate deployment arguments and preservation with fake cloud/container commands."""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "gcp_artifacts", ROOT / "deploy/gcp/verify_artifacts.py"
)
ARTIFACTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARTIFACTS)


@pytest.fixture
def bundle(tmp_path):
    """Create an isolated public bundle with the exact supported portfolio identities."""
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "eval_runs").mkdir()
    documents = [
        {"document_id": f"{issuer}-{year}", "issuer": issuer, "fiscal_year": year}
        for issuer, years in (
            ("NVDA", range(2019, 2025)),
            ("AMD", range(2019, 2025)),
            ("005930", range(2022, 2025)),
            ("000660", range(2022, 2025)),
        )
        for year in years
    ]
    sources = {f"sources/{row['document_id']}.txt": b"original" for row in documents}
    manifest = {
        "documents": documents,
        "artifacts": [
            {
                "document_id": row["document_id"],
                "role": "primary",
                "path": f"sources/{row['document_id']}.txt",
                "sha256": hashlib.sha256(b"original").hexdigest(),
                "byte_length": len(b"original"),
            }
            for row in documents
        ],
    }
    payload = json.dumps(manifest).encode()
    with tarfile.open(root / "originals.tar.gz", "w:gz") as archive:
        member = tarfile.TarInfo("corpus/manifest.json")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
        for name, source in sources.items():
            member = tarfile.TarInfo(f"corpus/{name}")
            member.size = len(source)
            archive.addfile(member, io.BytesIO(source))
    (root / "database.public.dump").write_bytes(b"public-dump-fixture")
    (root / "database.private.dump").write_bytes(b"never-transfer-this")
    for name in ARTIFACTS.EVALUATIONS:
        (root / "eval_runs" / name).write_text('{"cases": [1], "metrics": {"mrr": 1}}')
    refresh_checksums(root)
    return root


def refresh_checksums(root):
    """Write real checksums for the isolated artifact fixture."""
    (root / "checksums.json").write_text(
        json.dumps(
            {
                name: {
                    "bytes": (root / name).stat().st_size,
                    "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(),
                }
                for name in ARTIFACTS.PUBLIC_FILES
            }
        )
    )


def database_report(bundle):
    """Supply expected persisted identities independently from shell command responses."""
    manifest = ARTIFACTS.validate_artifacts(bundle)
    return {
        "documents": sorted(row["document_id"] for row in manifest["documents"]),
        "chunks": 10586,
        "embeddings": 10586,
        "matching_embeddings": 10586,
        "snapshots": 4,
        "public_ready_snapshots": 4,
        "complete_snapshot_documents": 4,
        "evaluation_paths": sorted(f"/app/data/eval_runs/{name}" for name in ARTIFACTS.EVALUATIONS),
        "linked_evaluations": 4,
        "runs": 0,
        "traces": 0,
        "operator_jobs": 0,
    }


def executable(path, source):
    """Install one fake external command in the test-owned PATH."""
    path.write_text(source)
    path.chmod(0o755)


def command_log(path):
    """Read captured command arguments, including an untouched empty log."""
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def launcher(tmp_path, bundle):
    """Prepare a dotenv fixture and a gcloud fake without cloud access."""
    checkout = tmp_path / "checkout with spaces"
    scripts = checkout / "deploy/gcp"
    scripts.mkdir(parents=True)
    for name in ("deploy_backend.sh", "deploy_env_config.sh", "verify_artifacts.py"):
        shutil.copy2(ROOT / "deploy/gcp" / name, scripts / name)
    dotenv = checkout / ".env"
    dotenv.write_text(
        "DEPLOY_GCP_PROJECT=fixture-project\n"
        "OPENAI_API_KEY_PROD=fixture-key\n"
        "DOCREVIEW_IMAGE=fixture/image:tag\n"
        "DEPLOY_POSTGRES_PASSWORD=fixture-password\n"
    )
    tools = tmp_path / "tools"
    tools.mkdir()
    executable(
        tools / "gcloud",
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['COMMAND_LOG'], 'a') as out:\n"
        "    out.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if '--command' in sys.argv and 'mktemp' in sys.argv[-1]:\n"
        "    print('/tmp/docreview-deploy.Fixture123')\n",
    )
    log = tmp_path / "commands.jsonl"
    env = {
        **os.environ,
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "COMMAND_LOG": str(log),
        "DOTENV_PATH": str(dotenv),
        "DEPLOY_ARTIFACT_DIR": str(bundle),
        "DEPLOY_VM_NAME": "fixture-vm",
        "DEPLOY_GCP_ZONE": "us-central1-a",
    }
    return scripts / "deploy_backend.sh", env, log


def test_dotenv_values_use_the_remote_install_filename(launcher):
    """Dotenv input is exported with the inherited key to the exact remote filename."""
    script, env, log = launcher
    result = subprocess.run(["bash", str(script), "first-install"], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    commands = command_log(log)
    config_copy = next(cmd for cmd in commands if any("Caddyfile" in arg for arg in cmd))
    env_copy = next(Path(arg) for arg in config_copy if arg.endswith("/backend.env"))
    content = env_copy.read_text()
    assert "OPENAI_API_KEY_PROD=fixture-key\n" in content
    assert "POSTGRES_PASSWORD=fixture-password\n" in content
    assert "DOCREVIEW_IMAGE=fixture/image:tag\n" in content
    assert env_copy.stat().st_mode & 0o777 == 0o600
    assert "database.private.dump" not in str(commands)
    copies = [cmd for cmd in commands if cmd[:2] == ["compute", "scp"]]
    assert all("--tunnel-through-iap" in cmd for cmd in copies)
    assert sum(any("database.public.dump" in arg for arg in cmd) for cmd in copies) == 1
    assert sum(any("eval_runs/" in arg for arg in cmd) for cmd in copies) == 4
    assert "'first-install'" in commands[-1][-1]


def test_first_install_requires_a_deploy_password(launcher):
    """A missing DEPLOY_POSTGRES_PASSWORD fails before any cloud command."""
    script, env, log = launcher
    env = {
        k: v for k, v in env.items() if k not in ("POSTGRES_PASSWORD", "DEPLOY_POSTGRES_PASSWORD")
    }
    dotenv = Path(env["DOTENV_PATH"])
    dotenv.write_text(
        "DEPLOY_GCP_PROJECT=fixture-project\n"
        "OPENAI_API_KEY_PROD=fixture-key\n"
        "DOCREVIEW_IMAGE=fixture/image:tag\n"
    )
    result = subprocess.run(["bash", str(script), "first-install"], env=env, capture_output=True)
    assert result.returncode != 0
    assert "DEPLOY_POSTGRES_PASSWORD" in result.stderr.decode()
    assert command_log(log) == []


def test_launcher_update_never_transfers_artifacts_or_credentials(launcher):
    """Application updates work without reading or transferring the restore bundle."""
    script, env, log = launcher
    result = subprocess.run(
        ["bash", str(script), "update"],
        env={**env, "DEPLOY_ARTIFACT_DIR": "/missing/bundle"},
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    commands = command_log(log)
    assert len(commands) == 3
    assert commands[1][2].endswith("/apply_backend.sh")
    assert "backend.env" not in str(commands)
    assert "'update'" in commands[-1][-1]


def test_launcher_requires_an_explicit_mode(launcher):
    """An accidental bare invocation never reaches gcloud."""
    script, env, log = launcher
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True)
    assert result.returncode == 2
    assert command_log(log) == []


def test_corrupted_bundle_blocks_cloud_staging(launcher, bundle):
    """A mismatch is caught before any credential or artifact transfer."""
    script, env, log = launcher
    (bundle / "database.public.dump").write_bytes(b"changed")
    result = subprocess.run(["bash", str(script), "first-install"], env=env, capture_output=True)
    assert result.returncode != 0
    assert command_log(log) == []


@pytest.fixture
def remote(tmp_path, bundle):
    """Run the remote installer in temporary roots with fake root and Docker commands."""
    stage = tmp_path / "stage"
    stage.mkdir()
    shutil.copytree(bundle, stage / "artifacts")
    for name in ("verify_artifacts.py", "verify_restore.sql", "docker-compose.deploy.yml"):
        shutil.copy2(ROOT / "deploy/gcp" / name, stage / name)
    (stage / "Caddyfile").write_text(':80 { respond "fixture" }')
    (stage / "backend.env").write_text("POSTGRES_PASSWORD=fixture-password\n")
    install_dir = tmp_path / "install"
    data_dir = tmp_path / "data"
    script = tmp_path / "apply_backend.sh"
    script.write_text(
        (ROOT / "deploy/gcp/apply_backend.sh")
        .read_text()
        .replace("install_dir=/opt/docreview", f"install_dir={shlex.quote(str(install_dir))}")
        .replace("data_dir=/var/lib/docreview", f"data_dir={shlex.quote(str(data_dir))}")
    )
    tools = tmp_path / "remote-tools"
    tools.mkdir()
    executable(tools / "id", "#!/bin/sh\nprintf '0\\n'\n")
    executable(tools / "chown", "#!/bin/sh\nexit 0\n")
    executable(
        tools / "docker",
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['COMMAND_LOG'], 'a') as out:\n"
        "    out.write(json.dumps(args) + '\\n')\n"
        "if os.environ.get('FAIL_COMMAND') in args:\n"
        "    sys.exit(19)\n"
        "if 'images' in args:\n"
        "    print('sha256:previous-image')\n"
        "if 'psql' in args:\n"
        "    print(os.environ['DATABASE_REPORT'])\n"
        "if 'up' in args and args[-1] == 'db':\n"
        "    (Path(os.environ['DATA_DIR']) / 'postgres/PG_VERSION').write_text('16')\n",
    )
    log = tmp_path / "remote.jsonl"
    env = {
        **os.environ,
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "COMMAND_LOG": str(log),
        "DATABASE_REPORT": json.dumps(database_report(bundle)),
        "DATA_DIR": str(data_dir),
    }
    return script, stage, install_dir, data_dir, env, log


def run_remote(remote, mode, **extra):
    """Execute one installer mode against the fake remote host."""
    script, stage, _, _, env, _ = remote
    return subprocess.run(
        ["bash", str(script), mode, str(stage), "fixture/image:new"],
        env={**env, **extra},
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "existing", ["postgres/PG_VERSION", "runtime/usage.sqlite3", ".restore-in-progress"]
)
def test_first_install_refuses_existing_data(remote, existing):
    """Existing usage, database state and interrupted restores are never overwritten."""
    _, _, _, data, _, log = remote
    target = data / existing
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"preserve-me")
    result = run_remote(remote, "first-install")
    assert result.returncode != 0
    assert target.read_bytes() == b"preserve-me"
    assert command_log(log) == []


def test_first_install_validates_before_starting_public_services(remote):
    """Restored identity and schema checks precede the first public app startup."""
    _, _, _, data, _, log = remote
    result = run_remote(remote, "first-install")
    assert result.returncode == 0, result.stderr
    calls = command_log(log)
    restore = next(i for i, cmd in enumerate(calls) if "pg_restore" in cmd)
    report = next(i for i, cmd in enumerate(calls) if "psql" in cmd)
    schema = next(i for i, cmd in enumerate(calls) if "run" in cmd)
    public_start = next(i for i, cmd in enumerate(calls) if cmd[-2:] == ["app", "caddy"])
    assert restore < report < schema < public_start
    assert (data / ".restore-complete").exists()
    assert not (data / ".restore-in-progress").exists()
    assert (data / "runtime").stat().st_mode & 0o777 == 0o700
    assert len(list((data / "eval-runs").glob("*.json"))) == 4


@pytest.mark.parametrize("failure", ["pg_restore", "psql", "run"])
def test_restore_failure_preserves_marker_and_blocks_retry(remote, failure):
    """A failed restore cannot silently resume or start the public app."""
    _, _, _, data, _, log = remote
    first = run_remote(remote, "first-install", FAIL_COMMAND=failure)
    assert first.returncode != 0
    assert (data / ".restore-in-progress").exists()
    before = command_log(log)
    assert not any(cmd[-2:] == ["app", "caddy"] for cmd in before)
    second = run_remote(remote, "first-install")
    assert second.returncode != 0
    assert "Interrupted restore" in second.stderr
    assert command_log(log) == before


def test_invalid_database_report_blocks_public_start(remote):
    """Successful pg_restore alone cannot pass incomplete snapshot acceptance."""
    _, _, _, data, env, log = remote
    report = json.loads(env["DATABASE_REPORT"])
    report["snapshots"] = 3
    result = run_remote(remote, "first-install", DATABASE_REPORT=json.dumps(report))
    assert result.returncode != 0
    assert (data / ".restore-in-progress").exists()
    assert not any(cmd[-2:] == ["app", "caddy"] for cmd in command_log(log))


def test_update_preserves_data_and_retains_rollback_image(remote):
    """App updates keep all persisted bytes and offer an explicit local-image rollback."""
    _, _, install_dir, data, _, log = remote
    install_dir.mkdir()
    (install_dir / ".env").write_text("POSTGRES_PASSWORD=existing-password\n")
    (install_dir / "image.env").write_text("DOCREVIEW_IMAGE=fixture/image:old\n")
    (install_dir / "docker-compose.yml").write_text("preserved-compose")
    for name in (
        ".restore-complete",
        "postgres/PG_VERSION",
        "corpus/source",
        "eval-runs/saved.json",
        "runtime/usage.sqlite3",
    ):
        target = data / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(name.encode())
    before = {str(path): path.read_bytes() for path in data.rglob("*") if path.is_file()}
    result = run_remote(remote, "update")
    assert result.returncode == 0, result.stderr
    calls = command_log(log)
    assert any(cmd[:2] == ["image", "tag"] for cmd in calls)
    assert any(cmd[-2:] == ["pull", "app"] for cmd in calls)
    assert any("--no-deps" in cmd and cmd[-1] == "app" for cmd in calls)
    assert not any("pg_restore" in cmd or "prune" in cmd or "db" in cmd for cmd in calls)
    assert before == {str(path): path.read_bytes() for path in data.rglob("*") if path.is_file()}
    assert (install_dir / "docker-compose.yml").read_text() == "preserved-compose"
    assert (install_dir / ".env").read_text() == "POSTGRES_PASSWORD=existing-password\n"
    rollback = (install_dir / "rollback-image").read_text().strip()
    assert rollback.startswith("docreview-rollback:")
    result = run_remote(remote, "rollback")
    assert result.returncode == 0, result.stderr
    assert (install_dir / "image.env").read_text() == f"DOCREVIEW_IMAGE={rollback}\n"
    assert before == {str(path): path.read_bytes() for path in data.rglob("*") if path.is_file()}


def test_failed_update_cannot_replace_the_known_rollback_image(remote):
    """A retry preserves the healthy rollback reference until explicit recovery succeeds."""
    _, _, install_dir, _, _, log = remote
    assert run_remote(remote, "first-install").returncode == 0
    assert run_remote(remote, "update", FAIL_COMMAND="up").returncode != 0
    rollback = (install_dir / "rollback-image").read_bytes()
    before = command_log(log)
    retry = run_remote(remote, "update")
    assert retry.returncode != 0
    assert "interrupted update" in retry.stderr
    assert (install_dir / "rollback-image").read_bytes() == rollback
    assert command_log(log) == before
    assert run_remote(remote, "rollback").returncode == 0
    assert not (install_dir / ".update-in-progress").exists()
    assert run_remote(remote, "update").returncode == 0


@pytest.mark.parametrize("name", ["../outside", "corpus/../../outside", "/absolute", "corpus/link"])
def test_archive_rejects_traversal_and_links(bundle, name):
    """A checksummed archive still cannot escape its corpus directory."""
    with tarfile.open(bundle / "originals.tar.gz", "w:gz") as archive:
        member = tarfile.TarInfo(name)
        if name == "corpus/link":
            member.type = tarfile.SYMTYPE
            member.linkname = "/outside"
        archive.addfile(member)
    refresh_checksums(bundle)
    with pytest.raises(ValueError, match="Unsafe"):
        ARTIFACTS.validate_artifacts(bundle)


def test_extraction_refuses_preexisting_sources(bundle, tmp_path):
    """An existing source file is preserved even with a valid restore bundle."""
    target = tmp_path / "restore"
    (target / "corpus").mkdir(parents=True)
    (target / "corpus/keep").write_text("existing")
    with pytest.raises(ValueError, match="not empty"):
        ARTIFACTS.extract_artifacts(bundle, target)
    assert (target / "corpus/keep").read_text() == "existing"


def test_production_compose_has_no_admin_bypass():
    """The production service keeps data persistent and publishes only Caddy."""
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(ROOT / "deploy/gcp/docker-compose.deploy.yml"),
            "config",
            "--format",
            "json",
        ],
        env={
            **os.environ,
            "DOCREVIEW_IMAGE": "fixture/image:tag",
            "POSTGRES_PASSWORD": "fixture-password",
            "POSTGRES_PASSWORD_FILE": "/tmp/fixture-postgres-password",
            "OPENAI_API_KEY_PROD": "fixture-key",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    config = json.loads(result.stdout)
    app = config["services"]["app"]
    assert app["user"] == "10001:10001"
    assert "ports" not in app
    assert app["environment"]["DOCREVIEW_ADMIN_MODE"] == "off"
    assert app["environment"]["DOCREVIEW_OPENAI_MODEL"] == "gpt-5.6-luna"
    assert app["environment"]["REVIEW_MODEL"] == "gpt-5.6-luna"
    assert app["environment"]["DOCREVIEW_RATE_LIMIT_PER_MINUTE"] == "10"
    assert app["environment"]["DOCREVIEW_RATE_LIMIT_PER_DAY"] == "50"
    assert app["environment"]["DOCREVIEW_PUBLIC_DAILY_COST_USD"] == "0.10"
    assert app["environment"]["DOCREVIEW_OPENAI_MAX_COST_USD"] == "0.005"
    assert any(
        mount["source"] == "/var/lib/docreview/runtime"
        and mount["target"] == "/app/data/runtime"
        and not mount.get("read_only", False)
        for mount in app["volumes"]
    )
