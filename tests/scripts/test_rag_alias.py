"""Shared shell branding and isolated Bash/Zsh registration compatibility."""

import os
from pathlib import Path
import pty
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "rag_alias.sh"
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
        env={**os.environ, "TERM": "xterm-256color", **(env or {})},
        input=input,
        capture_output=True,
        text=True,
        check=True,
    )


def test_shell_syntax_and_direct_setup(shell):
    """Execution explains sourcing and prints the canonical full wordmark."""
    subprocess.run([shell, "-n", str(SCRIPT)], check=True, capture_output=True)
    result = run_shell(shell, '"$SHELL_TEST" "$1"', env={"SHELL_TEST": shell, "COLUMNS": "80"})
    assert WORDMARK in result.stdout
    assert "DocReview RAG v2" in result.stdout
    assert "rag-help" in result.stdout
    assert "source" in result.stdout or "[INSTALLED]" in result.stdout
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
        "alias rag-dev-up >/dev/null; rag-help",
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


@pytest.mark.parametrize("environment", [{"NO_COLOR": ""}, {"TERM": "dumb"}])
def test_color_opt_out_is_escape_free(shell, environment):
    """Color opt-outs suppress escapes even when banner output goes to an actual TTY."""
    args = [shell, "--noprofile", "--norc"] if Path(shell).name == "bash" else [shell, "-f"]
    master, slave = pty.openpty()
    try:
        subprocess.run(
            [*args, "-c", 'source "$1" >/dev/null; _docreview_banner', "test", str(SCRIPT)],
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
        "source /other/checkout/rag_alias.sh >/dev/null\n"
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
        "if typeset -f rag-help >/dev/null; then exit 7; fi",
        env={"TEST_STARTUP": str(startup)},
        input="y\n",
    )
    assert "foreign-command" in result.stdout
    assert "foreign-alias" in result.stdout
    assert startup.read_text() == unrelated
    backups = list(tmp_path.glob("startup.docreview-backup-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == original
