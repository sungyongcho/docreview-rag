"""The pre-commit hook keeps secrets out of what a commit would publish.

The repository is public, so a key that reaches a commit is published by the next push.
Nothing else stops it: `.env` files are ignored by Git, but a value copied into a tracked
file, or an env file added with `git add -f`, would go out unchecked.
"""

from pathlib import Path
import shutil
import subprocess

import pytest

HOOKS = Path(__file__).resolve().parents[2] / ".githooks"
# Built at run time so this file itself holds no credential form.
_OPENAI_FORM = "sk-" + "proj-" + "A1b2C3d4" * 4
_LOCAL_VALUE = "local-" + "Zq7" * 6


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with the project's hooks and a local `.env` that Git ignores."""
    _git(tmp_path, "init", "-q")
    shutil.copytree(HOOKS, tmp_path / ".githooks")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        f"OPENAI_API_KEY_LOCAL={_LOCAL_VALUE}\nLOG_LEVEL=information-only\n", encoding="utf-8"
    )
    return tmp_path


def _refusal(repo: Path, files: dict[str, str], *, force: bool = False) -> str | None:
    """Stage the files, run the hook; return what it says when it refuses."""
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
        _git(repo, "add", *(["-f"] if force else []), name)
    done = subprocess.run(
        ["bash", str(repo / ".githooks" / "pre-commit")],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return done.stderr if done.returncode else None


def test_an_ordinary_change_is_accepted(repo: Path) -> None:
    """Accept code that names variables but holds no secret value."""
    files = {"app/settings.py": 'KEY_NAME = "OPENAI_API_KEY_LOCAL"\nLEVEL = "information-only"\n'}

    assert _refusal(repo, files) is None


@pytest.mark.parametrize(
    ("files", "force", "reason"),
    [
        (
            {"app/config.py": f'KEY = "{_LOCAL_VALUE}"\n'},
            False,
            "the value of OPENAI_API_KEY_LOCAL",
        ),
        ({"docs/run.md": f"export KEY={_OPENAI_FORM}\n"}, False, "an OpenAI or Anthropic API key"),
        ({".env": f"OPENAI_API_KEY_LOCAL={_LOCAL_VALUE}\n"}, True, "an env file is staged"),
        ({"deploy/.env.prod": "MODE=production\n"}, False, "an env file is staged"),
    ],
)
def test_a_secret_in_the_staged_change_is_refused_without_showing_it(
    repo: Path, files: dict[str, str], force: bool, reason: str
) -> None:
    """Refuse a local secret value, a key form and a staged env file, naming only the place."""
    refusal = _refusal(repo, files, force=force)

    assert refusal is not None
    assert reason in refusal
    assert _LOCAL_VALUE not in refusal
    assert _OPENAI_FORM not in refusal


def test_a_documented_fake_line_can_be_allowed(repo: Path) -> None:
    """Accept a key form on a line that marks itself as an intended fake."""
    files = {"tests/fake.py": f'FAKE = "{_OPENAI_FORM}"  # secret-scan: allow\n'}

    assert _refusal(repo, files) is None


def test_the_example_env_file_may_be_committed(repo: Path) -> None:
    """Accept `.env.example`, which documents names without values."""
    assert _refusal(repo, {".env.example": "OPENAI_API_KEY_LOCAL=\n"}) is None
