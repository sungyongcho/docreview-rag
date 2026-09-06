#!/usr/bin/env python3
"""Check source-linked code blocks, constants, and local Markdown links.

Source markers identify Python symbols rather than line numbers, so documentation remains
stable when unrelated code moves. Local links are checked against the complete document set,
including locale-specific translated heading anchors.

    <!-- src: app/ingestion/parser.py::segment_by_heading -->
    ```python
    def segment_by_heading(...):
        ...
    ```

Multiple comma-separated symbols select one contiguous source span:

    <!-- src: app/ingestion/parser.py::CANONICAL,ORDER,PART_OF -->

Usage:
    uv run python scripts/check_doc_code.py                 # all of docs/
    uv run python scripts/check_doc_code.py docs/en/m1-1-parser/03-build.md
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
import tomllib

REPO = Path(__file__).resolve().parent.parent
# Scan all documentation so new milestone directories cannot silently escape verification.
DEFAULT_TARGETS = ["docs"]
LEARNING_CONFIG = REPO / "docs" / "project" / "learning.toml"

# A symbol marker must be followed by a Python fence. A complete-file marker may use
# any fenced language because tutorials also reproduce Docker and configuration files.
SYMBOL_MARKER = re.compile(
    r"^[ \t]*<!--[ \t]*src:[ \t]*(?P<path>[^\s:]+)::(?P<symbols>[\w, ]+?)[ \t]*-->[ \t]*$"
)
FILE_MARKER = re.compile(r"^[ \t]*<!--[ \t]*file:[ \t]*(?P<path>[^\s]+?)[ \t]*-->[ \t]*$")
FENCE_OPEN = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})(?P<info>[^`~\s]*)[ \t]*$")

# Prose threshold convention: `CONSTANT_NAME` followed by a numeric value and unit.
PROSE_CONST = re.compile(
    r"`(?P<name>[A-Z][A-Z0-9_]{2,})`\s*\(\s*(?P<value>\d+(?:\.\d+)?)\s*(?:자|개|블록|줄|행|회|pt|%|\))"
)
# Modules whose top-level constants may be referenced in prose.
CONST_SOURCES = [
    "app/ingestion/parser.py",
    "app/ingestion/xref.py",
    "app/ingestion/tables.py",
    "app/ingestion/chunk.py",
]

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def slugify(heading: str) -> str:
    """Apply the GitHub-style heading anchor rules used by this repository."""
    s = re.sub(r"`|\*\*|\*|★|⚠", "", heading).strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s", "-", s)


@dataclass
class Mismatch:
    """One documentation mismatch with its source location and diagnostic."""

    doc: Path
    line: int
    ref: str
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class DocumentationConfig:
    """Source policy for documentation code blocks."""

    allow_missing_sources: bool = False
    reference_revision: str | None = None


@dataclass(frozen=True)
class SourceMarker:
    """One source-linked documentation marker."""

    path: str
    symbols: tuple[str, ...] | None


def documentation_config() -> DocumentationConfig:
    """Load the pinned-reference source policy for the learning branch."""
    if not LEARNING_CONFIG.exists():
        return DocumentationConfig()
    raw = tomllib.loads(LEARNING_CONFIG.read_text(encoding="utf-8"))
    documentation = raw.get("documentation", {})
    revision = documentation.get("reference_revision")
    if revision is not None and not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("documentation.reference_revision must be a full Git commit hash")
    return DocumentationConfig(
        allow_missing_sources=documentation.get("allow_missing_sources") is True,
        reference_revision=revision,
    )


def parse_marker(line: str) -> SourceMarker | None:
    """Parse a symbol excerpt or complete-file marker."""
    if match := SYMBOL_MARKER.match(line):
        symbols = tuple(s.strip() for s in match.group("symbols").split(",") if s.strip())
        return SourceMarker(match.group("path"), symbols)
    if match := FILE_MARKER.match(line):
        return SourceMarker(match.group("path"), None)
    return None


def source_text(path: Path, reference_revision: str | None) -> tuple[str | None, str]:
    """Read the pinned reference when configured, otherwise the local file."""
    if reference_revision is not None:
        try:
            relative = path.relative_to(REPO).as_posix()
        except ValueError:
            return None, f"source path escapes repository: {path}"
        result = subprocess.run(
            ["git", "show", f"{reference_revision}:{relative}"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None, f"file not found at {reference_revision[:8]}: {relative}"
        return result.stdout, ""
    if path.exists():
        return path.read_text(encoding="utf-8"), ""
    return None, f"file not found: {path}"


def symbol_span(tree: ast.Module, name: str) -> tuple[int, int] | None:
    """Return a top-level symbol span, including decorators."""
    for node in tree.body:
        match node:
            case ast.FunctionDef(name=n) | ast.AsyncFunctionDef(name=n) | ast.ClassDef(name=n):
                if n != name:
                    continue
                start = node.lineno
                if node.decorator_list:
                    start = min(start, min(d.lineno for d in node.decorator_list))
                return start, node.end_lineno
            case ast.Assign(targets=targets):
                if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                    return node.lineno, node.end_lineno
            case ast.AnnAssign(target=ast.Name(id=n)) if n == name:
                return node.lineno, node.end_lineno
            case ast.TypeAlias(name=ast.Name(id=n)) if n == name:
                return node.lineno, node.end_lineno
    return None


def source_for(
    path: Path,
    symbols: tuple[str, ...] | None,
    reference_revision: str | None,
) -> tuple[str | None, str]:
    """Return a complete file or one contiguous top-level symbol span."""
    text, error = source_text(path, reference_revision)
    if text is None:
        return None, error
    if symbols is None:
        return text, ""
    tree = ast.parse(text)

    spans = []
    for name in symbols:
        span = symbol_span(tree, name)
        if span is None:
            return None, f"{path.name} has no top-level symbol `{name}`"
        spans.append(span)

    lines = text.splitlines()
    lo = min(s for s, _ in spans)
    hi = max(e for _, e in spans)
    return "\n".join(lines[lo - 1 : hi]), ""


def normalize(code: str) -> str:
    """Normalize only trailing whitespace and final blank lines."""
    return "\n".join(line.rstrip() for line in code.strip("\n").splitlines())


def opening_fence(line: str) -> tuple[str, str] | None:
    """Return the exact fence token and language, if this line opens a fence."""
    if match := FENCE_OPEN.match(line):
        return match.group("fence"), match.group("info")
    return None


def outside_fence_lines(lines: list[str]) -> Iterator[tuple[int, str]]:
    """Yield line numbers and prose while respecting variable-length Markdown fences."""
    active: str | None = None
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if active is not None:
            if stripped == active:
                active = None
            continue
        if opened := opening_fence(line):
            active = opened[0]
            continue
        yield number, line


def load_constants(reference_revision: str | None) -> dict[str, float]:
    """Load top-level numeric constants from the configured documentation source."""
    out: dict[str, float] = {}
    for rel in CONST_SOURCES:
        text, _error = source_text(REPO / rel, reference_revision)
        if text is None:
            continue
        for node in ast.parse(text).body:
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.isupper()
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, int | float)
                and not isinstance(node.value.value, bool)
            ):
                out[node.targets[0].id] = node.value.value
    return out


def check_prose(doc: Path, constants: dict[str, float]) -> tuple[int, list[Mismatch]]:
    """Check prose values adjacent to known constant names."""
    checked, problems = 0, []
    lines = doc.read_text(encoding="utf-8").splitlines()
    for n, line in outside_fence_lines(lines):
        for m in PROSE_CONST.finditer(line):
            name, value = m.group("name"), float(m.group("value"))
            if name not in constants:
                continue
            checked += 1
            if constants[name] != value:
                problems.append(
                    Mismatch(
                        doc,
                        n,
                        name,
                        "prose value differs from source constant",
                        f"      document: {m.group('value')}   source: {constants[name]}",
                    )
                )
    return checked, problems


def anchors_of(doc: Path) -> set[str]:
    """Return anchors exposed by a document, including duplicate suffixes."""
    seen: dict[str, int] = {}
    out: set[str] = set()
    lines = doc.read_text(encoding="utf-8").splitlines()
    for _, line in outside_fence_lines(lines):
        if m := HEADING.match(line):
            base = slugify(m.group(2))
            n = seen.get(base, 0)
            seen[base] = n + 1
            out.add(base if n == 0 else f"{base}-{n}")
    return out


def check_links(docs: list[Path]) -> tuple[int, list[Mismatch]]:
    """Check local document targets and heading fragments."""
    # Key by path because duplicate filenames exist across milestone directories.
    # A filename-only key can hide a valid anchor or produce a false pass against
    # an anchor from the wrong document.
    anchors = {d.resolve(): anchors_of(d) for d in docs}
    checked, problems = 0, []
    for doc in docs:
        lines = doc.read_text(encoding="utf-8").splitlines()
        for n, line in outside_fence_lines(lines):
            for m in MD_LINK.finditer(line):
                target = m.group(1)
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path, _, frag = target.partition("#")
                checked += 1
                if path:
                    resolved = (doc.parent / path).resolve()
                    if not resolved.exists():
                        problems.append(Mismatch(doc, n, target, "linked file does not exist"))
                        continue
                    key = resolved
                else:
                    key = doc.resolve()
                if frag and key in anchors and frag not in anchors[key]:
                    near = [a for a in anchors[key] if a.startswith(frag[:12])]
                    problems.append(
                        Mismatch(
                            doc,
                            n,
                            target,
                            "linked anchor does not exist",
                            f"      similar: {near[0]}" if near else "",
                        )
                    )
    return checked, problems


def check_doc(doc: Path, *, config: DocumentationConfig) -> tuple[int, int, list[Mismatch]]:
    """Return the checked source-block count and mismatches."""
    lines = doc.read_text(encoding="utf-8").splitlines()
    checked, deferred, problems = 0, 0, []

    i = 0
    while i < len(lines):
        marker = parse_marker(lines[i])
        if not marker:
            i += 1
            continue

        symbol_label = ",".join(marker.symbols) if marker.symbols is not None else "*"
        ref = f"{marker.path}::{symbol_label}"
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        opened = opening_fence(lines[j]) if j < len(lines) else None
        if opened is None:
            problems.append(Mismatch(doc, i + 1, ref, "source marker lacks a code fence"))
            i += 1
            continue
        fence, info = opened
        if marker.symbols is not None and info not in {"python", "py"}:
            problems.append(Mismatch(doc, i + 1, ref, "symbol marker requires a Python fence"))
            i += 1
            continue

        k = j + 1
        while k < len(lines) and lines[k].strip() != fence:
            k += 1
        if k >= len(lines):
            problems.append(Mismatch(doc, i + 1, ref, "unclosed code fence"))
            break

        in_doc = "\n".join(lines[j + 1 : k])
        source_path = REPO / marker.path
        actual, err = source_for(source_path, marker.symbols, config.reference_revision)

        if actual is None and config.allow_missing_sources and not source_path.exists():
            deferred += 1
        elif actual is None:
            checked += 1
            problems.append(Mismatch(doc, i + 1, ref, err))
        else:
            checked += 1
            if normalize(in_doc) != normalize(actual):
                problems.append(
                    Mismatch(
                        doc,
                        i + 1,
                        ref,
                        "documented code differs from source",
                        diff(in_doc, actual),
                    )
                )
        i = k + 1

    return checked, deferred, problems


def diff(in_doc: str, actual: str) -> str:
    """Render only the first differing line."""
    a, b = normalize(in_doc).splitlines(), normalize(actual).splitlines()
    for n, (x, y) in enumerate(zip(a, b, strict=False), 1):
        if x != y:
            return f"      line {n}\n        document: {x!r}\n        source: {y!r}"
    if len(a) != len(b):
        longer, who = (a, "document") if len(a) > len(b) else (b, "source")
        first = longer[min(len(a), len(b))]
        return (
            f"      length differs (document {len(a)} lines / source {len(b)} lines); "
            f"first line only in {who}: {first!r}"
        )
    return ""


def collect(targets: list[str]) -> list[Path]:
    """Collect Markdown paths from repository-relative or current-directory targets."""
    out: list[Path] = []
    for t in targets:
        p = Path(t)
        if not p.exists():
            p = REPO / t
        out.extend(sorted(p.rglob("*.md")) if p.is_dir() else [p.resolve()])
    return list(dict.fromkeys(out))


def fix_doc(doc: Path, *, config: DocumentationConfig) -> int:
    """Replace source-marked code fences with the configured documentation source."""
    lines = doc.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    replaced = 0

    i = 0
    while i < len(lines):
        marker = parse_marker(lines[i])
        out.append(lines[i])
        if not marker:
            i += 1
            continue

        j = i + 1
        while j < len(lines) and not lines[j].strip():
            out.append(lines[j])
            j += 1
        opened = opening_fence(lines[j]) if j < len(lines) else None
        if opened is None:
            i = j
            continue
        fence, _ = opened

        k = j + 1
        while k < len(lines) and lines[k].strip() != fence:
            k += 1
        if k >= len(lines):
            out.extend(lines[j:])
            break

        actual, err = source_for(
            REPO / marker.path,
            marker.symbols,
            config.reference_revision,
        )
        if actual is None:
            print(f"  ⚠ {doc.name}:{i + 1} {err} — 건너뜀")
            out.extend(lines[j : k + 1])
        else:
            out.append(lines[j])
            out.extend(normalize(actual).splitlines())
            out.append(lines[k])  # ```
            replaced += 1
        i = k + 1

    doc.write_text("\n".join(out) + "\n", encoding="utf-8")
    return replaced


def main(argv: list[str]) -> int:
    """Check or refresh documentation targets selected by command-line arguments."""
    args = [a for a in argv[1:] if not a.startswith("-")]
    docs = collect(args or DEFAULT_TARGETS)
    config = documentation_config()

    if "--fix" in argv:
        total = sum(fix_doc(d, config=config) for d in docs)
        print(f"Updated {total} source-linked code block(s).")
        return 0

    constants = load_constants(config.reference_revision)
    n_blocks = n_deferred = n_prose = 0
    all_problems = []
    for doc in docs:
        checked, deferred, problems = check_doc(doc, config=config)
        n_blocks += checked
        n_deferred += deferred
        all_problems += problems
        checked, problems = check_prose(doc, constants)
        n_prose += checked
        all_problems += problems

    n_links, link_problems = check_links(docs)
    all_problems += link_problems

    def rel(p: Path) -> str:
        return str(p.relative_to(REPO)) if p.is_relative_to(REPO) else str(p)

    if all_problems:
        print(
            f"Documentation check failed with {len(all_problems)} issue(s) "
            f"({n_blocks} verified source blocks, {n_deferred} deferred source blocks, "
            f"{n_prose} prose constants, {n_links} links).\n"
        )
        for p in all_problems:
            print(f"  {rel(p.doc)}:{p.line}  {p.ref}")
            print(f"    {p.reason}")
            if p.detail:
                print(p.detail)
            print()
        return 1

    if n_blocks + n_deferred == 0:
        print("No source-linked code blocks were found.")
        return 1

    print(
        f"Documentation OK: {n_blocks} verified source blocks, "
        f"{n_deferred} deferred source blocks, {n_prose} prose constants, "
        f"{n_links} links across {len(docs)} documents."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
