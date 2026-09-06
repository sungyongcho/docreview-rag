"""Keep pinned-reference code blocks, constants, and links synchronized."""

from pathlib import Path
import subprocess
import sys

from scripts.sync_tutorial_code import load_config, read_source
from tests.support import REPO

CHECKER = REPO / "scripts" / "check_doc_code.py"
TUTORIAL_SYNC = REPO / "scripts" / "sync_tutorial_code.py"
TARGETS = (
    "README.md",
    "docs",
    "deploy/huggingface/README.md",
)


def test_doc_code_blocks_match_reference() -> None:
    """Every source-linked block resolves to the pinned completed reference."""
    r = subprocess.run(
        [sys.executable, str(CHECKER), *TARGETS],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, "\n" + r.stdout + r.stderr
    assert "0 deferred source blocks" in r.stdout


def test_complete_file_marker_uses_pinned_reference(tmp_path: Path) -> None:
    """A local learner implementation never replaces the complete-file reference."""
    source = subprocess.run(
        ["git", "show", "c70011314d405e4be3e865bc0b75a3c7db01d3e7:app/ingestion/tables.py"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.rstrip()
    document = tmp_path / "complete-file.md"
    document.write_text(
        f"# Complete file\n\n<!-- file: app/ingestion/tables.py -->\n```python\n{source}\n```\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(document)],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 verified source blocks, 0 deferred source blocks" in result.stdout


def test_tutorial_source_uses_pinned_reference() -> None:
    """Complete-file generation reads the configured revision, not learner code."""
    config = load_config()
    result = subprocess.run(
        ["git", "show", f"{config.revision}:app/ingestion/tables.py"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )

    assert read_source("app/ingestion/tables.py", config.revision) == result.stdout.rstrip()


def test_complete_tutorial_sections_are_current() -> None:
    """Managed bilingual complete-file sections match their pinned inputs."""
    result = subprocess.run(
        [sys.executable, str(TUTORIAL_SYNC), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Checked 24 bilingual build tutorials" in result.stdout
