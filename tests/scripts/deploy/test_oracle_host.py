"""Verify the Oracle host preparation without connecting to a remote host."""

import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def test_prepare_host_runs_its_own_setup_for_the_origin_port(tmp_path):
    """Host preparation uses this repository's script and opens only DocReview's port."""
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "DEPLOY_ORACLE_HOST=192.0.2.1\n"
        "OPENAI_API_KEY_PROD=fixture-key\n"
        "DEPLOY_ORACLE_ORIGIN_PORT=8881\n"
    )
    log = tmp_path / "commands.jsonl"
    for command in ("ssh", "scp"):
        path = tmp_path / command
        path.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with open(os.environ['COMMAND_LOG'], 'a') as out:\n"
            "    out.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + '\\n')\n"
            "print('/tmp/docreview-host.TEST')\n"
        )
        path.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "DOTENV_PATH": str(dotenv),
        "COMMAND_LOG": str(log),
    }
    subprocess.run(["bash", ROOT / "deploy/oracle/prepare_host.sh"], check=True, env=env)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    copied = next(call for call in calls if call[0] == "scp")
    assert copied[-2] == str(ROOT / "deploy/oracle/host_setup.sh")
    assert "'ubuntu' '8881'; rm -rf" in calls[-1][-1]


def test_oracle_scripts_do_not_depend_on_another_repository():
    """Oracle deployment scripts stay within this repository."""
    scripts = (ROOT / "deploy/oracle").glob("*.sh")
    assert not [path.name for path in scripts if "gomoku" in path.read_text().lower()]
