"""Refuse a staged change that would put a secret into this public repository.

Run by ``.githooks/pre-commit`` from the repository root. It reads only the staged
change, so what it judges is exactly what the commit would publish. Three things refuse:

- a staged ``.env`` or ``.env.*`` file other than ``.env.example``;
- an added line holding the value of a secret-named variable from a local env file
  (the repository's own ``.env`` files, which Git ignores);
- an added line matching a well-known credential form (provider API keys, private keys).

A refusal names the file, the line and the reason, never the value. A line that must
carry such a form on purpose (a documented fake) says ``secret-scan: allow``.
"""

from collections.abc import Iterator
import os
from pathlib import Path
import re
import subprocess
import sys

ALLOW_MARK = "secret-scan: allow"
_SKIPPED_FOLDERS = frozenset({".git", ".venv", "node_modules", ".next", "__pycache__"})
_SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|DSN", re.I)
_MIN_VALUE_LENGTH = 12
_FORMS = {
    "an OpenAI or Anthropic API key": re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    "an AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "a GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"),
    "a Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "a Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "a private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def is_env_file(path: str) -> bool:
    """Tell whether a path names an env file that must stay out of Git."""
    name = Path(path).name
    return (name == ".env" or name.startswith(".env.")) and name != ".env.example"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def local_env_files(root: Path) -> Iterator[Path]:
    """Yield the env files present in the working tree, without entering tool folders."""
    for folder, folders, files in os.walk(root):
        folders[:] = sorted(name for name in folders if name not in _SKIPPED_FOLDERS)
        for name in sorted(files):
            if is_env_file(name):
                yield Path(folder) / name


def secret_values(files: Iterator[Path]) -> dict[str, str]:
    """Map each secret-looking value of the env files to its variable name."""
    values: dict[str, str] = {}
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.removeprefix("export ").split("=", 1)
            name, value = name.strip(), value.strip().strip("'\"")
            credential_url = "://" in value and "@" in value
            if len(value) >= _MIN_VALUE_LENGTH and (_SECRET_NAME.search(name) or credential_url):
                values[value] = name
    return values


def added_lines(diff: str) -> Iterator[tuple[str, int, str]]:
    """Yield (path, line number, text) for every line a ``git diff -U0`` adds."""
    path, number = "", 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else ""
        elif hunk := _HUNK.match(line):
            number = int(hunk.group(1))
        elif line.startswith("+") and path:
            yield path, number, line[1:]
            number += 1


def findings(staged_paths: list[str], diff: str, values: dict[str, str]) -> list[str]:
    """Return one message per staged env file and per added line that holds a secret."""
    found = [f"{path}: an env file is staged" for path in staged_paths if is_env_file(path)]
    for path, number, text in added_lines(diff):
        if ALLOW_MARK in text:
            continue
        reasons = [f"the value of {name}" for value, name in values.items() if value in text]
        reasons += [form for form, pattern in _FORMS.items() if pattern.search(text)]
        found += [f"{path}:{number}: {reason}" for reason in reasons]
    return found


def main() -> int:
    """Judge the staged change of the repository this runs in; 1 refuses the commit."""
    root = Path(_git("rev-parse", "--show-toplevel").strip())
    staged = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0")
    diff = _git("diff", "--cached", "-U0", "--no-color", "--no-ext-diff", "--diff-filter=ACMR")
    problems = findings(
        [path for path in staged if path], diff, secret_values(local_env_files(root))
    )
    if not problems:
        return 0
    for problem in problems:
        print(f"pre-commit: secret refused: {problem}", file=sys.stderr)
    print(
        f"pre-commit: remove it from the staged change; a documented fake line says '{ALLOW_MARK}'",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
