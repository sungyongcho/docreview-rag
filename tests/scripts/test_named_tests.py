"""Check repository-relative test paths named in code, workflows, config and guides.

Release scripts and contributor instructions can keep a stale path after a test
moves. Scan the runtime and tooling trees, GitHub workflows, root instructions
and configuration, and project docs. The tutorials currently use no illustrative
test paths, so include them to catch stale runnable examples as well. A path that
starts with ``web/`` keeps that prefix when checked.
"""

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
_FOLDERS = ("app", "scripts", "deploy", "docker", ".githooks", ".github", "docs")
# Sources only: a build copied under one of the folders is not where a pointer is kept.
_SUFFIXES = frozenset({"", ".py", ".sh", ".md", ".yml", ".yaml", ".toml", ".sql"})
_NAMED = re.compile(
    r"(?<![\w./-])(?:\./)?"
    r"((?:web/)?tests/[\w/.-]+\.py(?:::\w+)*|web/[\w/.-]+\.(?:test|spec)\.[cm]?[jt]sx?)"
    r"(?![\w/-]|\.[\w.-])"
)


def _missing(reference: str) -> str | None:
    """Require the named test file and any pytest selectors it carries."""
    path, *names = reference.split("::")
    if not (ROOT / path).is_file():
        return f"{path} does not exist"
    if names:
        source = (ROOT / path).read_text(encoding="utf-8")
        for name in names:
            if not re.search(rf"^\s*(?:async def|def|class) {re.escape(name)}\b", source, re.M):
                return f"{path} defines no {name}"
    return None


def _references() -> dict[str, list[str]]:
    """Map each named test to the files that name it."""
    sources = [ROOT / "AGENTS.md", ROOT / "pyproject.toml", *ROOT.glob("README*")]
    for folder in _FOLDERS:
        sources.extend((ROOT / folder).rglob("*"))

    found: dict[str, list[str]] = {}
    for path in sorted(sources):
        if (
            path.name.startswith(".env")
            or path.suffix not in _SUFFIXES
            or path.is_symlink()
            or not path.is_file()
        ):
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


def test_root_guides_workflows_and_tutorials_are_scanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report a reference from every location that maintains test instructions."""
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    reference = "tests/test_moved.py::test_example"
    holders = [
        ".github/workflows/verify.yml",
        "AGENTS.md",
        "README.en.md",
        "docs/TUTORIAL/en/verify.md",
        "pyproject.toml",
    ]
    for holder in holders:
        path = tmp_path / holder
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"pytest {reference}\n", encoding="utf-8")

    assert _references().get(reference) == holders
    assert _missing(reference) == "tests/test_moved.py does not exist"


def test_web_test_references_keep_their_own_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A web-prefixed reference can only resolve inside the web tree."""
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    guide = tmp_path / "scripts/README.md"
    guide.parent.mkdir()
    reference = "web/tests/test_browser.py::test_preview"
    vitest = "web/components/preview.test.tsx"
    guide.write_text(f"Run {reference} and ./{vitest}.\n", encoding="utf-8")
    backend = tmp_path / "tests/test_browser.py"
    backend.parent.mkdir()
    backend.write_text("def test_preview(): pass\n", encoding="utf-8")

    assert _references() == {reference: ["scripts/README.md"], vitest: ["scripts/README.md"]}
    assert _missing(reference) == "web/tests/test_browser.py does not exist"
    assert _missing(vitest) == f"{vitest} does not exist"
    web = tmp_path / "web/tests/test_browser.py"
    web.parent.mkdir(parents=True)
    web.write_text(backend.read_text(encoding="utf-8"), encoding="utf-8")
    assert _missing(reference) is None


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
