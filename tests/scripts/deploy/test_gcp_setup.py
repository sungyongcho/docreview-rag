"""Validate the one-shot project setup and image push with fake cloud commands."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]


def executable(path, source):
    """Install one fake external command in the test-owned PATH."""
    path.write_text(source)
    path.chmod(0o755)


def command_log(path):
    """Read captured command arguments, including an untouched empty log."""
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def launcher(tmp_path):
    """Prepare a dotenv fixture plus gcloud/docker fakes without cloud access."""
    checkout = tmp_path / "checkout"
    scripts = checkout / "deploy/gcp"
    scripts.mkdir(parents=True)
    for name in (
        "setup.sh",
        "build_image.sh",
        "deploy_env_config.sh",
        "deploy_all.sh",
        "deploy_backend.sh",
    ):
        shutil.copy2(ROOT / "deploy/gcp" / name, scripts / name)
    shutil.copytree(ROOT / "deploy/gcp/lib", scripts / "lib")
    dotenv = checkout / ".env"
    dotenv.write_text(
        "DEPLOY_GCP_PROJECT=fixture-project\n"
        "OPENAI_API_KEY_PROD=fixture-key\n"
        "DEPLOY_POSTGRES_PASSWORD=fixture-password\n"
    )
    tools = tmp_path / "tools"
    tools.mkdir()
    executable(
        tools / "gcloud",
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['COMMAND_LOG'], 'a') as out:\n"
        "    out.write(json.dumps(args) + '\\n')\n"
        "if args[:2] == ['auth', 'list']:\n"
        "    print('fixture@example.com')\n"
        "if args[:2] == ['compute', 'ssh'] and 'mktemp -d' in args[-1]:\n"
        "    print('/tmp/docreview-deploy.TEST')\n"
        "existing = set(os.environ.get('GCLOUD_EXISTING', '').split(','))\n"
        "if 'describe' in args and not existing.intersection(args):\n"
        "    sys.exit(1)\n",
    )
    executable(
        tools / "docker",
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['COMMAND_LOG'], 'a') as out:\n"
        "    out.write(json.dumps(sys.argv[1:]) + '\\n')\n",
    )
    log = tmp_path / "commands.jsonl"
    env = {
        **os.environ,
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "COMMAND_LOG": str(log),
        "DOTENV_PATH": str(dotenv),
        "DEPLOY_GCP_ZONE": "us-central1-a",
        "DEPLOY_SUMMARY": "0",
    }
    return scripts, env, log


@pytest.mark.parametrize("mode", ["first-install", "update", "rollback"])
def test_backend_wrapper_requires_artifacts_only_for_first_install(launcher, mode):
    """The wrapper preserves backend validation and leaves updates independent of bundles."""
    scripts, env, log = launcher
    env = {
        **{key: value for key, value in env.items() if key != "DEPLOY_ARTIFACT_DIR"},
        "GCLOUD_EXISTING": "fixture-project,docreview-rag",
    }
    result = subprocess.run(
        ["bash", str(scripts / "deploy_all.sh"), "backend", "--mode", mode, "--yes"],
        env=env,
        capture_output=True,
        text=True,
    )
    commands = command_log(log)
    remote = [cmd for cmd in commands if cmd[:2] in (["compute", "ssh"], ["compute", "scp"])]
    if mode == "first-install":
        assert result.returncode != 0
        assert "DEPLOY_ARTIFACT_DIR is required for first-install" in result.stderr
        assert remote == []
    else:
        assert result.returncode == 0, result.stderr
        assert any(f"'{mode}'" in cmd[-1] and "apply_backend.sh" in cmd[-1] for cmd in remote)
        assert not any("database.public.dump" in " ".join(cmd) for cmd in remote)


def test_setup_provisions_registry_and_service_account(launcher):
    """Setup enables every required API and creates missing registry resources once."""
    scripts, env, log = launcher
    result = subprocess.run(["bash", str(scripts / "setup.sh")], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    commands = command_log(log)
    enable = next(cmd for cmd in commands if cmd[:2] == ["services", "enable"])
    for api in (
        "compute.googleapis.com",
        "artifactregistry.googleapis.com",
        "iam.googleapis.com",
        "iap.googleapis.com",
    ):
        assert api in enable
    create = next(cmd for cmd in commands if cmd[:3] == ["artifacts", "repositories", "create"])
    assert "docreview" in create and "us-central1" in create
    sa_create = next(cmd for cmd in commands if cmd[:3] == ["iam", "service-accounts", "create"])
    assert "docreview-deploy" in sa_create
    bindings = [cmd for cmd in commands if "--role" in cmd]
    roles = {cmd[cmd.index("--role") + 1] for cmd in bindings}
    assert "roles/artifactregistry.reader" in roles
    assert "roles/iam.serviceAccountUser" in roles
    member = next(
        cmd[cmd.index("--member") + 1]
        for cmd in bindings
        if cmd[cmd.index("--member") + 1].startswith("user:")
    )
    assert member == "user:fixture@example.com"


def test_setup_is_idempotent_for_existing_resources(launcher):
    """Existing repositories and accounts are described, not recreated."""
    scripts, env, log = launcher
    env = {
        **env,
        "GCLOUD_EXISTING": "docreview,docreview-deploy@fixture-project.iam.gserviceaccount.com",
    }
    result = subprocess.run(["bash", str(scripts / "setup.sh")], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    commands = command_log(log)
    assert not any(cmd[:3] == ["artifacts", "repositories", "create"] for cmd in commands)
    assert not any(cmd[:3] == ["iam", "service-accounts", "create"] for cmd in commands)


def test_build_image_pushes_the_configured_reference(launcher):
    """Docker auth and the buildx push target the configured Artifact Registry image."""
    scripts, env, log = launcher
    env = {
        **env,
        "DOCREVIEW_IMAGE": "us-central1-docker.pkg.dev/fixture-project/docreview/docreview:v1",
    }
    result = subprocess.run(["bash", str(scripts / "build_image.sh")], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    commands = command_log(log)
    auth = next(
        cmd
        for cmd in commands
        if cmd[:3] == ["auth", "configure-docker", "us-central1-docker.pkg.dev"]
    )
    assert auth
    build = next(cmd for cmd in commands if cmd[:2] == ["buildx", "build"])
    assert "us-central1-docker.pkg.dev/fixture-project/docreview/docreview:v1" in build
    assert "push=true" in str(build)
    assert "linux/amd64" in build


def test_env_config_defaults_the_registry_image(launcher):
    """An unset DOCREVIEW_IMAGE resolves to the repository's docreview:latest."""
    scripts, env, log = launcher
    probe = f'source "{scripts}/deploy_env_config.sh" >/dev/null && printf %s "$DOCREVIEW_IMAGE"'
    result = subprocess.run(
        ["bash", "-c", probe],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "us-central1-docker.pkg.dev/fixture-project/docreview/docreview:latest"
    assert command_log(log) == []
