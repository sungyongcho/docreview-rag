"""Deterministic tests for the Markdown reflow contract."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from tests.support import REPO

FORMATTER = REPO / "scripts" / "format_docs.py"

HARD_WRAPPED = """# M9 Fixture

Hand wrapping is invisible once the document is rendered, so this
break may be removed.

- A list item that continues on the next physical line keeps its own
  marker.
  - A nested item is its own block and never merges upward.

> A quoted callout is joined too, and the marker returns to the front
> of the joined line.
>
> A blank quote line still separates two quoted paragraphs.

| Column | Count |
|---|---:|
| Source | 718 |

<!-- src: app/ingestion/parser.py::segment_by_heading -->

```python
def segment_by_heading(  # this wrapped comment lives inside a fence
    document: str,
) -> list[str]:
    return []
```

1. A numbered step that owns an indented fence.

    ```bash
    uv run pytest -q
    ```

Trailing spaces disappear.\x20\x20
"""

REFLOWED = """# M9 Fixture

Hand wrapping is invisible once the document is rendered, so this break may be removed.

- A list item that continues on the next physical line keeps its own marker.
  - A nested item is its own block and never merges upward.

> A quoted callout is joined too, and the marker returns to the front of the joined line.
>
> A blank quote line still separates two quoted paragraphs.

| Column | Count |
|---|---:|
| Source | 718 |

<!-- src: app/ingestion/parser.py::segment_by_heading -->

```python
def segment_by_heading(  # this wrapped comment lives inside a fence
    document: str,
) -> list[str]:
    return []
```

1. A numbered step that owns an indented fence.

    ```bash
    uv run pytest -q
    ```

Trailing spaces disappear.
"""


def _run(*args: str, cwd: Path = REPO) -> subprocess.CompletedProcess[str]:
    """Run the formatter CLI and capture its result."""

    return subprocess.run(
        [sys.executable, str(FORMATTER), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_reflow_joins_prose_and_leaves_structure_untouched(tmp_path: Path) -> None:
    document = tmp_path / "fixture.md"
    document.write_text(HARD_WRAPPED, encoding="utf-8")

    result = _run(str(document), cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert document.read_text(encoding="utf-8") == REFLOWED


def test_reflow_is_idempotent(tmp_path: Path) -> None:
    document = tmp_path / "fixture.md"
    document.write_text(REFLOWED, encoding="utf-8")

    result = _run(str(document), cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert document.read_text(encoding="utf-8") == REFLOWED


def test_check_mode_reports_hard_wrapped_files_without_writing(tmp_path: Path) -> None:
    document = tmp_path / "fixture.md"
    document.write_text(HARD_WRAPPED, encoding="utf-8")

    result = _run("--check", str(document), cwd=tmp_path)

    assert result.returncode == 1
    assert "fixture.md" in result.stdout
    assert document.read_text(encoding="utf-8") == HARD_WRAPPED


def test_repository_documentation_stays_reflowed() -> None:
    result = _run("--check", "docs")

    assert result.returncode == 0, result.stdout + result.stderr
