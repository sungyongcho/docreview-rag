"""Firebase packaging stages only the built app before an explicitly requested deployment."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("build_succeeds", [True, False])
def test_firebase_build_stage_deploy_order_from_another_directory(tmp_path, build_succeeds):
    """Mock external commands while exercising real source copying and failure propagation."""
    checkout = tmp_path / "checkout with spaces"
    script = checkout / "scripts/deploy/firebase.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/deploy/firebase.sh", script)
    (checkout / "web").mkdir()
    public = checkout / "deploy/firebase/public"
    staged = public / "docreview-rag-agent"
    staged.mkdir(parents=True)
    (staged / "old.html").write_text("old application")
    sentinel = public / "unrelated.txt"
    sentinel.write_text("keep")
    tools = tmp_path / "tools"
    tools.mkdir()
    npm = tools / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        'printf "npm:%s:%s\\n" "$*" "$PWD" >> "$COMMAND_LOG"\n'
        'if [ "$*" = "run build" ]; then\n'
        '  [ "$BUILD_SUCCEEDS" = true ] || exit 19\n'
        '  [ "$NEXT_PUBLIC_ADMIN_MODE" = canned ] || exit 20\n'
        '  [ "$NEXT_PUBLIC_API_BASE_URL" = '
        "https://sungyongcho.com/docreview-rag-agent/api ] || exit 21\n"
        "  mkdir -p out; printf new-application > out/index.html\n"
        "fi\n"
    )
    npm.chmod(0o755)
    npx = tools / "npx"
    npx.write_text(
        "#!/bin/sh\n"
        'printf "npx:%s:%s\\n" "$*" "$PWD" >> "$COMMAND_LOG"\n'
        '[ "$(cat public/docreview-rag-agent/index.html)" = new-application ] || exit 22\n'
        "[ ! -e public/docreview-rag-agent/old.html ] || exit 23\n"
    )
    npx.chmod(0o755)
    log = tmp_path / "commands.log"
    result = subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
            "COMMAND_LOG": str(log),
            "BUILD_SUCCEEDS": str(build_succeeds).lower(),
            "FIREBASE_PROJECT_ID": "fixture-project",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    commands = log.read_text().splitlines()
    assert commands[:2] == [f"npm:ci:{checkout}/web", f"npm:run build:{checkout}/web"]
    assert sentinel.read_text() == "keep"
    if build_succeeds:
        assert result.returncode == 0, result.stderr
        assert commands[2:] == [
            "npx:firebase-tools deploy --only hosting --project "
            f"fixture-project:{checkout}/deploy/firebase"
        ]
        assert (staged / "index.html").read_text() == "new-application"
        assert not (staged / "old.html").exists()
    else:
        assert result.returncode == 19
        assert len(commands) == 2
        assert (staged / "old.html").read_text() == "old application"
        assert not (staged / "index.html").exists()
