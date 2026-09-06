#!/usr/bin/env python3
"""Validate bilingual documentation inventory, structure, links, and language."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tomllib
from typing import Any
from urllib.parse import unquote, urlsplit

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO / "docs" / "localization.toml"
SCHEMA_VERSION = 1
REQUIRED_FIELDS = (
    "heading_levels",
    "code_fences",
    "inline_code",
    "link_shapes",
    "link_destinations",
    "table_shapes",
    "checkpoint_ids",
    "html_comments",
)
EXACT_PARITY_FIELDS = tuple(field for field in REQUIRED_FIELDS if field != "link_destinations")

FENCE_OPEN = re.compile(r"^(?P<indent> {0,3})(?P<marker>`{3,}|~{3,})(?P<info>.*)$")
HEADING = re.compile(r"^(#{1,6})[ \t]+(?P<title>\S.*)$")
INLINE_CODE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
LINK = re.compile(
    r"(?P<image>!)?\[(?P<label>[^\]]*)\]"
    r"\((?P<target>[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\)"
)
HTML_COMMENT = re.compile(r"<!--.*?-->", flags=re.DOTALL)
CHECKPOINT_ID = re.compile(r"(?<![A-Za-z0-9])M\d+(?:\.\d+)+(?![A-Za-z0-9])")
HANGUL = re.compile(r"[가-힣]")
ENGLISH_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
EXTERNAL_SCHEMES = {"http", "https", "mailto"}
KOREAN_TERMINOLOGY = {
    "provider": ("공급자", ("프로바이더", "제공자")),
    "ablation": ("어블레이션", ("절제", "제거 실험")),
}


class ParityConfigurationError(ValueError):
    """Report invalid localization metadata."""


class MarkdownStructureError(ValueError):
    """Report malformed Markdown that prevents deterministic comparison."""


@dataclass(frozen=True)
class LocalizationConfig:
    """Resolved localization roots and structural policy."""

    path: Path
    repository_root: Path
    canonical_root: Path
    manifest_path: Path
    locales: tuple[str, ...]
    reference_locale: str
    shared_roots: tuple[str, ...]
    locale_roots: dict[str, Path]
    required_fields: tuple[str, ...]


@dataclass(frozen=True)
class InventoryManifest:
    """Frozen relative paths for one localization inventory version."""

    version: str
    canonical_root: str
    locales: tuple[str, ...]
    documents: tuple[str, ...]


@dataclass(frozen=True)
class LinkDestination:
    """A translation-invariant link classification and document identity."""

    image: bool
    kind: str
    document: str
    has_fragment: bool


@dataclass(frozen=True)
class StructuralSignature:
    """Translation-invariant Markdown features."""

    heading_levels: tuple[int, ...]
    code_fences: tuple[tuple[str, int, str, int, int, str], ...]
    inline_code: tuple[str, ...]
    link_shapes: tuple[tuple[bool, str, bool], ...]
    link_destinations: tuple[LinkDestination, ...]
    table_shapes: tuple[tuple[int, tuple[str, ...], tuple[int, ...]], ...]
    checkpoint_ids: tuple[str, ...]
    html_comments: tuple[str, ...]


@dataclass(frozen=True, order=True)
class Issue:
    """One deterministic inventory, parity, or language failure."""

    path: str
    field: str
    message: str

    def render(self) -> str:
        """Render a stable one-line diagnostic."""

        return f"{self.path}: {self.field}: {self.message}"


def _require_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ParityConfigurationError(f"missing [{key}] table")
    return value


def _require_string(table: dict[str, Any], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ParityConfigurationError(f"{key} must be a non-empty string")
    return value


def _require_string_list(table: dict[str, Any], key: str) -> tuple[str, ...]:
    value = table.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ParityConfigurationError(f"{key} must be a non-empty string list")
    return tuple(value)


def _resolved_child(root: Path, relative: str, field: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise ParityConfigurationError(f"{field} must be relative")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ParityConfigurationError(f"{field} escapes its root")
    return resolved


def load_config(path: Path = DEFAULT_CONFIG) -> LocalizationConfig:
    """Load and validate the repository-relative TOML configuration."""

    resolved_path = path.resolve()
    try:
        raw = tomllib.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ParityConfigurationError(f"cannot load config {resolved_path}: {exc}") from exc

    localization = _require_table(raw, "localization")
    if localization.get("schema_version") != SCHEMA_VERSION:
        raise ParityConfigurationError(f"schema_version must be {SCHEMA_VERSION}")
    repository_value = Path(_require_string(localization, "repository_root"))
    if repository_value.is_absolute():
        raise ParityConfigurationError("repository_root must be relative")
    repository_root = (resolved_path.parent / repository_value).resolve()
    canonical_root = _resolved_child(
        repository_root, _require_string(localization, "canonical_root"), "canonical_root"
    )
    manifest_path = _resolved_child(
        repository_root, _require_string(localization, "manifest"), "manifest"
    )
    locales = _require_string_list(localization, "locales")
    if len(locales) != len(set(locales)) or tuple(sorted(locales)) != locales:
        raise ParityConfigurationError("locales must be unique and sorted")
    if any(not re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", locale) for locale in locales):
        raise ParityConfigurationError("locale names must use lowercase language tags")
    reference_locale = _require_string(localization, "reference_locale")
    if reference_locale not in locales:
        raise ParityConfigurationError("reference_locale must be one of locales")
    shared_roots = _require_string_list(localization, "shared_roots")
    if len(shared_roots) != len(set(shared_roots)) or tuple(sorted(shared_roots)) != shared_roots:
        raise ParityConfigurationError("shared_roots must be unique and sorted")
    if set(shared_roots) & set(locales):
        raise ParityConfigurationError("shared_roots must not overlap locales")
    if any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", root) for root in shared_roots):
        raise ParityConfigurationError("shared_roots must be safe top-level directory names")

    parity = _require_table(raw, "parity")
    required_fields = _require_string_list(parity, "required_fields")
    if required_fields != REQUIRED_FIELDS:
        raise ParityConfigurationError(
            "required_fields must match the checker contract exactly: " + ", ".join(REQUIRED_FIELDS)
        )
    return LocalizationConfig(
        path=resolved_path,
        repository_root=repository_root,
        canonical_root=canonical_root,
        manifest_path=manifest_path,
        locales=locales,
        reference_locale=reference_locale,
        shared_roots=shared_roots,
        locale_roots={locale: canonical_root / locale for locale in locales},
        required_fields=required_fields,
    )


def _validated_manifest_path(path: str, locales: tuple[str, ...]) -> str:
    pure = PurePosixPath(path)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ParityConfigurationError(f"invalid manifest path: {path!r}")
    if pure.suffix != ".md":
        raise ParityConfigurationError(f"manifest path is not Markdown: {path!r}")
    if pure.parts[0] in locales:
        raise ParityConfigurationError(f"localized path cannot contain a locale prefix: {path!r}")
    return pure.as_posix()


def load_manifest(config: LocalizationConfig) -> InventoryManifest:
    """Load and validate the frozen JSON inventory."""

    try:
        raw = json.loads(config.manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParityConfigurationError(
            f"cannot load manifest {config.manifest_path}: {exc}"
        ) from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ParityConfigurationError(f"manifest schema_version must be {SCHEMA_VERSION}")
    version = raw.get("inventory_version")
    canonical_root = raw.get("canonical_root")
    locales = raw.get("locales")
    documents = raw.get("documents")
    if not isinstance(version, str) or not version:
        raise ParityConfigurationError("inventory_version must be a non-empty string")
    expected_root = config.canonical_root.relative_to(config.repository_root).as_posix()
    if canonical_root != expected_root:
        raise ParityConfigurationError(f"manifest canonical_root must be {expected_root!r}")
    if locales != list(config.locales):
        raise ParityConfigurationError("manifest locales must match config locales")
    if not isinstance(documents, list) or not all(isinstance(item, str) for item in documents):
        raise ParityConfigurationError("documents must be a string list")
    validated = tuple(_validated_manifest_path(item, config.locales) for item in documents)
    if validated != tuple(sorted(validated)) or len(validated) != len(set(validated)):
        raise ParityConfigurationError("documents must be unique and sorted")
    if raw.get("document_count") != len(validated):
        raise ParityConfigurationError("document_count must equal the number of documents")
    return InventoryManifest(version, canonical_root, tuple(locales), validated)


def discover_markdown(root: Path) -> tuple[str, ...]:
    """Return sorted Markdown paths relative to a locale root."""

    if not root.is_dir():
        return ()
    return tuple(sorted(path.relative_to(root).as_posix() for path in root.rglob("*.md")))


def _outside_fences(text: str) -> tuple[str, tuple[tuple[str, int, str, int, int, str], ...]]:
    lines = text.splitlines()
    outside: list[str] = []
    fences: list[tuple[str, int, str, int, int, str]] = []
    marker = ""
    marker_length = 0
    info = ""
    body: list[str] = []
    for line in lines:
        if not marker:
            match = FENCE_OPEN.match(line)
            if match:
                marker = match.group("marker")[0]
                marker_length = len(match.group("marker"))
                info = match.group("info").strip()
                body = []
                outside.append("")
            else:
                outside.append(line)
            continue
        close = re.fullmatch(rf" {{0,3}}{re.escape(marker)}{{{marker_length},}}[ \t]*", line)
        if close:
            digest = sha256("\n".join(body).encode()).hexdigest()
            fences.append((marker, marker_length, info, len(line.strip()), len(body), digest))
            marker = ""
            marker_length = 0
            info = ""
            body = []
            outside.append("")
        else:
            body.append(line)
            outside.append("")
    if marker:
        raise MarkdownStructureError(f"unclosed {marker * marker_length} code fence")
    return "\n".join(outside), tuple(fences)


def _split_table_cells(line: str) -> tuple[str, ...]:
    stripped = line.strip()
    if "|" not in stripped:
        return ()
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    in_code = False
    for char in stripped:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            current.append(char)
            escaped = True
        elif char == "`":
            current.append(char)
            in_code = not in_code
        elif char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    if cells and not cells[0]:
        cells.pop(0)
    if cells and not cells[-1]:
        cells.pop()
    return tuple(cells)


def _separator_alignment(cell: str) -> str | None:
    value = cell.strip()
    if not re.fullmatch(r":?-{3,}:?", value):
        return None
    if value.startswith(":") and value.endswith(":"):
        return "center"
    if value.endswith(":"):
        return "right"
    if value.startswith(":"):
        return "left"
    return "default"


def _table_shapes(outside: str) -> tuple[tuple[int, tuple[str, ...], tuple[int, ...]], ...]:
    lines = outside.splitlines()
    shapes: list[tuple[int, tuple[str, ...], tuple[int, ...]]] = []
    index = 0
    while index + 1 < len(lines):
        header = _split_table_cells(lines[index])
        separator = _split_table_cells(lines[index + 1])
        alignments = tuple(_separator_alignment(cell) for cell in separator)
        if not header or not separator or any(value is None for value in alignments):
            index += 1
            continue
        rows = [len(header), len(separator)]
        cursor = index + 2
        while cursor < len(lines):
            cells = _split_table_cells(lines[cursor])
            if not cells:
                break
            rows.append(len(cells))
            cursor += 1
        shapes.append((len(header), tuple(value for value in alignments if value), tuple(rows)))
        index = cursor
    return tuple(shapes)


def _normalize_destination(
    relative_path: str, target: str, locales: tuple[str, ...] = ()
) -> LinkDestination:
    parsed = urlsplit(target.removeprefix("<").removesuffix(">"))
    image = False
    if parsed.scheme.lower() in EXTERNAL_SCHEMES:
        return LinkDestination(
            image,
            f"external:{parsed.scheme.lower()}",
            target,
            bool(parsed.fragment),
        )
    if parsed.path.startswith("/"):
        return LinkDestination(image, "absolute", unquote(parsed.path), bool(parsed.fragment))
    if not parsed.path:
        document = relative_path
        kind = "fragment"
    else:
        base = PurePosixPath(relative_path).parent
        parts: list[str] = []
        for part in (base / unquote(parsed.path)).parts:
            if part in {"", "."}:
                continue
            if part == "..":
                if parts:
                    parts.pop()
                else:
                    parts.append("..")
            else:
                parts.append(part)
        document = PurePosixPath(*parts).as_posix()
        kind = "relative"
    parts = PurePosixPath(document).parts
    if len(parts) >= 2 and parts[0] == ".." and parts[1] in locales:
        document = PurePosixPath(*parts[2:]).as_posix()
    return LinkDestination(image, kind, document, bool(parsed.fragment))


def _link_features(
    outside: str, relative_path: str, locales: tuple[str, ...] = ()
) -> tuple[tuple[tuple[bool, str, bool], ...], tuple[LinkDestination, ...]]:
    shapes: list[tuple[bool, str, bool]] = []
    destinations: list[LinkDestination] = []
    for match in LINK.finditer(outside):
        target = match.group("target")
        destination = _normalize_destination(relative_path, target, locales)
        destination = LinkDestination(
            bool(match.group("image")),
            destination.kind,
            destination.document,
            destination.has_fragment,
        )
        shapes.append((destination.image, destination.kind, destination.has_fragment))
        destinations.append(destination)
    return tuple(shapes), tuple(destinations)


def structural_signature(
    text: str,
    relative_path: str = "document.md",
    locales: tuple[str, ...] = (),
) -> StructuralSignature:
    """Extract features that translation must not alter."""

    outside, code_fences = _outside_fences(text)
    link_shapes, link_destinations = _link_features(outside, relative_path, locales)
    inline_code = tuple(INLINE_CODE.findall(outside))
    html_comments = tuple(comment.strip() for comment in HTML_COMMENT.findall(outside))
    heading_levels = tuple(
        len(match.group(1)) for line in outside.splitlines() if (match := HEADING.match(line))
    )
    return StructuralSignature(
        heading_levels=heading_levels,
        code_fences=code_fences,
        inline_code=inline_code,
        link_shapes=link_shapes,
        link_destinations=link_destinations,
        table_shapes=_table_shapes(outside),
        checkpoint_ids=tuple(CHECKPOINT_ID.findall(outside)),
        html_comments=html_comments,
    )


def check_inventory(config: LocalizationConfig, manifest: InventoryManifest) -> list[Issue]:
    """Require every locale tree to match the frozen inventory exactly."""

    issues: list[Issue] = []
    expected = set(manifest.documents)
    allowed_roots = set(config.locales) | set(config.shared_roots)
    for path in discover_markdown(config.canonical_root):
        top_level = PurePosixPath(path).parts[0]
        if path != "00-README.md" and top_level not in allowed_roots:
            issues.append(
                Issue(
                    path,
                    "inventory",
                    "Markdown document must live under a declared documentation root",
                )
            )
    for locale, root in config.locale_roots.items():
        actual = set(discover_markdown(root))
        for path in sorted(expected - actual):
            issues.append(Issue(path, "inventory", f"locale {locale!r} document is missing"))
        for path in sorted(actual - expected):
            issues.append(Issue(path, "inventory", f"locale {locale!r} has an extra document"))
        for path in sorted(actual & expected):
            try:
                structural_signature(
                    (root / path).read_text(encoding="utf-8"), path, config.locales
                )
            except (OSError, UnicodeError, MarkdownStructureError) as exc:
                issues.append(Issue(path, "markdown", f"cannot parse locale {locale!r}: {exc}"))
    return issues


def _signature_issues(
    relative_path: str,
    reference: StructuralSignature,
    candidate: StructuralSignature,
    fields: tuple[str, ...],
    locale: str,
) -> list[Issue]:
    return [
        Issue(relative_path, field, f"locale {locale!r} differs from English structural reference")
        for field in fields
        if getattr(reference, field) != getattr(candidate, field)
    ]


def check_parity(
    config: LocalizationConfig, manifest: InventoryManifest, locales: tuple[str, ...]
) -> list[Issue]:
    """Compare selected locale trees against the English structural reference."""

    issues = check_inventory(config, manifest)
    reference_root = config.locale_roots[config.reference_locale]
    for locale in locales:
        locale_root = config.locale_roots[locale]
        for relative_path in manifest.documents:
            reference_path = reference_root / relative_path
            candidate_path = locale_root / relative_path
            if not reference_path.is_file() or not candidate_path.is_file():
                continue
            try:
                reference = structural_signature(
                    reference_path.read_text(encoding="utf-8"), relative_path, config.locales
                )
                candidate = structural_signature(
                    candidate_path.read_text(encoding="utf-8"), relative_path, config.locales
                )
            except (OSError, UnicodeError, MarkdownStructureError) as exc:
                issues.append(
                    Issue(
                        relative_path,
                        "markdown",
                        f"cannot compare locale {locale!r}: {exc}",
                    )
                )
                continue
            issues.extend(
                _signature_issues(relative_path, reference, candidate, EXACT_PARITY_FIELDS, locale)
            )
            issues.extend(
                _signature_issues(
                    relative_path, reference, candidate, ("link_destinations",), locale
                )
            )
    return sorted(set(issues))


def _unprotected_prose(text: str) -> str:
    outside, _ = _outside_fences(text)
    outside = HTML_COMMENT.sub("", outside)
    outside = INLINE_CODE.sub("", outside)
    outside = LINK.sub(lambda match: match.group("label"), outside)
    return re.sub(r"(?:https?|mailto)://\S+", "", outside)


def _looks_like_untranslated_english(line: str) -> bool:
    stripped = line.strip().lstrip("#>*- ")
    if not stripped or HANGUL.search(stripped) or stripped.startswith(("|", "<")):
        return False
    words = ENGLISH_WORD.findall(stripped)
    return len(words) >= 12 and len(" ".join(words)) >= 70


def check_language(config: LocalizationConfig, manifest: InventoryManifest) -> list[Issue]:
    """Reject wrong-language prose and inconsistent Korean terminology."""

    issues: list[Issue] = []
    for relative_path in manifest.documents:
        en_path = config.locale_roots["en"] / relative_path
        ko_path = config.locale_roots["ko"] / relative_path
        if en_path.is_file():
            for line_number, line in enumerate(
                _unprotected_prose(en_path.read_text(encoding="utf-8")).splitlines(), 1
            ):
                if HANGUL.search(line):
                    issues.append(
                        Issue(
                            relative_path,
                            "language:en",
                            f"Hangul in prose at line {line_number}",
                        )
                    )
        if ko_path.is_file():
            prose = _unprotected_prose(ko_path.read_text(encoding="utf-8"))
            for line_number, line in enumerate(prose.splitlines(), 1):
                if _looks_like_untranslated_english(line):
                    issues.append(
                        Issue(
                            relative_path,
                            "language:ko",
                            f"possible untranslated English prose at line {line_number}",
                        )
                    )
            for concept, (preferred, rejected) in KOREAN_TERMINOLOGY.items():
                for term in rejected:
                    if term in prose:
                        issues.append(
                            Issue(
                                relative_path,
                                "terminology:ko",
                                f"use {preferred!r} for {concept!r}, not {term!r}",
                            )
                        )
    return sorted(set(issues))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inventory", help="check locale paths against the frozen manifest")
    parity = subparsers.add_parser("parity", help="compare complete localized trees")
    parity.add_argument("--locale", action="append", dest="locales")
    subparsers.add_parser("language", help="check English, Korean, and terminology gates")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one deterministic documentation gate."""

    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        manifest = load_manifest(config)
        selected_locales = config.locales
        if args.command == "inventory":
            issues = check_inventory(config, manifest)
        elif args.command == "language":
            issues = check_language(config, manifest)
        else:
            requested = tuple(args.locales or config.locales)
            if len(requested) != len(set(requested)):
                raise ParityConfigurationError("--locale values must be unique")
            unknown = sorted(set(requested) - set(config.locales))
            if unknown:
                raise ParityConfigurationError("unknown locales: " + ", ".join(unknown))
            selected_locales = requested
            issues = check_parity(config, manifest, requested)
    except (ParityConfigurationError, MarkdownStructureError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    if issues:
        for issue in issues:
            print(issue.render(), file=sys.stderr)
        print(
            f"{args.command.capitalize()} check failed with {len(issues)} issue(s).",
            file=sys.stderr,
        )
        return 1
    if args.command == "inventory":
        print(
            f"Inventory OK: {len(manifest.documents)} Markdown documents in each locale: "
            + ", ".join(config.locales)
            + "."
        )
    elif args.command == "language":
        print(f"Language OK: {len(manifest.documents)} English/Korean document pairs.")
    else:
        print(
            f"Parity OK: {len(manifest.documents)} documents for "
            + ", ".join(selected_locales)
            + "."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
