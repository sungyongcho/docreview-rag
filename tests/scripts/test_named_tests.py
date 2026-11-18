"""A script or module that names a test names one that exists.

Release scripts and docstrings point at tests by path, and a moved or renamed test
leaves that pointer behind without any check failing; a script then stops only when
someone runs it.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
# Runnable code and its guides; prose under docs/ may name a path as an illustration.
_FOLDERS = ("app", "scripts", "deploy", "docker", ".githooks")
# Sources only: a build copied under one of the folders is not where a pointer is kept.
_SUFFIXES = frozenset({"", ".py", ".sh", ".md", ".yml", ".yaml", ".toml", ".sql"})
_NAMED = re.compile(r"\btests/[\w/.-]+\.py(?:::\w+)*")


def _missing(reference: str) -> str | None:
    """Return why one ``tests/...py::name`` reference does not resolve, if it does not."""
    path, *names = reference.split("::")
    if not (ROOT / path).is_file():
        return f"{path} does not exist"
    source = (ROOT / path).read_text(encoding="utf-8")
    for name in names:
        if not re.search(rf"^\s*(?:async def|def|class) {re.escape(name)}\b", source, re.M):
            return f"{path} defines no {name}"
    return None


def _references() -> dict[str, list[str]]:
    """Map each named test to the files that name it."""
    found: dict[str, list[str]] = {}
    for folder in _FOLDERS:
        for path in sorted((ROOT / folder).rglob("*")):
            if path.suffix not in _SUFFIXES or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for reference in _NAMED.findall(text):
                found.setdefault(reference, []).append(path.relative_to(ROOT).as_posix())
    return found


def test_a_reference_resolves_only_to_an_existing_file_and_name() -> None:
    """Tell an existing test from a missing file and from a missing name."""
    here = "tests/scripts/test_named_tests.py"

    assert _missing(f"{here}::test_a_reference_resolves_only_to_an_existing_file_and_name") is None
    assert _missing("tests/scripts/test_gone.py") == "tests/scripts/test_gone.py does not exist"
    assert _missing(f"{here}::test_gone") == f"{here} defines no test_gone"


def test_every_test_named_by_a_script_or_module_exists() -> None:
    """Fail with each stale pointer and the file that holds it."""
    references = _references()
    assert references, "no named test was found; the scan is broken"

    stale = [
        f"{', '.join(sorted(set(holders)))}: {reason}"
        for reference, holders in sorted(references.items())
        if (reason := _missing(reference)) is not None
    ]

    assert not stale, "A test was moved or renamed without its pointers:\n" + "\n".join(stale)
