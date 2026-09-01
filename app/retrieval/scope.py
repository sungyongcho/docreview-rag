"""Manifest-backed issuer aliases and deterministic query-scope resolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Literal
import unicodedata

from pydantic import BaseModel, ConfigDict

from app.ingestion.registry import registry_for, registry_name, resolve_registry
from app.retrieval.language import detect_query_languages
from app.retrieval.types import RetrievalFilters

CorpusScope = Literal["auto", "sec", "dart"]
ResolutionSource = Literal["explicit", "alias", "query_language"]


class QueryScopeError(ValueError):
    """One stable semantic conflict between a query and explicit scope."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class MatchedAlias(BaseModel):
    """One longest non-overlapping alias occurrence in normalized query text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alias: str
    issuer: str
    registry: str
    language: str


class ResolvedQueryScope(BaseModel):
    """Explain inferred, suppressed, and finally applied retrieval restrictions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: ResolutionSource
    matched_aliases: tuple[MatchedAlias, ...] = ()
    suppressed_aliases: tuple[MatchedAlias, ...] = ()
    inferred_issuers: tuple[str, ...] = ()
    inferred_registries: tuple[str, ...] = ()
    inferred_languages: tuple[str, ...] = ()
    filters: RetrievalFilters


@dataclass(frozen=True, slots=True)
class IssuerMetadata:
    """One registry-neutral issuer entry assembled from repeated filing metadata."""

    issuer: str
    registry: str
    language: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    """Display metadata for one manifest-backed filing document."""

    doc_id: str
    registry: str
    language: str
    issuer: str
    fiscal_year: int
    form: str


def _normalized(value: str) -> str:
    """Return a Unicode-compatible, case-insensitive alias comparison value."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _aliases(entry: Mapping[str, Any], *, owner: str) -> tuple[str, ...]:
    """Validate and canonicalize one manifest alias array."""
    raw = entry.get("aliases")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{owner} must define a nonempty aliases array")
    if not all(isinstance(alias, str) and alias.strip() for alias in raw):
        raise ValueError(f"{owner} aliases must be nonblank strings")
    by_normalized: dict[str, str] = {}
    for alias in raw:
        canonical = " ".join(alias.split())
        key = _normalized(canonical)
        if key in by_normalized:
            raise ValueError(f"{owner} aliases contain a normalized duplicate: {alias!r}")
        by_normalized[key] = canonical
    return tuple(by_normalized[key] for key in sorted(by_normalized))


def _issuer(entry: Mapping[str, Any]) -> str:
    """Return the canonical retrieval issuer used by one manifest adapter."""
    value = entry.get("issuer") or entry.get("ticker")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("manifest entry must name issuer or ticker")
    return value.strip()


def _fiscal_year(entry: Mapping[str, Any]) -> int:
    """Return an explicit or registry-adapter fiscal year."""
    value = entry.get("fiscal_year")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    report_date = entry.get("report_date")
    if isinstance(report_date, str) and report_date[:4].isdigit():
        return int(report_date[:4])
    raise ValueError("manifest entry must provide a fiscal year")


class ManifestScopeIndex:
    """Validated issuer aliases and document display data from corpus manifests."""

    def __init__(
        self,
        issuers: Sequence[IssuerMetadata],
        documents: Sequence[DocumentMetadata],
    ) -> None:
        self.issuers = tuple(sorted(issuers, key=lambda item: (item.registry, item.issuer)))
        self.documents = {document.doc_id: document for document in documents}
        alias_owners: dict[str, IssuerMetadata] = {}
        display_aliases: dict[str, str] = {}
        for issuer in self.issuers:
            for alias in issuer.aliases:
                key = _normalized(alias)
                owner = alias_owners.get(key)
                if owner is not None and (owner.registry, owner.issuer) != (
                    issuer.registry,
                    issuer.issuer,
                ):
                    raise ValueError(
                        f"normalized alias {alias!r} maps to both "
                        f"{owner.registry}:{owner.issuer} and {issuer.registry}:{issuer.issuer}"
                    )
                alias_owners[key] = issuer
                display_aliases[key] = alias
        self._alias_owners = alias_owners
        self._display_aliases = display_aliases

    @classmethod
    def from_entries(cls, entries: Iterable[Mapping[str, Any]]) -> ManifestScopeIndex:
        """Build an index while requiring identical aliases per canonical issuer."""
        issuers: dict[tuple[str, str], IssuerMetadata] = {}
        documents: list[DocumentMetadata] = []
        for position, raw in enumerate(entries):
            entry = dict(raw)
            registry = registry_name(entry)
            adapter = resolve_registry(entry)
            issuer = _issuer(entry)
            aliases = _aliases(entry, owner=f"manifest entry {position}")
            metadata = IssuerMetadata(
                issuer=issuer,
                registry=registry,
                language=adapter.language,
                aliases=aliases,
            )
            key = (registry, issuer)
            existing = issuers.get(key)
            if existing is not None and existing.aliases != aliases:
                raise ValueError(f"manifest aliases disagree for {registry}:{issuer}")
            issuers[key] = metadata
            documents.append(
                DocumentMetadata(
                    doc_id=adapter.doc_id(entry),
                    registry=registry,
                    language=adapter.language,
                    issuer=issuer,
                    fiscal_year=_fiscal_year(entry),
                    form=str(entry.get("form") or "10-K"),
                )
            )
        return cls(tuple(issuers.values()), documents)

    @classmethod
    def from_paths(cls, paths: Sequence[Path]) -> ManifestScopeIndex:
        """Load list-shaped UTF-8 manifests in caller order."""
        entries: list[Mapping[str, Any]] = []
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, list) or not all(
                isinstance(item, Mapping) for item in payload
            ):
                raise ValueError(f"manifest must hold a list of objects: {path}")
            entries.extend(payload)
        return cls.from_entries(entries)

    def issuer(self, registry: str, issuer: str) -> IssuerMetadata | None:
        """Return one canonical issuer when it exists in this corpus."""
        return next(
            (item for item in self.issuers if item.registry == registry and item.issuer == issuer),
            None,
        )

    def issuers_named(self, values: Sequence[str]) -> tuple[IssuerMetadata, ...]:
        """Resolve explicit canonical issuer values without accepting aliases."""
        wanted = set(values)
        return tuple(item for item in self.issuers if item.issuer in wanted)

    def match(self, query: str) -> tuple[MatchedAlias, ...]:
        """Return longest non-overlapping alias matches in query order."""
        normalized_query = _normalized(query)
        candidates: list[tuple[int, int, str, IssuerMetadata]] = []
        for key, owner in self._alias_owners.items():
            escaped = re.escape(key)
            ascii_words = all(
                character.isascii() and (character.isalnum() or character.isspace())
                for character in key
            )
            if ascii_words:
                pattern = rf"(?<![0-9a-z]){escaped}(?![0-9a-z])"
            else:
                pattern = escaped
            for occurrence in re.finditer(pattern, normalized_query):
                candidates.append((occurrence.start(), occurrence.end(), key, owner))
        selected: list[tuple[int, int, str, IssuerMetadata]] = []
        for candidate in sorted(candidates, key=lambda item: (-(item[1] - item[0]), item[0])):
            if any(candidate[0] < kept[1] and kept[0] < candidate[1] for kept in selected):
                continue
            selected.append(candidate)
        selected.sort(key=lambda item: item[0])
        return tuple(
            MatchedAlias(
                alias=self._display_aliases[key],
                issuer=owner.issuer,
                registry=owner.registry,
                language=owner.language,
            )
            for _start, _end, key, owner in selected
        )


def resolve_query_scope(
    query: str,
    index: ManifestScopeIndex,
    *,
    corpus_scope: CorpusScope = "auto",
    explicit_filters: RetrievalFilters | None = None,
) -> ResolvedQueryScope:
    """Resolve explicit settings, issuer aliases, and script fallback in precedence order."""
    if corpus_scope not in {"auto", "sec", "dart"}:
        raise ValueError("corpus_scope must be auto, sec, or dart")
    filters = explicit_filters or RetrievalFilters()
    matches = index.match(query)
    explicit_issuers = index.issuers_named(filters.issuers)
    if filters.issuers and len({item.issuer for item in explicit_issuers}) != len(filters.issuers):
        missing = sorted(set(filters.issuers) - {item.issuer for item in explicit_issuers})
        raise QueryScopeError("unknown_issuer", f"unknown issuer selection: {', '.join(missing)}")

    corpus_registry = () if corpus_scope == "auto" else (corpus_scope,)
    if explicit_issuers:
        registries = tuple(sorted({item.registry for item in explicit_issuers}))
        languages = tuple(sorted({item.language for item in explicit_issuers}))
        if corpus_registry and any(registry not in corpus_registry for registry in registries):
            raise QueryScopeError(
                "profile_scope_conflict",
                "selected issuers do not belong to the selected corpus",
            )
        suppressed = matches
        source: ResolutionSource = "explicit"
        issuers = filters.issuers
    elif matches:
        inferred = tuple({(match.registry, match.issuer, match.language) for match in matches})
        if corpus_registry and any(registry not in corpus_registry for registry, _, _ in inferred):
            raise QueryScopeError(
                "query_scope_conflict",
                "the query names an issuer outside the selected corpus",
            )
        registries = tuple(sorted({registry for registry, _, _ in inferred}))
        languages = tuple(sorted({language for _, _, language in inferred}))
        issuers = tuple(sorted({issuer for _, issuer, _ in inferred}))
        suppressed = ()
        source = "alias"
    else:
        registries = corpus_registry or filters.registries
        if filters.languages:
            languages = filters.languages
        elif corpus_registry:
            languages = tuple(registry_for(registry).language for registry in corpus_registry)
        else:
            languages = detect_query_languages(query)
        issuers = filters.issuers
        suppressed = ()
        source = "explicit" if corpus_registry or filters.languages else "query_language"

    final_registries = filters.registries or corpus_registry or registries
    final_languages = filters.languages or languages
    final_filters = filters.model_copy(
        update={
            "registries": final_registries,
            "languages": final_languages,
            "issuers": issuers,
        }
    )
    return ResolvedQueryScope(
        source=source,
        matched_aliases=matches,
        suppressed_aliases=suppressed,
        inferred_issuers=tuple(sorted(set(issuers))),
        inferred_registries=tuple(sorted(set(registries))),
        inferred_languages=tuple(sorted(set(languages))),
        filters=final_filters,
    )
