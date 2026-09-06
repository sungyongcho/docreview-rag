"""Deterministic tests for the bilingual documentation contract."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from tests.support import REPO

CHECKER = REPO / "scripts" / "check_doc_parity.py"

EN_DOCUMENT = """
# M8.1 English guide

Read the [details](guide.md#details) and the [reference](https://example.com/v1).
Run the protected command after the measured result.

| File | Count |
|---|---:|
| Source | 718 |

## Details

Use `scripts/check.py` for the protected command.

<!-- parity: keep -->

```bash
uv run python scripts/check.py --limit 718
```
"""

KO_DOCUMENT = """
# M8.1 한국어 안내서

[상세 설명](guide.md#상세-설명)과 [참고 자료](https://example.com/v1)를 읽는다.
실측 결과를 확인한 뒤 보호된 명령을 실행한다.

| 파일 | 개수 |
|---|---:|
| 출처 | 718개 |

## 상세 설명

보호된 명령은 `scripts/check.py`로 실행한다.

<!-- parity: keep -->

```bash
uv run python scripts/check.py --limit 718
```
"""


def _write_project(root: Path) -> Path:
    """Create a complete two-locale parity fixture."""

    docs = root / "docs"
    for locale, document in (("en", EN_DOCUMENT), ("ko", KO_DOCUMENT)):
        (docs / locale).mkdir(parents=True)
        (docs / locale / "guide.md").write_text(
            textwrap.dedent(document).lstrip(), encoding="utf-8"
        )
    manifest = {
        "schema_version": 1,
        "inventory_version": "test",
        "canonical_root": "docs",
        "locales": ["en", "ko"],
        "document_count": 1,
        "documents": ["guide.md"],
    }
    (docs / "localization-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    config = root / "localization.toml"
    config.write_text(
        textwrap.dedent(
            """
            [localization]
            schema_version = 1
            repository_root = "."
            canonical_root = "docs"
            manifest = "docs/localization-manifest.json"
            locales = ["en", "ko"]
            reference_locale = "en"
            shared_roots = ["project"]

            [parity]
            required_fields = [
              "heading_levels",
              "code_fences",
              "inline_code",
              "link_shapes",
              "link_destinations",
              "table_shapes",
              "checkpoint_ids",
              "html_comments",
            ]
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return config


def _run(config: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the parity CLI against one fixture."""

    return subprocess.run(
        [sys.executable, str(CHECKER), "--config", str(config), *args],
        cwd=config.parent,
        capture_output=True,
        text=True,
        check=False,
    )


def test_repository_manifest_freezes_every_localized_markdown_path() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER), "inventory"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Markdown documents in each locale" in result.stdout


def test_natural_translation_preserves_protected_structure(tmp_path: Path) -> None:
    config = _write_project(tmp_path)

    result = _run(config, "parity")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Parity OK: 1 documents for en, ko." in result.stdout


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        ("# M8.1 한국어 안내서", "## M8.1 한국어 안내서", "heading_levels"),
        ("--limit 718", "--limit 719", "code_fences"),
        ("`scripts/check.py`", "`scripts/other.py`", "inline_code"),
        ("https://example.com/v1", "mailto:docs@example.com", "link_shapes"),
        ("| 출처 | 718개 |", "| 출처 | 718개 | 추가 |", "table_shapes"),
        ("M8.1 한국어", "M8.2 한국어", "checkpoint_ids"),
        ("<!-- parity: keep -->", "<!-- parity: drop -->", "html_comments"),
    ],
)
def test_parity_reports_each_protected_field(
    tmp_path: Path, old: str, new: str, field: str
) -> None:
    config = _write_project(tmp_path)
    path = tmp_path / "docs" / "ko" / "guide.md"
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    result = _run(config, "parity", "--locale", "ko")

    assert result.returncode == 1
    assert f": {field}:" in result.stderr


def test_translated_fragment_may_change_when_document_identity_matches(tmp_path: Path) -> None:
    config = _write_project(tmp_path)

    result = _run(config, "parity")

    assert result.returncode == 0, result.stdout + result.stderr


def test_parity_rejects_different_document_destination(tmp_path: Path) -> None:
    config = _write_project(tmp_path)
    path = tmp_path / "docs" / "ko" / "guide.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("guide.md#상세-설명", "other.md#상세-설명"),
        encoding="utf-8",
    )

    result = _run(config, "parity")

    assert result.returncode == 1
    assert ": link_destinations:" in result.stderr


def test_inventory_rejects_unmanifested_locale_document(tmp_path: Path) -> None:
    config = _write_project(tmp_path)
    localized = tmp_path / "docs" / "en" / "new.md"
    localized.write_text("# New\n", encoding="utf-8")

    result = _run(config, "inventory")

    assert result.returncode == 1
    assert "locale 'en' has an extra document" in result.stderr

    localized.unlink()
    (tmp_path / "docs" / "legacy.md").write_text("# Legacy\n", encoding="utf-8")

    result = _run(config, "inventory")

    assert result.returncode == 1
    assert "Markdown document must live under a declared documentation root" in result.stderr


def test_inventory_allows_declared_shared_document_root(tmp_path: Path) -> None:
    config = _write_project(tmp_path)
    shared = tmp_path / "docs" / "project"
    shared.mkdir()
    (shared / "notes.md").write_text("# Shared project notes\n", encoding="utf-8")

    result = _run(config, "inventory")

    assert result.returncode == 0, result.stdout + result.stderr


def test_locale_parity_requires_the_complete_manifest_tree(tmp_path: Path) -> None:
    config = _write_project(tmp_path)
    (tmp_path / "docs" / "en" / "guide.md").unlink()

    result = _run(config, "parity", "--locale", "en")

    assert result.returncode == 1
    assert "locale 'en' document is missing" in result.stderr


def test_language_gate_rejects_hangul_in_english_prose(tmp_path: Path) -> None:
    config = _write_project(tmp_path)
    path = tmp_path / "docs" / "en" / "guide.md"
    path.write_text(path.read_text(encoding="utf-8") + "번역 누락\n", encoding="utf-8")

    result = _run(config, "language")

    assert result.returncode == 1
    assert ": language:en:" in result.stderr


def test_language_gate_rejects_long_english_prose_in_korean(tmp_path: Path) -> None:
    config = _write_project(tmp_path)
    path = tmp_path / "docs" / "ko" / "guide.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + (
            "This entire sentence remains untranslated and contains enough ordinary English "
            "words to trigger the deterministic Korean language audit.\n"
        ),
        encoding="utf-8",
    )

    result = _run(config, "language")

    assert result.returncode == 1
    assert ": language:ko:" in result.stderr


def test_language_gate_ignores_protected_code(tmp_path: Path) -> None:
    config = _write_project(tmp_path)

    result = _run(config, "language")

    assert result.returncode == 0, result.stdout + result.stderr
