#!/usr/bin/env python3
"""Reflow Markdown prose onto one physical line per paragraph.

Markdown renders a line break inside a paragraph as a single space, so hard wrapping changes
nothing in the rendered document while it fights every soft-wrapping editor. This formatter
removes those breaks and copies every structural line verbatim: code fences, tables, headings,
HTML comments, thematic breaks, and indented code blocks are never touched.

Usage:
    uv run python scripts/format_docs.py                 # rewrite all of docs/
    uv run python scripts/format_docs.py --check         # list files that still need reflow
    uv run python scripts/format_docs.py docs/ko         # limit the run to one subtree
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path
import re
import sys

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TARGETS = ("docs",)

# A fence may be indented far past three spaces when it belongs to a nested list item, so the
# opening indent is unrestricted here and the closing line only has to repeat the marker.
FENCE = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t].*)?$")
THEMATIC = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
QUOTE = re.compile(r"^ {0,3}>[ \t]?(?P<body>.*)$")
BULLET = re.compile(r"^(?P<prefix>[ \t]*(?P<marker>[-*+])[ \t]+)(?P<body>.*)$")
ORDERED = re.compile(r"^(?P<prefix>[ \t]*(?P<number>\d{1,9})[.)][ \t]+)(?P<body>.*)$")
INDENTED_CODE = re.compile(r"^(?: {4,}|\t)")


class MarkdownFormatError(ValueError):
    """Report Markdown this formatter refuses to rewrite."""


def _is_table_row(line: str) -> bool:
    """Report whether a line belongs to a pipe table."""
    return line.lstrip().startswith("|")


def _is_verbatim(line: str) -> bool:
    """Report whether a line must survive byte for byte on its own output line."""
    stripped = line.lstrip()
    return (
        bool(HEADING.match(line))
        or bool(THEMATIC.match(line))
        or _is_table_row(line)
        or stripped.startswith("<!--")
    )


def _copy_fence(lines: list[str], start: int, out: list[str]) -> int:
    """Copy a fenced block verbatim and return the index after its closing line."""
    match = FENCE.match(lines[start])
    assert match is not None
    marker = match.group("marker")[0]
    length = len(match.group("marker"))
    close = re.compile(rf"^[ \t]*{re.escape(marker)}{{{length},}}[ \t]*$")
    out.append(lines[start])
    index = start + 1
    while index < len(lines):
        out.append(lines[index])
        if close.match(lines[index]):
            return index + 1
        index += 1
    raise MarkdownFormatError(f"unclosed {marker * length} code fence opened at line {start + 1}")


def _copy_quote(lines: list[str], start: int, out: list[str]) -> int:
    """Reflow one blockquote by formatting its stripped body and restoring the marker."""
    body: list[str] = []
    index = start
    while index < len(lines) and (match := QUOTE.match(lines[index])):
        body.append(match.group("body"))
        index += 1
    for line in _format_lines(body):
        out.append(f"> {line}".rstrip() if line else ">")
    return index


def _opens_list_item(line: str, inside_paragraph: bool) -> re.Match[str] | None:
    """Return the list marker match when a line starts a list item here."""
    bullet = BULLET.match(line)
    if bullet:
        return bullet
    ordered = ORDERED.match(line)
    if ordered and (not inside_paragraph or ordered.group("number") == "1"):
        return ordered
    return None


def _format_lines(lines: list[str]) -> list[str]:
    """Join every soft-wrapped prose line inside one block sequence."""
    out: list[str] = []
    pieces: list[str] = []
    prefix = ""
    open_block = False
    index = 0

    def flush() -> None:
        nonlocal pieces, prefix, open_block
        if open_block:
            out.append((prefix + " ".join(pieces)).rstrip())
        pieces = []
        prefix = ""
        open_block = False

    while index < len(lines):
        line = lines[index]
        if FENCE.match(line):
            flush()
            index = _copy_fence(lines, index, out)
            continue
        if not line.strip():
            flush()
            out.append("")
            index += 1
            continue
        if QUOTE.match(line):
            flush()
            index = _copy_quote(lines, index, out)
            continue
        if _is_verbatim(line):
            flush()
            out.append(line.rstrip())
            index += 1
            continue
        item = _opens_list_item(line, open_block)
        if item:
            flush()
            prefix = item.group("prefix")
            pieces = [item.group("body").strip()]
            open_block = True
            index += 1
            continue
        if not open_block and INDENTED_CODE.match(line):
            out.append(line.rstrip())
            index += 1
            continue
        if not open_block:
            prefix = line[: len(line) - len(line.lstrip())]
            open_block = True
        pieces.append(line.strip())
        index += 1

    flush()
    return out


def format_markdown(text: str) -> str:
    """Return the reflowed document for one Markdown source string."""
    ends_with_newline = text.endswith("\n")
    lines = text.split("\n")
    if ends_with_newline:
        lines.pop()
    formatted = "\n".join(_format_lines(lines))
    return f"{formatted}\n" if ends_with_newline else formatted


def iter_markdown(targets: tuple[str, ...]) -> Iterator[Path]:
    """Yield every Markdown file selected by the command-line targets."""
    seen: set[Path] = set()
    for target in targets:
        path = Path(target)
        if not path.is_absolute():
            path = REPO / path
        candidates = sorted(path.rglob("*.md")) if path.is_dir() else [path]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield candidate


def main(argv: list[str] | None = None) -> int:
    """Rewrite or verify the reflow of every selected Markdown file."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "targets", nargs="*", default=list(DEFAULT_TARGETS), help="files or directories"
    )
    parser.add_argument("--check", action="store_true", help="report instead of rewriting")
    args = parser.parse_args(argv)

    targets = tuple(args.targets) or DEFAULT_TARGETS
    changed: list[str] = []
    scanned = 0
    for path in iter_markdown(targets):
        original = path.read_text(encoding="utf-8")
        try:
            formatted = format_markdown(original)
        except MarkdownFormatError as error:
            print(f"{path}: {error}", file=sys.stderr)
            return 2
        scanned += 1
        if formatted == original:
            continue
        changed.append(str(path.relative_to(REPO) if path.is_relative_to(REPO) else path))
        if not args.check:
            path.write_text(formatted, encoding="utf-8")

    if args.check:
        for name in changed:
            print(f"{name}: paragraph is hard wrapped")
        print(f"Format check: {len(changed)} of {scanned} file(s) need reflow.")
        return 1 if changed else 0
    print(f"Formatted {len(changed)} of {scanned} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
