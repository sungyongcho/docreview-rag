"""Keep local UI synchronization away from PROD, API restarts, and runtime packages."""

import json
import subprocess

import pytest

from scripts.stack import refresh_dev_ui


def fake_docker(monkeypatch, *, mode="dev", changed=False):
    """Record commands and return deterministic container identities without Docker."""
    calls = []
    inspections = 0

    def run(command, **kwargs):
        """Simulate only the inspect/create responses used by the UI refresh."""
        nonlocal inspections
        calls.append(command)
        if command[1] == "inspect":
            inspections += 1
            record = {
                "Id": "a" * 64,
                "State": {
                    "Running": True,
                    "StartedAt": "later" if changed and inspections > 1 else "same",
                },
                "Config": {"Env": [f"MODE={mode}", "DOCREVIEW_ADMIN_MODE=live"]},
            }
            return subprocess.CompletedProcess(command, 0, json.dumps([record]))
        return subprocess.CompletedProcess(command, 0, "b" * 64 if command[1] == "create" else "")

    monkeypatch.setattr(refresh_dev_ui.subprocess, "run", run)
    return calls


def test_refresh_builds_canonical_web_only_and_preserves_api(monkeypatch):
    """The only write to the live target is the static frontend copy."""
    calls = fake_docker(monkeypatch)
    refresh_dev_ui.refresh("dev-target")
    build = next(command for command in calls if command[1] == "build")
    assert build[build.index("--target") + 1] == "web"
    assert build[-1] == str(refresh_dev_ui.ROOT)
    assert "NEXT_PUBLIC_ADMIN_MODE=live" in build
    copies = [command for command in calls if command[1] == "cp"]
    assert copies[-1][-1] == "dev-target:/app/web/out/"
    assert all(
        command[1] not in {"stop", "restart", "exec", "kill", "compose"} for command in calls
    )
    assert [command[-1] for command in calls if command[1] == "rm"] == ["b" * 64]


def test_prod_is_rejected_before_build(monkeypatch):
    """A PROD target cannot receive an administrator frontend."""
    calls = fake_docker(monkeypatch, mode="prod")
    with pytest.raises(ValueError, match="DEV container"):
        refresh_dev_ui.refresh("prod-target")
    assert len(calls) == 1


def test_recreated_api_blocks_static_copy(monkeypatch):
    """Refuse an API identity change during the build."""
    calls = fake_docker(monkeypatch, changed=True)
    with pytest.raises(RuntimeError, match="changed during"):
        refresh_dev_ui.refresh("dev-target")
    assert not any(command[1] == "cp" for command in calls)


def test_dry_run_only_inspects(monkeypatch):
    """A dry run makes no image, container, or filesystem mutations."""
    calls = fake_docker(monkeypatch)
    refresh_dev_ui.refresh("dev-target", dry_run=True)
    assert len(calls) == 1 and calls[0][1] == "inspect"
