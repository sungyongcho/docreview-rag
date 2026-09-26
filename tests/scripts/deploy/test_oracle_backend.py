"""Verify Oracle artifact selection without connecting to a remote host."""

import json
import os
from pathlib import Path
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
    tools = tmp_path / "tools"
    tools.mkdir()
    for command in ("ssh", "scp", "rsync"):
        path = tools / command
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with open(os.environ['COMMAND_LOG'], 'a') as out:\n"
            "    out.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + '\\n')\n"
            "if 'mktemp -d' in sys.argv[-1]:\n"
            "    print('/tmp/docreview-deploy.TEST')\n"
        )
        path.chmod(0o755)
    log = tmp_path / "commands.jsonl"
    env = {
        **{key: value for key, value in os.environ.items() if key != "DEPLOY_ARTIFACT_DIR"},
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "COMMAND_LOG": str(log),
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
