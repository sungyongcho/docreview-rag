#!/usr/bin/env python3
"""Synchronize copy-ready canonical implementation files into bilingual tutorials."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import subprocess
import tomllib

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO / "docs" / "project" / "tutorial-code.toml"
START = "<!-- complete-files:start -->"
END = "<!-- complete-files:end -->"


@dataclass(frozen=True)
class Group:
    """One checkpoint and the canonical files it introduces."""

    checkpoint: str
    files: tuple[str, ...]
    commands: tuple[str, ...]


@dataclass(frozen=True)
class Module:
    """One bilingual build tutorial and its ordered checkpoints."""

    slug: str
    groups: tuple[Group, ...]


@dataclass(frozen=True)
class Config:
    """Pinned reference and complete tutorial inventory."""

    revision: str
    modules: tuple[Module, ...]


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a string list")
    return tuple(value)


def load_config(path: Path = DEFAULT_CONFIG) -> Config:
    """Load and validate the tutorial source inventory."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    revision = raw.get("reference", {}).get("revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("reference.revision must be a full Git commit hash")
    modules: list[Module] = []
    seen_slugs: set[str] = set()
    seen_paths: set[str] = set()
    for module_raw in raw.get("modules", []):
        slug = module_raw.get("slug")
        if not isinstance(slug, str) or not re.fullmatch(r"m[0-9][a-z0-9-]+", slug):
            raise ValueError(f"invalid module slug: {slug!r}")
        if slug in seen_slugs:
            raise ValueError(f"duplicate module slug: {slug}")
        seen_slugs.add(slug)
        groups: list[Group] = []
        for group_raw in module_raw.get("groups", []):
            checkpoint = group_raw.get("id")
            if not isinstance(checkpoint, str) or not re.fullmatch(r"M\d+(?:\.\d+)+", checkpoint):
                raise ValueError(f"invalid checkpoint: {checkpoint!r}")
            files = _strings(group_raw.get("files"), f"{checkpoint}.files")
            commands = _strings(group_raw.get("commands"), f"{checkpoint}.commands")
            for relative in files:
                path = Path(relative)
                if path.is_absolute() or ".." in path.parts or relative.endswith("_mine.py"):
                    raise ValueError(f"unsafe or learner-copy path: {relative}")
                key = f"{slug}:{relative}"
                if key in seen_paths:
                    raise ValueError(f"duplicate tutorial file: {key}")
                seen_paths.add(key)
            validate_commands(checkpoint, commands)
            groups.append(Group(checkpoint, files, commands))
        modules.append(Module(slug, tuple(groups)))
    config = Config(revision, tuple(modules))
    validate_app_inventory(config)
    return config


def validate_commands(checkpoint: str, commands: tuple[str, ...]) -> None:
    """Reject stale, destructive, or non-canonical tutorial commands."""
    if not commands:
        raise ValueError(f"{checkpoint} must define at least one checkpoint command")
    for command in commands:
        if re.search(r"[가-힣]", command):
            raise ValueError(f"{checkpoint} command must be English: {command}")
        if "_mine.py" in command or re.search(r"\brm\s+-[a-zA-Z]*r", command):
            raise ValueError(f"{checkpoint} command is non-canonical or destructive: {command}")
        parts = shlex.split(command)
        if parts[:2] != ["uv", "run"]:
            raise ValueError(f"{checkpoint} command must use the locked uv environment: {command}")
        for token in parts:
            if not token.startswith(("tests/", "scripts/")):
                continue
            if not (REPO / token).exists():
                raise ValueError(f"{checkpoint} command path does not exist: {token}")


def validate_app_inventory(config: Config) -> None:
    """Require every canonical non-learner app file from the reference commit."""
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", config.revision, "--", "app"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    reference = {path for path in result.stdout.splitlines() if not path.endswith("_mine.py")}
    documented = {
        path
        for module in config.modules
        for group in module.groups
        for path in group.files
        if path.startswith("app/")
    }
    if reference != documented:
        missing = sorted(reference - documented)
        extra = sorted(documented - reference)
        raise ValueError(f"canonical app inventory mismatch: missing={missing}, extra={extra}")


def read_source(relative: str, revision: str) -> str:
    """Read a canonical file from the pinned completed-reference revision."""
    result = subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise FileNotFoundError(f"{relative} is absent at {revision[:8]}")
    return result.stdout.rstrip("\n")


def language_for(path: str) -> str:
    """Choose a readable Markdown fence language for a repository file."""
    name = Path(path).name
    suffix = Path(path).suffix
    if suffix == ".py":
        return "python"
    if suffix == ".toml":
        return "toml"
    if suffix == ".json":
        return "json"
    if suffix in {".yml", ".yaml"}:
        return "yaml"
    if suffix == ".sh":
        return "bash"
    if name == "Dockerfile":
        return "dockerfile"
    if name == ".dockerignore":
        return "gitignore"
    if name.endswith(".env.example"):
        return "dotenv"
    return "text"


def fence_for(text: str) -> str:
    """Choose a backtick fence longer than any run inside the source."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def render(module: Module, locale: str, revision: str) -> str:
    """Render the managed complete-file section for one locale."""
    if locale == "en":
        lines = [
            START,
            "## Reference baseline — the complete canonical files",
            "",
            (
                "Create or replace the canonical paths below directly. Do not create `_mine.py` or "
                "another learner-copy module. The earlier excerpts explain individual decisions; "
                "the blocks in this section are the finished files to compare against once a "
                "checkpoint is done. Preserve the shown type annotations and English comments; "
                "`pyproject.toml` is the authoritative Ruff policy."
            ),
        ]
    else:
        lines = [
            START,
            "## 완성 기준본 — 정식 구현 전체",
            "",
            (
                "아래 정식 경로를 직접 생성하거나 교체한다. `_mine.py` 또는 별도의 학습자용 복사 "
                "모듈을 만들지 않는다. 앞의 발췌 코드는 개별 결정을 설명하고, 이 절의 코드 블록은 "
                "체크포인트를 마친 뒤 대조할 완성 파일이다. 표시된 타입 어노테이션과 영어 주석을 "
                "유지하며 `pyproject.toml`을 Ruff 정책의 기준으로 사용한다."
            ),
        ]
    for group in module.groups:
        title = "Complete checkpoint" if locale == "en" else "완성 체크포인트"
        lines.extend(["", f"### {group.checkpoint} — {title}", ""])
        for relative in group.files:
            action = "Create or replace" if locale == "en" else "생성 또는 교체"
            source = read_source(relative, revision)
            fence = fence_for(source)
            lines.extend(
                [
                    f"#### {action} `{relative}`",
                    "",
                    f"<!-- file: {relative} -->",
                    f"{fence}{language_for(relative)}",
                ]
            )
            if source:
                lines.append(source)
            lines.extend([fence, ""])
        run = "Run the checkpoint:" if locale == "en" else "체크포인트를 실행한다."
        lines.extend([run, "", "```bash", *group.commands, "```", ""])
        if locale == "en":
            lines.extend(
                [
                    (
                        "**Expected:** every selected offline test passes. A declared integration "
                        "test may skip only when its external service is unavailable."
                    ),
                    "",
                    (
                        "**Stop:** do not continue if a test fails or skips because a required "
                        "symbol is missing."
                    ),
                    "",
                    (
                        "**Debug:** rerun the same pytest target with `-vv --tb=long`, then fix "
                        "the first failing contract before continuing."
                    ),
                ]
            )
        else:
            lines.extend(
                [
                    (
                        "**예상 결과:** 선택한 모든 오프라인 테스트가 통과한다. 명시된 통합 "
                        "테스트는 외부 서비스를 사용할 수 없을 때만 건너뛸 수 있다."
                    ),
                    "",
                    (
                        "**중단 조건:** 테스트가 실패하거나 필수 정식 심볼이 없어서 건너뛰면 "
                        "진행하지 않는다."
                    ),
                    "",
                    (
                        "**디버깅:** 같은 pytest 대상을 `-vv --tb=long`으로 다시 실행하고 첫 "
                        "번째로 실패한 계약을 고친 뒤 진행한다."
                    ),
                ]
            )
    lines.extend(["", END])
    return "\n".join(lines)


def replace_managed(document: Path, rendered: str) -> bool:
    """Append or replace the generated complete-file section."""
    text = document.read_text(encoding="utf-8")
    if START in text or END in text:
        if text.count(START) != 1 or text.count(END) != 1:
            raise ValueError(f"malformed managed section: {document}")
        before, rest = text.split(START, 1)
        _, after = rest.split(END, 1)
        updated = before.rstrip() + "\n\n" + rendered + after
    else:
        updated = text.rstrip() + "\n\n" + rendered + "\n"
    if updated == text:
        return False
    document.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    """Check or update every managed bilingual tutorial section."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when generated sections are stale",
    )
    args = parser.parse_args()
    config = load_config()
    stale: list[Path] = []
    for module in config.modules:
        for locale in ("en", "ko"):
            document = REPO / "docs" / locale / module.slug / "03-build.md"
            rendered = render(module, locale, config.revision)
            current = document.read_text(encoding="utf-8")
            if START in current and END in current:
                before, rest = current.split(START, 1)
                _, after = rest.split(END, 1)
                expected = before.rstrip() + "\n\n" + rendered + after
            else:
                expected = current.rstrip() + "\n\n" + rendered + "\n"
            if expected == current:
                continue
            stale.append(document)
            if not args.check:
                replace_managed(document, rendered)
    if args.check and stale:
        for path in stale:
            print(f"stale tutorial code: {path.relative_to(REPO)}")
        return 1
    verb = "Checked" if args.check else "Updated"
    print(f"{verb} {len(config.modules) * 2} bilingual build tutorials.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
