"""Exercise host cleanup guards in disposable Git checkouts, never user Docker resources."""

import json
import os
import subprocess
from unittest.mock import Mock

import pytest

from scripts.stack import fresh


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """Create a throwaway checkout with tracked files and isolated Docker/operator boundaries."""
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for name, content in {
        "data/corpus/manifest.json": "{}",
        ".gitignore": "data/browser-reset.json\ndata/browser-reset.tmp\n",
        "source.py": "original",
        ".env.example": "template",
    }.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "Fixture baseline",
        ],
        check=True,
    )
    monkeypatch.setattr(fresh.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "Y")
    resources = {"docker": ["fixture-docker"], "containers": [], "volumes": [], "images": []}
    monkeypatch.setattr(fresh, "docker_inventory", lambda *args, **kwargs: resources)
    monkeypatch.setattr(fresh, "LocalOperator", lambda root: Mock())
    return root


def populate(root):
    """Represent downloaded/cache files and every default preserved local directory."""
    for name in (
        "data/corpus/sec/a.txt",
        "data/exports/embeddings.json",
        ".venv/bin/python",
        "web/node_modules/a/index.js",
        "web/.next/cache/file",
        ".pytest_cache/file",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("remove")
    for name in (
        ".env",
        ".env.local",
        ".claude/config",
        ".agents/config",
        ".codex/config",
        ".vscode/config",
        ".idea/config",
        "private/note",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep")
    (root / ".freshstart-keep").write_text("private\n")
    (root / "data/corpus/manifest.json").write_text('{"modified": true}')


def test_clean_restores_data_and_preserves_configuration_with_own_receipt(checkout, capsys):
    """Actual file cleanup restores tracked manifest edits and leaves preserved files intact."""
    populate(checkout)
    assert fresh.start_fresh(checkout, no_start=True) == 0
    assert (checkout / "data/corpus/manifest.json").read_text() == "{}"
    for name in (
        ".env",
        ".env.local",
        ".claude/config",
        ".agents/config",
        ".codex/config",
        ".vscode/config",
        ".idea/config",
        "private/note",
        ".git",
    ):
        assert (checkout / name).exists()
    for name in (".venv", "web/node_modules", "web/.next", ".pytest_cache", "data/corpus/sec"):
        assert not (checkout / name).exists()
    assert fresh.status(checkout, "start-fresh") == 0
    output = capsys.readouterr().out
    assert "files," in output and "bytes" in output and "1." in output
    assert "Revert tracked: data/corpus/manifest.json" in output
    assert "browser data will reset to defaults" in output
    assert json.loads((checkout / "data/browser-reset.json").read_text())["reset_id"]


@pytest.mark.parametrize(
    "answers", [[""], ["y"], ["yes"], ["Y "], ["confirm"], ["Y", "y"], ["Y", ""]]
)
def test_cancel_every_nonuppercase_gate_without_file_or_docker_writes(
    checkout, monkeypatch, answers, capsys
):
    """Both extreme confirmations accept only the exact single uppercase character Y."""
    populate(checkout)
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    run = Mock(side_effect=AssertionError("No mutation may run before both confirmations"))
    monkeypatch.setattr(fresh, "run_step", run)
    assert fresh.start_fresh(checkout, extreme=True, no_start=True) == 0
    assert (checkout / ".env").exists() and (checkout / ".venv/bin/python").exists()
    assert not fresh.receipt_path(checkout, "start-fresh").exists()
    assert "nothing changed" in capsys.readouterr().out


def test_extreme_removes_environment_but_retains_template_and_never_starts(
    checkout, monkeypatch, capsys
):
    """Extreme cleanup removes private environment files after two prompts and stops."""
    populate(checkout)
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "Y")
    assert fresh.start_fresh(checkout, extreme=True) == 0
    assert len(prompts) == 2 and all("(Y/n)" in prompt for prompt in prompts)
    assert ".env*" in prompts[1]
    assert not (checkout / ".env").exists() and not (checkout / ".env.local").exists()
    assert (checkout / ".env.example").read_text() == "template"
    assert "Run rag-start-quick" in capsys.readouterr().out


def test_noninteractive_does_not_even_inventory(checkout, monkeypatch):
    """Piped input cannot trigger a preview or deletion."""
    monkeypatch.setattr(fresh.sys.stdin, "isatty", lambda: False)
    inventory = Mock()
    monkeypatch.setattr(fresh, "inventory", inventory)
    with pytest.raises(ValueError, match="interactively"):
        fresh.start_fresh(checkout)
    inventory.assert_not_called()


def test_tracked_code_requires_explicit_discard_and_preview(checkout, capsys):
    """Foreign tracked source edits block the default cleanup and are listed when authorized."""
    (checkout / "source.py").write_text("edited")
    with pytest.raises(ValueError, match="outside data/"):
        fresh.start_fresh(checkout, no_start=True)
    assert (checkout / "source.py").read_text() == "edited"
    assert fresh.start_fresh(checkout, no_start=True, discard_tracked=True) == 0
    assert (checkout / "source.py").read_text() == "original"
    assert "Revert tracked: source.py" in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["symlink", "nested", "traversal"])
def test_unsafe_paths_abort_without_following_them(checkout, tmp_path, kind):
    """Reject linked sources, nested repositories and escaping preservation paths."""
    if kind == "symlink":
        (checkout / "data/link").symlink_to(tmp_path, target_is_directory=True)
    elif kind == "nested":
        (checkout / "data/nested/.git").mkdir(parents=True)
    else:
        (checkout / ".freshstart-keep").write_text("../outside\n")
    with pytest.raises(ValueError):
        fresh.start_fresh(checkout, no_start=True)
    assert (checkout / "source.py").read_text() == "original"


def test_preview_expiry_and_file_drift_require_new_confirmation(checkout, monkeypatch):
    """Expired previews and changed removal targets never execute a cached deletion plan."""
    populate(checkout)
    times = iter([0, 301])
    monkeypatch.setattr(fresh.time, "monotonic", lambda: next(times))
    with pytest.raises(ValueError, match="expired"):
        fresh.start_fresh(checkout, no_start=True)
    monkeypatch.setattr(fresh.time, "monotonic", lambda: 0)

    def change(prompt):
        """Introduce a file after the preview to simulate concurrent work."""
        (checkout / "new-work").write_text("preserve")
        return "Y"

    monkeypatch.setattr("builtins.input", change)
    with pytest.raises(ValueError, match="Preview changed"):
        fresh.start_fresh(checkout, no_start=True)
    assert (checkout / "new-work").read_text() == "preserve"


def test_permissions_are_reported_only_after_failure_and_retried_once(
    checkout, monkeypatch, capsys
):
    """A real failed unlink leads to one exact scoped chown hint and only one retry."""
    populate(checkout)
    original = os.unlink
    denied = checkout / "data/corpus/sec/a.txt"
    calls = []

    def unlink(path, *args, **kwargs):
        """Simulate a legacy container-owned file at the removal boundary."""
        if path == denied.name:
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError(13, "fixture denied", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink)
    assert fresh.start_fresh(checkout, no_start=True) == 0
    assert len(calls) == 2
    output = capsys.readouterr().out
    assert output.count('sudo chown -R "$(id -u):$(id -g)" --') == 1
    assert str(denied.parent) in output


def test_remote_daemon_rejected_before_contact(tmp_path, monkeypatch):
    """A remote Docker context cannot become a cleanup target."""
    monkeypatch.setenv("DOCKER_HOST", "tcp://other-host:2375")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    contact = Mock()
    monkeypatch.setattr(fresh.subprocess, "check_output", contact)
    with pytest.raises(ValueError, match="local Docker"):
        fresh.docker_inventory(tmp_path, extreme=False)
    contact.assert_not_called()


def test_tracked_content_drift_aborts_after_confirmation(checkout, monkeypatch):
    """Editing an already-modified manifest cannot evade the preview fingerprint."""
    populate(checkout)

    def edit(prompt):
        """Simulate a concurrent app write that preserves the changed path list."""
        (checkout / "data/corpus/manifest.json").write_text("new concurrent content")
        return "Y"

    monkeypatch.setattr("builtins.input", edit)
    with pytest.raises(ValueError, match="Preview changed"):
        fresh.start_fresh(checkout, no_start=True)
    assert (checkout / "data/corpus/manifest.json").read_text() == "new concurrent content"


@pytest.mark.parametrize("extreme", [False, True])
@pytest.mark.parametrize("foreign", ["none", "container", "volume-user", "image-user"])
def test_docker_inventory_pins_checkout_and_preserves_shared_resources(
    tmp_path, monkeypatch, extreme, foreign
):
    """Only matching checkout resources enter the deletion preview; shared resources block it."""
    import json
    import socket

    root = tmp_path / "fixture-project"
    root.mkdir()
    endpoint = tmp_path / "docker.sock"
    sock = socket.socket(socket.AF_UNIX)
    sock.bind(str(endpoint))
    monkeypatch.setenv("DOCKER_HOST", "unix://" + str(endpoint))
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    project = root.name
    container = "c" * 64
    image = "sha256:" + "a" * 64

    def output(command, **kwargs):
        """Represent Docker's JSON/read-only inventory, with no real daemon access."""
        args = command[3:]
        if args[:2] == ["ps", "-aq"]:
            if args[-1].startswith("volume=") and foreign == "volume-user":
                return "foreign-container"
            if args[-1].startswith("ancestor=") and foreign == "image-user":
                return "foreign-container"
            return container
        if args[0] == "inspect":
            return json.dumps(
                [
                    {
                        "Id": container,
                        "Config": {
                            "Labels": {
                                "com.docker.compose.project": project,
                                "com.docker.compose.project.working_dir": str(
                                    tmp_path if foreign == "container" else root
                                ),
                            }
                        },
                    }
                ]
            )
        if args[:2] == ["volume", "ls"]:
            return f"{project}_pg_data\n{project}_ollama_models"
        if args[:2] == ["volume", "inspect"]:
            return json.dumps(
                [
                    {
                        "Name": args[2],
                        "Driver": "local",
                        "Options": {},
                        "Labels": {
                            "com.docker.compose.project": project,
                            "com.docker.compose.volume": "ollama_models"
                            if args[2].endswith("ollama_models")
                            else "pg_data",
                        },
                    }
                ]
            )
        if args[:2] == ["image", "ls"]:
            return image
        if args[:2] == ["image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": image,
                        "RepoTags": [f"{project}-app:latest"],
                        "Config": {
                            "Labels": {
                                "com.docker.compose.project": project,
                                "com.docker.compose.service": "app",
                            }
                        },
                    }
                ]
            )
        raise AssertionError(command)

    monkeypatch.setattr(fresh.subprocess, "check_output", output)
    try:
        if foreign != "none":
            with pytest.raises(ValueError, match="another checkout|shared outside"):
                fresh.docker_inventory(root, extreme=extreme)
        else:
            resources = fresh.docker_inventory(root, extreme=extreme)
            assert resources["containers"] == [container]
            assert resources["images"] == [image]
            assert (f"{project}_ollama_models" in resources["volumes"]) == extreme
            assert f"{project}_pg_data" in resources["volumes"]
    finally:
        sock.close()


def test_permission_free_cleanup_does_not_print_a_repair(checkout, capsys):
    """Healthy checkout cleanup never lectures about permissions or suggests sudo."""
    populate(checkout)
    fresh.start_fresh(checkout, no_start=True)
    assert "sudo" not in capsys.readouterr().out


@pytest.mark.parametrize("relative", ["source.py", "data/corpus/manifest.json"])
def test_index_changes_cannot_cancel_worktree_guard(checkout, relative):
    """Opposite index/worktree edits are still changes and data reset clears both."""
    target = checkout / relative
    original = target.read_text()
    target.write_text("staged edit")
    subprocess.run(["git", "-C", str(checkout), "add", "--", relative], check=True)
    target.write_text(original)
    assert fresh.git(checkout, "diff", "HEAD", "--name-only") == ""
    if relative == "source.py":
        with pytest.raises(ValueError, match="outside data/"):
            fresh.start_fresh(checkout, no_start=True)
        assert fresh.git(checkout, "diff", "--cached", "--name-only").strip() == relative
    else:
        assert fresh.start_fresh(checkout, no_start=True) == 0
        assert fresh.git(checkout, "status", "--porcelain") == ""


def test_parent_symlink_swap_cannot_unlink_outside_checkout(checkout, tmp_path):
    """A directory swap after preview cannot redirect descriptor-relative unlink."""
    populate(checkout)
    snapshot = fresh.inventory(checkout, extreme=False, discard_tracked=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_text("foreign work")
    source = checkout / "data/corpus/sec"
    source.rename(checkout / "data/corpus/original-sec")
    source.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        fresh.remove_files(checkout, snapshot)
    assert (outside / "a.txt").read_text() == "foreign work"
    assert (checkout / "data/corpus/original-sec/a.txt").read_text() == "remove"


def test_post_preview_inode_change_records_failure_without_restart(checkout, monkeypatch):
    """A file replaced during operator stop leaves a failed receipt after partial cleanup."""
    populate(checkout)
    target = checkout / "data/corpus/sec/a.txt"
    initial_inode = target.stat().st_ino

    def replace_target():
        """Replace a previewed inode after the final inventory comparison has completed."""
        replacement = target.with_suffix(".replacement")
        replacement.write_text("concurrent source")
        replacement.replace(target)

    operator = Mock()
    operator.stop.side_effect = replace_target
    monkeypatch.setattr(fresh, "LocalOperator", lambda root: operator)
    commands = Mock(wraps=fresh.subprocess.run)
    monkeypatch.setattr(fresh.subprocess, "run", commands)
    with pytest.raises(ValueError, match="Removal target changed"):
        fresh.start_fresh(checkout)
    operator.stop.assert_called_once()
    assert target.stat().st_ino != initial_inode
    assert target.read_text() == "concurrent source"
    assert not (checkout / ".venv/bin/python").exists()
    receipt = json.loads(fresh.receipt_path(checkout, "start-fresh").read_text())
    assert receipt["status"] == "failed"
    assert receipt["error"] == "ValueError"
    assert "files" not in receipt["completed"]
    assert not any(call.args[0][0] == "bash" for call in commands.call_args_list)


@pytest.mark.parametrize("changed_state", ["worktree", "index", "head"])
def test_post_preview_git_changes_are_preserved_before_restore(
    checkout, monkeypatch, changed_state
):
    """Concurrent tracked changes after confirmation cannot be discarded by the final restore."""
    populate(checkout)
    relative = "data/corpus/manifest.json"
    target = checkout / relative

    def change_tracked_state():
        """Simulate a writer updating the manifest while cleanup stops its services."""
        target.write_text("new concurrent content")
        if changed_state in {"index", "head"}:
            subprocess.run(["git", "-C", str(checkout), "add", "--", relative], check=True)
        if changed_state == "head":
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "Concurrent fixture commit",
                ],
                check=True,
            )

    operator = Mock()
    operator.stop.side_effect = change_tracked_state
    monkeypatch.setattr(fresh, "LocalOperator", lambda root: operator)
    with pytest.raises(ValueError, match="Tracked Git state changed"):
        fresh.start_fresh(checkout, no_start=True)
    assert target.read_text() == "new concurrent content"
    if changed_state == "index":
        assert fresh.git(checkout, "show", f":{relative}") == "new concurrent content"
    if changed_state == "head":
        assert fresh.git(checkout, "show", f"HEAD:{relative}") == "new concurrent content"
    receipt = json.loads(fresh.receipt_path(checkout, "start-fresh").read_text())
    assert receipt["status"] == "failed"
    assert "tracked files" not in receipt["completed"]


def test_each_successful_fresh_start_issues_a_new_browser_reset(checkout):
    """Only an approved completed fresh cleanup publishes a new web reset identity."""
    from uuid import UUID

    assert fresh.start_fresh(checkout, no_start=True) == 0
    first = json.loads((checkout / "data/browser-reset.json").read_text())["reset_id"]
    UUID(first)
    assert fresh.start_fresh(checkout, no_start=True) == 0
    second = json.loads((checkout / "data/browser-reset.json").read_text())["reset_id"]
    UUID(second)
    assert first != second


def test_cancelled_fresh_start_does_not_schedule_browser_reset(checkout, monkeypatch):
    """Declining cleanup leaves browser reset state entirely unchanged."""
    monkeypatch.setattr(fresh, "confirm", lambda prompt: False)
    assert fresh.start_fresh(checkout, no_start=True) == 0
    assert not (checkout / "data/browser-reset.json").exists()


def test_fresh_preserves_builtin_and_custom_golden_files(checkout):
    """Preview never deletes authored evaluation data while clearing runtime artifacts."""
    folder = checkout / "data" / "golden"
    folder.mkdir()
    (folder / "retrieval.json").write_text("[]")
    (folder / "my-evaluation.json").write_text('{"cases": []}')
    plan = fresh.inventory(checkout, extreme=True, discard_tracked=False)
    assert not any(path.startswith("data/golden") for path in plan["files"])
    assert not any(path.startswith("data/golden") for path in plan["revert"])
