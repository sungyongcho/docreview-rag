"""Shared shell branding and isolated Bash/Zsh registration compatibility."""

import errno
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import time

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
    assert "  source " in result.stdout
    assert "cannot change its calling shell" in result.stdout
    assert "No shell was started." in result.stdout
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


def lifecycle_checkout(tmp_path, shell):
    """Create two harmless owned-command versions and a confined startup environment."""
    helper, _legacy, startup, environment = helper_checkout(tmp_path, shell)
    original = helper.read_text()
    pattern = r"(?ms)^rag-up\(\) \{.*?^\}"
    assert len(re.findall(pattern, original)) == 1
    versions = [
        re.sub(
            pattern,
            lambda _, name=name: "rag-up() {\n    printf '%s\n' 'fixture-version-" + name + "'\n}",
            original,
            count=1,
        )
        for name in ("one", "two")
    ]
    helper.write_text(versions[0])
    replacement = tmp_path / "next-helper.sh"
    replacement.write_text(versions[1])
    environment.update(
        NEXT_HELPER=str(replacement),
        STARTUP=str(startup),
        TEST_PYTHON=sys.executable,
        OLD_ROOT=str(helper.parent),
    )
    hashes = tuple(hashlib.sha256(value.encode()).hexdigest() for value in versions)
    return helper, startup, environment, hashes


def metadata_command():
    """Read only the two documented exported helper metadata values in a child process."""
    code = (
        "import json, os; print('EXPORTED:' + json.dumps(["
        "os.environ.get('DOCREVIEW_HELPER_SHA256'), "
        "os.environ.get('DOCREVIEW_HELPER_PATH')]))"
    )
    return '"$TEST_PYTHON" -c ' + shlex.quote(code)


def exported_metadata(output):
    """Decode the explicit metadata record without inspecting any unrelated environment."""
    records = [
        line.partition("EXPORTED:")[2]
        for line in output.splitlines()
        if line.startswith("EXPORTED:")
    ]
    assert len(records) == 1
    return json.loads(records[0])


def run_lifecycle_tty(shell, command, environment, *, answers="", interactive=True):
    """Run a bounded controlling-PTY child with every shell home confined to its fixture."""
    assert environment.get("HOME") and environment.get("ZDOTDIR")
    args = [shell, "--noprofile", "--norc"] if Path(shell).name == "bash" else [shell, "-f"]
    if interactive:
        args.append("-i")
    args.extend(["-c", command])
    isolated = {**os.environ, **environment, "TERM": "xterm-256color", "PS1": "", "PS2": ""}
    pid, master = pty.fork()
    if pid == 0:
        try:
            os.execve(shell, args, isolated)
        except OSError:
            os._exit(127)
    status = None
    chunks = []
    ended = False
    deadline = time.monotonic() + 20
    try:
        if answers:
            os.write(master, answers.encode())
        while time.monotonic() < deadline:
            if status is None:
                observed, code = os.waitpid(pid, os.WNOHANG)
                if observed:
                    status = os.waitstatus_to_exitcode(code)
            if select.select([master], [], [], 0.05)[0]:
                try:
                    data = os.read(master, 65536)
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    ended = True
                else:
                    if data:
                        chunks.append(data)
                    else:
                        ended = True
            if status is not None and ended:
                break
        assert status is not None, "Isolated helper PTY did not exit before its deadline."
        return subprocess.CompletedProcess(args, status, b"".join(chunks).decode(), "")
    finally:
        if status is None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
        os.close(master)


def test_update_check_preserves_unchanged_registration_and_exports(shell, tmp_path):
    """An unchanged read-only query reports the loaded file and writes no startup state."""
    helper, startup, environment, hashes = lifecycle_checkout(tmp_path, shell)
    original = "# Keep startup settings\nsource " + shlex.quote(str(helper)) + " >/dev/null\n"
    startup.write_text(original)
    timestamp = startup.stat().st_mtime_ns
    result = run_shell(
        shell,
        'set -e; source "$HELPER" >/dev/null; rag-alias --check-updates; ' + metadata_command(),
        env=environment,
    )
    assert "Up to date" in result.stdout
    assert exported_metadata(result.stdout) == [hashes[0], str(helper)]
    assert hashes[0] in result.stdout and str(helper) in result.stdout
    assert startup.read_text() == original and startup.stat().st_mtime_ns == timestamp
    assert not list(tmp_path.glob(startup.name + ".docreview-backup-*"))


def test_update_reloads_owned_functions_and_preserves_custom_commands(shell, tmp_path):
    """A changed query leaves functions stale until update, which preserves user overrides."""
    helper, startup, environment, hashes = lifecycle_checkout(tmp_path, shell)
    original = "# Preserve custom startup\nsource " + shlex.quote(str(helper)) + " >/dev/null\n"
    startup.write_text(original)
    result = run_shell(
        shell,
        'set -e; source "$HELPER" >/dev/null; '
        'rag-dev() { printf "%s\n" fixture-custom-dev; }; '
        'cp "$NEXT_HELPER" "$HELPER"; rag-alias --check-updates; '
        'printf "%s\n" BEFORE_UPDATE; rag-up --help; '
        'rag-alias update; printf "%s\n" AFTER_UPDATE; rag-up --help; rag-dev; '
        + metadata_command(),
        env=environment,
    )
    before, after = result.stdout.split("AFTER_UPDATE", 1)
    assert "Update available" in before
    assert hashes[0] in before and hashes[1] in before
    assert "fixture-version-one" in before
    assert "fixture-version-two" in after and "fixture-custom-dev" in after
    assert exported_metadata(result.stdout) == [hashes[1], str(helper)]
    assert startup.read_text() == original
    assert startup.read_text().count(str(helper)) == 1


@pytest.mark.parametrize("target_kind", ["directory", "file"])
def test_update_repairs_only_the_existing_moved_checkout_registration(shell, tmp_path, target_kind):
    """An explicit moved target rebinds one owned line and retains every unrelated registration."""
    helper, startup, environment, hashes = lifecycle_checkout(tmp_path, shell)
    moved_root = tmp_path / "moved checkout's files"
    moved_helper = moved_root / "rag-alias.sh"
    foreign = "source /foreign/checkout/rag-alias.sh >/dev/null\n# Retain this comment\n"
    original = "source " + shlex.quote(str(helper)) + " >/dev/null\n" + foreign
    startup.write_text(original)
    environment.update(
        MOVED_ROOT=str(moved_root),
        UPDATE_TARGET=str(moved_root if target_kind == "directory" else moved_helper),
    )
    result = run_shell(
        shell,
        'set -e; source "$HELPER" >/dev/null; mv "$OLD_ROOT" "$MOVED_ROOT"; '
        'cp "$NEXT_HELPER" "$MOVED_ROOT/rag-alias.sh"; '
        'if rag-alias --check-updates; then exit 91; else [ "$?" = 2 ]; fi; '
        'rag-alias update "$UPDATE_TARGET"; rag-up --help; rag-alias update; ' + metadata_command(),
        env=environment,
    )
    assert "fixture-version-two" in result.stdout
    assert exported_metadata(result.stdout) == [hashes[1], str(moved_helper)]
    assert not helper.exists() and moved_helper.exists()
    updated = startup.read_text()
    assert str(helper) not in updated
    assert updated == "source " + shlex.quote(str(moved_helper)) + " >/dev/null\n" + foreign
    assert updated.count(shlex.quote(str(moved_helper))) == 1
    backups = list(tmp_path.glob(startup.name + ".docreview-backup-*"))
    assert len(backups) == 1 and backups[0].read_text() == original


@pytest.mark.parametrize("invalid_kind", ["missing", "unreadable", "invalid"])
@pytest.mark.parametrize("mode", ["update", "--check-updates"])
def test_update_rejects_unusable_targets_without_changing_loaded_state(
    shell, tmp_path, invalid_kind, mode
):
    """A missing, unreadable or non-helper target cannot alter functions or startup ownership."""
    if invalid_kind == "unreadable" and os.geteuid() == 0:
        pytest.skip("Root bypasses the unreadable-file fixture.")
    helper, startup, environment, hashes = lifecycle_checkout(tmp_path, shell)
    original = "source " + shlex.quote(str(helper)) + " >/dev/null\n"
    startup.write_text(original)
    target = tmp_path / "unusable/rag-alias.sh"
    target.parent.mkdir()
    if invalid_kind != "missing":
        target.write_text(
            "# This is not a DocReview helper.\nrag-up() { printf fixture-invalid; }\n"
        )
    if invalid_kind == "unreadable":
        target.chmod(0)
    environment.update(UPDATE_TARGET=str(target), UPDATE_MODE=mode)
    try:
        result = run_shell(
            shell,
            'set -e; source "$HELPER" >/dev/null; '
            'if rag-alias "$UPDATE_MODE" "$UPDATE_TARGET"; then exit 92; else [ "$?" = 2 ]; fi; '
            "rag-up --help; " + metadata_command(),
            env=environment,
        )
    finally:
        if target.exists():
            target.chmod(0o600)
    assert "fixture-version-one" in result.stdout
    assert exported_metadata(result.stdout) == [hashes[0], str(helper)]
    assert startup.read_text() == original
    assert not list(tmp_path.glob(startup.name + ".docreview-backup-*"))


@pytest.mark.parametrize("answer,installed", [("\n", False), ("y\n", True)])
def test_interactive_source_activates_immediately_and_persists_only_with_consent(
    shell, tmp_path, answer, installed
):
    """One direct source call activates commands while installation remains default-No."""
    helper, startup, environment, _hashes = lifecycle_checkout(tmp_path, shell)
    original = "# Keep this startup setting\n"
    startup.write_text(original)
    result = run_lifecycle_tty(
        shell,
        'source "$HELPER"; typeset -f rag-alias >/dev/null; rag-up --help',
        environment,
        answers=answer,
    )
    assert result.returncode == 0, result.stdout
    assert "fixture-version-one" in result.stdout
    assert "[y/N]" in result.stdout
    assert "\x1b" not in result.stdout
    if installed:
        assert startup.read_text().count(str(helper)) == 1
        backups = list(tmp_path.glob(startup.name + ".docreview-backup-*"))
        assert len(backups) == 1 and backups[0].read_text() == original
    else:
        assert startup.read_text() == original
        assert not list(tmp_path.glob(startup.name + ".docreview-backup-*"))


@pytest.mark.parametrize("context", ["noninteractive", "redirected", "startup"])
def test_readonly_source_contexts_never_prompt_or_persist(shell, tmp_path, context):
    """A TTY alone never authorizes registration from noninteractive, startup or redirected code."""
    _helper, startup, environment, _hashes = lifecycle_checkout(tmp_path, shell)
    original = (
        'source "$HELPER"\n# Keep variable-based startup loading\n'
        if context == "startup"
        else "# Keep startup\n"
    )
    startup.write_text(original)
    command = (
        'source "$STARTUP"'
        if context == "startup"
        else 'source "$HELPER"' + (" >/dev/null" if context == "redirected" else "")
    )
    result = run_lifecycle_tty(
        shell,
        command + "; rag-up --help",
        environment,
        answers="y\n",
        interactive=context != "noninteractive",
    )
    assert result.returncode == 0, result.stdout
    assert "fixture-version-one" in result.stdout
    assert "Install this checkout registration?" not in result.stdout
    assert startup.read_text() == original
    assert not list(tmp_path.glob(startup.name + ".docreview-backup-*"))


def test_update_after_declined_source_never_prompts_for_registration(shell, tmp_path):
    """An explicit code refresh cannot turn a declined install into startup persistence."""
    _helper, startup, environment, _hashes = lifecycle_checkout(tmp_path, shell)
    original = "# No helper registration\n"
    startup.write_text(original)
    result = run_lifecycle_tty(
        shell,
        'source "$HELPER"; cp "$NEXT_HELPER" "$HELPER"; rag-alias update; rag-up --help',
        environment,
        answers="n\ny\n",
    )
    assert result.returncode == 0, result.stdout
    assert "fixture-version-two" in result.stdout
    assert result.stdout.count("Install this checkout registration?") == 1
    assert startup.read_text() == original


@pytest.mark.parametrize("consent", [False, True])
def test_executed_login_offer_replaces_only_installer_and_requires_consent(
    shell, tmp_path, consent
):
    """A login stub verifies consent, exec identity and return to the original parent."""
    helper, startup, environment, _hashes = lifecycle_checkout(tmp_path, shell)
    startup.write_text("source " + shlex.quote(str(helper)) + " >/dev/null\n")
    original = startup.read_bytes()
    wrappers = tmp_path / "shell-stubs"
    wrappers.mkdir()
    for name in ("bash", "zsh"):
        executable = shutil.which(name)
        assert executable
        wrapper = wrappers / name
        wrapper.write_text(
            "#!/bin/sh\n"
            'for argument in "$@"; do\n'
            '  case "$argument" in -l|--login|-il|-li)\n'
            '    printf "%s\n" "$$" > "$LOGIN_PID"\n'
            '    printf "%s\n" "$*" > "$LOGIN_ARGS"\n'
            '    printf "%s\n" "$HOME" > "$LOGIN_HOME"\n'
            "    exit 23;; esac\n"
            "done\nexec " + shlex.quote(executable) + ' "$@"\n'
        )
        wrapper.chmod(0o755)
    launcher = tmp_path / "installer-launcher.sh"
    launcher.write_text('#!/bin/sh\nprintf "%s\n" "$$" > "$INSTALLER_PID"\nexec "$HELPER"\n')
    launcher.chmod(0o755)
    environment.update(
        PATH=str(wrappers) + os.pathsep + os.environ["PATH"],
        SHELL=str(wrappers / Path(shell).name),
        INSTALLER=str(launcher),
        INSTALLER_PID=str(tmp_path / "installer.pid"),
        LOGIN_PID=str(tmp_path / "login.pid"),
        LOGIN_ARGS=str(tmp_path / "login.args"),
        LOGIN_HOME=str(tmp_path / "login.home"),
    )
    result = run_lifecycle_tty(
        shell,
        'printf "PARENT_BEFORE:%s\n" "$$"; "$INSTALLER"; code=$?; '
        'printf "PARENT_AFTER:%s:%s\n" "$$" "$code"',
        environment,
        answers="y\n" if consent else "\n",
    )
    assert result.returncode == 0, result.stdout
    before = re.search(r"PARENT_BEFORE:(\d+)", result.stdout)
    after = re.search(r"PARENT_AFTER:(\d+):(\d+)", result.stdout)
    assert before and after and before[1] == after[1]
    assert "[y/N]" in result.stdout and "login shell" in result.stdout
    assert "installer process" in result.stdout and "original shell" in result.stdout
    source_lines = [
        line.strip() for line in result.stdout.splitlines() if line.strip().startswith("source ")
    ]
    assert any(shlex.split(line) == ["source", str(helper)] for line in source_lines)
    assert startup.read_bytes() == original
    if consent:
        assert after[2] == "23"
        assert (
            Path(environment["LOGIN_PID"]).read_text()
            == Path(environment["INSTALLER_PID"]).read_text()
        )
        assert Path(environment["LOGIN_ARGS"]).read_text().strip() in {"-l", "--login"}
        assert Path(environment["LOGIN_HOME"]).read_text().strip() == str(tmp_path)
    else:
        assert after[2] == "0"
        assert not Path(environment["LOGIN_PID"]).exists()


def test_update_check_never_executes_the_candidate_helper(shell, tmp_path):
    """A read-only version query hashes a candidate without executing even its valid shell body."""
    helper, startup, environment, hashes = lifecycle_checkout(tmp_path, shell)
    original = "# Keep startup untouched\n"
    startup.write_text(original)
    marker = tmp_path / "candidate-executed"
    candidate = Path(environment["NEXT_HELPER"])
    candidate.write_text(
        candidate.read_text() + 'printf candidate-executed > "$CANDIDATE_EXECUTED"\n'
    )
    candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    environment["CANDIDATE_EXECUTED"] = str(marker)
    result = run_shell(
        shell,
        'set -e; source "$HELPER" >/dev/null; cp "$NEXT_HELPER" "$HELPER"; '
        "rag-alias --check-updates; rag-up --help; " + metadata_command(),
        env=environment,
    )
    assert "Update available" in result.stdout
    assert candidate_hash in result.stdout
    assert "fixture-version-one" in result.stdout
    assert exported_metadata(result.stdout) == [hashes[0], str(helper)]
    assert not marker.exists()
    assert startup.read_text() == original


def test_moved_update_retries_registration_after_access_is_restored(shell, tmp_path):
    """A failed startup-file repair retains the old path until an explicit successful retry."""
    if os.geteuid() == 0:
        pytest.skip("Root bypasses the unreadable-startup fixture.")
    helper, startup, environment, hashes = lifecycle_checkout(tmp_path, shell)
    original = "# Keep startup order\nsource " + shlex.quote(str(helper)) + " >/dev/null\n"
    startup.write_text(original)
    moved_root = tmp_path / "moved retry checkout"
    moved_helper = moved_root / "rag-alias.sh"
    environment["MOVED_ROOT"] = str(moved_root)
    try:
        result = run_shell(
            shell,
            'set -e; source "$HELPER" >/dev/null; mv "$OLD_ROOT" "$MOVED_ROOT"; '
            'cp "$NEXT_HELPER" "$MOVED_ROOT/rag-alias.sh"; chmod 000 "$STARTUP"; '
            'if rag-alias update "$MOVED_ROOT"; then exit 93; else [ "$?" = 1 ]; fi; '
            'chmod 600 "$STARTUP"; rag-alias update; rag-up --help; ' + metadata_command(),
            env=environment,
        )
    finally:
        startup.chmod(0o600)
    assert "fixture-version-two" in result.stdout
    assert exported_metadata(result.stdout) == [hashes[1], str(moved_helper)]
    assert (
        startup.read_text()
        == "# Keep startup order\nsource " + shlex.quote(str(moved_helper)) + " >/dev/null\n"
    )
    backups = list(tmp_path.glob(startup.name + ".docreview-backup-*"))
    assert len(backups) == 1 and backups[0].read_text() == original


def test_unchanged_update_deduplicates_owned_lines_in_place(shell, tmp_path):
    """An unchanged code version still repairs duplicate current and legacy registration lines."""
    helper, startup, environment, hashes = lifecycle_checkout(tmp_path, shell)
    legacy = helper.with_name("rag_alias.sh")
    current = "source " + shlex.quote(str(helper)) + " >/dev/null\n"
    foreign = "source /foreign/checkout/rag-alias.sh >/dev/null\n"
    original = (
        "# Before owned registration\n"
        + current
        + "# Keep between markers\n"
        + "source "
        + shlex.quote(str(legacy))
        + " >/dev/null\n"
        + current
        + "# Keep after markers\n"
        + foreign
    )
    startup.write_text(original)
    result = run_shell(
        shell,
        'set -e; source "$HELPER" >/dev/null; rag-alias update; ' + metadata_command(),
        env=environment,
    )
    assert "Up to date" in result.stdout
    assert exported_metadata(result.stdout) == [hashes[0], str(helper)]
    assert startup.read_text() == (
        "# Before owned registration\n"
        + current
        + "# Keep between markers\n# Keep after markers\n"
        + foreign
    )
    backups = list(tmp_path.glob(startup.name + ".docreview-backup-*"))
    assert len(backups) == 1 and backups[0].read_text() == original
    assert not legacy.exists()
