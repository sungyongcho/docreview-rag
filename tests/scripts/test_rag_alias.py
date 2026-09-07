"""Shared shell branding and isolated Bash/Zsh registration compatibility."""

import os
from pathlib import Path
import pty
import re
import shlex
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "rag-alias.sh"
WORDMARK = (ROOT / "web/branding/wordmark.txt").read_text()
MONOGRAM = (ROOT / "web/branding/monogram.txt").read_text()


@pytest.fixture(params=["bash", "zsh"])
def shell(request):
    """Require both supported shells instead of hiding missing compatibility checks."""
    executable = shutil.which(request.param)
    assert executable, f"Required shell is unavailable: {request.param}"
    return executable


def run_shell(shell, command, *, env=None, input=""):
    """Run an isolated shell without loading any user's startup files."""
    args = [shell, "--noprofile", "--norc"] if Path(shell).name == "bash" else [shell, "-f"]
    return subprocess.run(
        [*args, "-c", command, "docreview-test", str(SCRIPT)],
        env={**os.environ, "TERM": "xterm-256color", "SHELL": shell, **(env or {})},
        input=input,
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.mark.parametrize("answer", ["", "n\n"])
def test_shell_syntax_and_direct_setup(shell, tmp_path, answer):
    """Execution offers installation without modifying a declined isolated home."""
    subprocess.run([shell, "-n", str(SCRIPT)], check=True, capture_output=True)
    result = run_shell(
        shell,
        '"$SHELL_TEST" "$1"',
        env={"SHELL_TEST": shell, "COLUMNS": "80", "HOME": str(tmp_path), "ZDOTDIR": str(tmp_path)},
        input=answer,
    )
    assert WORDMARK in result.stdout
    assert "DocReview RAG v2" in result.stdout
    assert "rag-help" in result.stdout
    assert "Install this checkout registration? [y/N]" in result.stdout
    assert "Cancelled" in result.stdout
    assert not (tmp_path / ".bashrc").exists()
    assert not (tmp_path / ".zshrc").exists()
    assert "\x1b" not in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("columns", "asset"),
    [("80", WORDMARK), ("78", WORDMARK), ("77", MONOGRAM), ("18", MONOGRAM), ("16", None)],
)
def test_source_registration_help_and_width(shell, columns, asset):
    """Sourcing stays quiet when redirected while help selects readable static assets."""
    result = run_shell(
        shell,
        'source "$1" >/dev/null; typeset -f rag-help >/dev/null; '
        "typeset -f rag-dev >/dev/null; rag-help",
        env={"COLUMNS": columns},
    )
    assert "[OK]" not in result.stdout
    assert "[STACK]" in result.stdout
    assert "DocReview RAG v2" in result.stdout
    assert "\x1b" not in result.stdout
    assert result.stderr == ""
    if asset:
        assert asset in result.stdout
    else:
        assert WORDMARK not in result.stdout
        assert MONOGRAM not in result.stdout


def test_banner_needs_only_standard_tools(shell, tmp_path):
    """A sourced banner and help do not invoke Python, Node, FIGlet, or a network client."""
    tools = tmp_path / "tools"
    tools.mkdir()
    cat = shutil.which("cat")
    assert cat
    (tools / "cat").symlink_to(cat)
    result = run_shell(
        shell,
        'source "$1" >/dev/null; PATH="$BANNER_TOOLS"; rag-help',
        env={"BANNER_TOOLS": str(tools), "COLUMNS": "80"},
    )
    assert WORDMARK in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("environment", [{}, {"NO_COLOR": ""}, {"TERM": "dumb"}])
def test_help_is_always_escape_free(shell, environment):
    """The complete menu stays plain even on a color-capable TTY without an opt-out."""
    args = [shell, "--noprofile", "--norc"] if Path(shell).name == "bash" else [shell, "-f"]
    master, slave = pty.openpty()
    try:
        subprocess.run(
            [*args, "-c", 'source "$1" >/dev/null; rag-help', "test", str(SCRIPT)],
            env={**os.environ, "TERM": "xterm-256color", "COLUMNS": "80", **environment},
            stdin=subprocess.DEVNULL,
            stdout=slave,
            stderr=subprocess.PIPE,
            check=True,
        )
        output = os.read(master, 4096).decode()
        assert "DocReview RAG v2" in output
        assert "\x1b" not in output
    finally:
        os.close(slave)
        os.close(master)


def test_python_help_is_escape_free_on_a_forced_color_tty(shell, tmp_path):
    """Argparse help stays plain without changing the calling shell or invoking services."""
    helper, _legacy, _startup, settings = helper_checkout(tmp_path, shell)
    (helper.parent / ".venv").symlink_to(sys.prefix, target_is_directory=True)
    (helper.parent / ".env").write_text("DB_PORT=1\n")
    tools = tmp_path / "blocked-tools"
    tools.mkdir()
    called = tmp_path / "service-called"
    for name in ("docker", "uv", "ollama"):
        command = tools / name
        command.write_text('#!/bin/sh\nprintf called > "$SERVICE_CALLED"\nexit 97\n')
        command.chmod(0o755)
    environment = {
        **os.environ,
        **settings,
        "TERM": "xterm-256color",
        "FORCE_COLOR": "1",
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        "SERVICE_CALLED": str(called),
    }
    environment.pop("NO_COLOR", None)
    environment.pop("PYTHON_COLORS", None)
    args = [shell, "--noprofile", "--norc"] if Path(shell).name == "bash" else [shell, "-f"]
    master, slave = pty.openpty()
    try:
        subprocess.run(
            [
                *args,
                "-c",
                'source "$HELPER" >/dev/null; rag-schema --help && '
                '[ "$FORCE_COLOR" = 1 ] && [ -z "${NO_COLOR+x}" ] && '
                '[ -z "${PYTHON_COLORS+x}" ]',
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=slave,
            stderr=subprocess.PIPE,
            timeout=10,
            check=True,
        )
        output = os.read(master, 8192).decode()
        assert "usage:" in output.lower()
        assert "{check,prepare,recover,recreate}" in output
        assert "\x1b" not in output
        assert not called.exists()
    finally:
        os.close(slave)
        os.close(master)


def test_uninstall_cancellation_preserves_commands_and_startup_file(shell, tmp_path):
    """Declining removal leaves a temporary registration and owned commands intact."""
    startup = tmp_path / "startup"
    original = f'source "{SCRIPT}" >/dev/null\n# Keep unrelated content.\n'
    startup.write_text(original)
    result = run_shell(
        shell,
        'source "$1" >/dev/null; _DOCREVIEW_RC="$TEST_STARTUP"; '
        "rag-alias-delete; typeset -f rag-help >/dev/null",
        env={"TEST_STARTUP": str(startup)},
        input="n\n",
    )
    assert "Cancelled" in result.stdout
    assert startup.read_text() == original


def test_uninstall_preserves_foreign_commands_and_exact_source_ownership(shell, tmp_path):
    """Confirmed removal touches only this checkout's exact source lines and owned commands."""
    startup = tmp_path / "startup"
    unrelated = (
        "source /other/checkout/rag-alias.sh >/dev/null\n"
        f'source "{SCRIPT}" && echo keep-composed-command\n'
        "# Preserve the rest of this temporary file.\n"
    )
    original = f'source "{SCRIPT}" >/dev/null\n' + unrelated
    startup.write_text(original)
    result = run_shell(
        shell,
        'source "$1" >/dev/null; _DOCREVIEW_RC="$TEST_STARTUP"; '
        'rag-dev() { printf "%s\\n" foreign-command; }; '
        "alias rag-prod-up='printf foreign-alias'; "
        "rag-alias-delete; rag-dev; alias rag-prod-up; "
        "if typeset -f rag-help >/dev/null; then exit 7; fi; "
        "if typeset -f rag-fresh-start >/dev/null; then exit 8; fi; "
        "if typeset -f rag-corpus >/dev/null; then exit 9; fi",
        env={"TEST_STARTUP": str(startup)},
        input="y\n",
    )
    assert "foreign-command" in result.stdout
    assert "foreign-alias" in result.stdout
    assert startup.read_text() == unrelated
    backups = list(tmp_path.glob("startup.docreview-backup-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == original


def test_fresh_start_help_and_registration(shell):
    """Both shells advertise the warning and register reset and corpus wrappers."""
    result = run_shell(
        shell, 'source "$1" >/dev/null; typeset -f rag-fresh-start; typeset -f rag-corpus; rag-help'
    )
    assert "scripts.stack.commands fresh-start" in result.stdout
    assert "scripts.stack.commands corpus" in result.stdout
    assert "rag-fresh-start [--status|--extreme]" in result.stdout
    assert "WARNING ordinary reset: deletes DB" in result.stdout
    assert "WARNING extreme reset: also deletes" in result.stdout
    assert "preserves code, .env and host Ollama" in result.stdout


@pytest.mark.parametrize("existing", [False, True])
def test_direct_install_verify_and_delete(shell, tmp_path, existing):
    """Install once, preserve startup content, verify again and explicitly remove."""
    environment = {"HOME": str(tmp_path), "ZDOTDIR": str(tmp_path)}
    rc = tmp_path / (".zshrc" if Path(shell).name == "zsh" else ".bashrc")
    original = "# User settings without a final newline" if existing else ""
    if existing:
        rc.write_text(original)
    result = run_shell(shell, '"$1"', env=environment, input="y\n")
    assert "[OK]" in result.stdout
    assert "no shell restart" in result.stdout
    assert "--delete" in result.stdout
    assert "Remove this registration?" not in result.stdout
    installed = rc.read_text()
    assert installed.startswith(original)
    assert installed.count(str(SCRIPT)) == 1
    result = run_shell(shell, '"$1"', env=environment, input="y\n")
    assert "[INSTALLED]" in result.stdout
    assert "Install this checkout registration?" not in result.stdout
    assert "Remove this registration?" not in result.stdout
    assert rc.read_text() == installed
    result = run_shell(
        shell,
        'source "$TEST_RC"; typeset -f rag-help >/dev/null; rag-help',
        env={**environment, "TEST_RC": str(rc)},
    )
    assert "[STACK]" in result.stdout
    result = run_shell(shell, '"$1" --delete', env=environment, input="y\n")
    assert "Removed this checkout" in result.stdout
    assert str(SCRIPT) not in rc.read_text()
    assert rc.read_text().rstrip("\n") == original


def test_failed_validation_does_not_install(shell, tmp_path):
    """A checkout missing wrapper targets must not be reported or registered as installed."""
    checkout = tmp_path / "incomplete checkout"
    checkout.mkdir()
    script = checkout / "rag-alias.sh"
    shutil.copy2(SCRIPT, script)
    environment = {**os.environ, "SHELL": shell, "HOME": str(tmp_path), "ZDOTDIR": str(tmp_path)}
    result = subprocess.run(
        [str(script)], input="y\n", text=True, capture_output=True, env=environment, check=False
    )
    assert result.returncode == 1
    assert "Missing helper target" in result.stderr
    assert "[OK]" not in result.stdout
    assert not (tmp_path / ".bashrc").exists()
    assert not (tmp_path / ".zshrc").exists()


def test_installed_interactive_execution_never_removes_registration(shell, tmp_path):
    """Even a queued Y on a terminal cannot trigger removal during normal execution."""
    rc = tmp_path / (".zshrc" if Path(shell).name == "zsh" else ".bashrc")
    original = f'source "{SCRIPT}" >/dev/null\n'
    rc.write_text(original)
    master, slave = pty.openpty()
    try:
        os.write(master, b"y\n")
        result = subprocess.run(
            [str(SCRIPT)],
            stdin=slave,
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "SHELL": shell, "HOME": str(tmp_path), "ZDOTDIR": str(tmp_path)},
            check=True,
        )
    finally:
        os.close(slave)
        os.close(master)
    assert "[INSTALLED]" in result.stdout
    assert "Remove this registration?" not in result.stdout
    assert rc.read_text() == original


def test_install_preserves_symlink_and_quotes_checkout_path(shell, tmp_path):
    """Quoted checkout paths survive startup loading without replacing rc symlinks."""
    checkout = tmp_path / "checkout's helper"
    checkout.mkdir()
    script = checkout / "rag-alias.sh"
    shutil.copy2(SCRIPT, script)
    for name in [
        "stack/__main__.py",
        "stack/quickstart.sh",
        "stack/commands.py",
        "schema/__main__.py",
        "diagnostics/ollama.py",
    ]:
        target = checkout / "scripts" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Isolated wrapper target.\n")
    target_rc = tmp_path / "managed-startup"
    target_rc.write_text("# User configuration\n")
    rc = tmp_path / (".zshrc" if Path(shell).name == "zsh" else ".bashrc")
    rc.symlink_to(target_rc)
    environment = {
        "HOME": str(tmp_path),
        "ZDOTDIR": str(tmp_path),
        "HELPER": str(script),
        "RC": str(rc),
    }
    result = run_shell(shell, '"$HELPER"', env=environment, input="y\n")
    assert "[OK]" in result.stdout
    assert rc.is_symlink()
    assert target_rc.read_text().startswith("# User configuration\n")
    result = run_shell(shell, 'source "$RC"; rag-help; "$HELPER"', env=environment)
    assert "[STACK]" in result.stdout
    assert "[INSTALLED]" in result.stdout


def test_help_lists_unique_commands_with_compact_descriptions(shell):
    """The rendered menu keeps one short row per command and groups flag variants inline."""
    result = run_shell(shell, 'source "$1" >/dev/null; rag-help')
    rows = [line.strip() for line in result.stdout.splitlines() if line.startswith("  rag-")]
    assert 1 <= len(rows) <= 15
    commands = []
    invocations = []
    for row in rows:
        invocation, description = re.split(r"\s{2,}", row, maxsplit=1)
        commands.append(invocation.split()[0])
        invocations.append(invocation)
        assert 1 <= len(description.split()) <= 4, row
    assert len(invocations) == len(set(invocations))
    assert commands.count("rag-schema") == 3
    assert "rag-schema" in commands
    assert "rag-ollama-check" in commands
    assert "--help" not in "\n".join(rows)
    assert result.stdout.count("Every command accepts --help") == 1
    assert "Example: rag-corpus acquire_edgar" in result.stdout


def test_removed_aliases_are_not_registered(shell):
    """Removed duplicate names cannot stay callable after loading the compact helper."""
    run_shell(
        shell,
        'source "$1" >/dev/null; '
        "for name in rag-dev-up rag-dev-down rag-prod-up rag-prod-down rag-diagnose; do "
        'if command -v "$name" >/dev/null 2>&1; then exit 7; fi; done',
    )


def test_every_advertised_help_preserves_checkout_and_registration(shell, tmp_path):
    """Real helper help never installs dependencies, calls services, or changes local files."""
    checkout = tmp_path / "isolated checkout"
    checkout.mkdir()
    helper = checkout / "rag-alias.sh"
    shutil.copy2(SCRIPT, helper)
    shutil.copytree(
        ROOT / "scripts", checkout / "scripts", ignore=shutil.ignore_patterns("__pycache__")
    )
    (checkout / ".venv").symlink_to(sys.prefix, target_is_directory=True)
    (checkout / ".env").write_text("UNRELATED_SETTING=preserved\n")
    startup = tmp_path / ".bashrc"
    startup.write_text("# Preserve existing shell configuration.\n")
    (tmp_path / ".zshrc").write_text(startup.read_text())
    tools = tmp_path / "blocked-tools"
    tools.mkdir()
    for name in ("docker", "uv", "ollama", "npm"):
        command = tools / name
        command.write_text(
            "#!/bin/sh\nprintf 'External command called during help\n' >&2\nexit 97\n"
        )
        command.chmod(0o755)
    before = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    menu = run_shell(shell, 'source "$1" >/dev/null; rag-help').stdout
    commands = list(
        dict.fromkeys(line.split()[0] for line in menu.splitlines() if line.startswith("  rag-"))
    )
    assert commands
    result = run_shell(
        shell,
        'source "$HELPER" >/dev/null; for name in ' + " ".join(commands) + "; do "
        '"$name" --help >/dev/null || exit $?; done',
        env={
            "HELPER": str(helper),
            "HOME": str(tmp_path),
            "ZDOTDIR": str(tmp_path),
            "PYTHONPATH": str(ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
        },
    )
    assert result.stderr == ""
    after = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    assert after == before


def test_quickstart_is_first_and_reset_commands_have_their_own_block(shell):
    """The primary setup action stands alone before separate data and reset choices."""
    menu = run_shell(shell, 'source "$1" >/dev/null; rag-help').stdout
    quick = menu.split("[QUICK START]", 1)[1].split("[STACK]", 1)[0]
    assert [line.split()[0] for line in quick.splitlines() if line.startswith("  rag-")] == [
        "rag-quickstart"
    ]
    assert "Then open the printed URL." in quick
    reset = menu.split("[RESET]", 1)[1].split("[HELP]", 1)[0]
    assert "rag-schema recover" in reset
    assert "rag-schema recreate" in reset
    assert "rag-fresh-start" in reset
    assert "WARNING ordinary reset:" in reset
    assert "WARNING extreme reset:" in reset
    assert "WARNING schema recreate:" in reset
    assert 10 <= sum(line.startswith("  rag-") for line in menu.splitlines()) <= 15


def helper_checkout(tmp_path, shell):
    """Copy only the helper's read-only prerequisites into an isolated shell home."""
    checkout = tmp_path / "checkout with spaces"
    checkout.mkdir()
    helper = checkout / "rag-alias.sh"
    shutil.copy2(SCRIPT, helper)
    shutil.copytree(
        ROOT / "scripts", checkout / "scripts", ignore=shutil.ignore_patterns("__pycache__")
    )
    legacy = helper.with_name(helper.name.replace("-", "_"))
    startup = tmp_path / (".bashrc" if Path(shell).name == "bash" else ".zshrc")
    environment = {
        "HELPER": str(helper),
        "HOME": str(tmp_path),
        "ZDOTDIR": str(tmp_path),
        "SHELL": shell,
    }
    return helper, legacy, startup, environment


@pytest.mark.parametrize("accept", [False, True])
def test_old_registration_migrates_only_after_explicit_confirmation(shell, tmp_path, accept):
    """A renamed helper explains the missing path and preserves a backup before migration."""
    helper, legacy, startup, environment = helper_checkout(tmp_path, shell)
    foreign = "source /another/checkout/helper.sh\n"
    original = (
        "# User configuration\nsource " + shlex.quote(str(legacy)) + " >/dev/null\n" + foreign
    )
    startup.write_text(original)
    result = run_shell(shell, '"$HELPER"', env=environment, input="y\n" if accept else "n\n")
    assert "[MIGRATION]" in result.stdout
    assert str(legacy) in result.stdout
    assert not legacy.exists()
    if not accept:
        assert startup.read_text() == original
        assert not list(tmp_path.glob(startup.name + ".docreview-backup-*"))
        return
    assert str(legacy) not in startup.read_text()
    assert shlex.quote(str(helper)) in startup.read_text()
    assert foreign in startup.read_text()
    backups = list(tmp_path.glob(startup.name + ".docreview-backup-*"))
    assert len(backups) == 1 and backups[0].read_text() == original
    again = run_shell(shell, '"$HELPER"', env=environment)
    assert "[INSTALLED]" in again.stdout
    assert "[MIGRATION]" not in again.stdout


def test_uninstall_removes_current_and_legacy_registration_only_for_this_checkout(shell, tmp_path):
    """Explicit removal covers both owned names without touching another checkout's line."""
    helper, legacy, startup, environment = helper_checkout(tmp_path, shell)
    foreign = "source /another/checkout/" + legacy.name + "\n"
    original = (
        "\n".join("source " + shlex.quote(str(path)) for path in (helper, legacy)) + "\n" + foreign
    )
    startup.write_text(original)
    result = run_shell(shell, '"$HELPER" --delete', env=environment, input="y\n")
    assert str(legacy) in result.stdout
    assert startup.read_text() == foreign
    backups = list(tmp_path.glob(startup.name + ".docreview-backup-*"))
    assert len(backups) == 1 and backups[0].read_text() == original
    assert helper.exists() and not legacy.exists()
