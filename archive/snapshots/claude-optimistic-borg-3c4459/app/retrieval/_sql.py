"""Shared SQL construction for retrieval strategies."""

from typing import Any

from sqlalchemy import Select, SQLColumnExpression, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Chunk, Document, SnapshotChunk
from app.retrieval.types import RetrievalFilters

TIE_BREAK_COLLATION = "C"
TEXT_SEARCH_CONFIG = "english"
type ChunkSource = type[Chunk] | type[SnapshotChunk]


def websearch_tokens(query: str) -> tuple[str, ...]:
    """Split web-search input on unquoted whitespace without rejecting malformed quotes."""
    tokens: list[str] = []
    start = 0
    length = len(query)
    while start < length:
        while start < length and query[start].isspace():
            start += 1
        if start == length:
            break

        end = start
        quoted = False
        while end < length:
            character = query[end]
            if character == '"':
                quoted = not quoted
            elif character.isspace() and not quoted:
                break
            end += 1
        tokens.append(query[start:end])
        start = end
    return tuple(tokens)


def positive_websearch_text(query: str) -> str:
    """Return only positive operands for lexical score-term extraction."""
    terms = tuple(token for token in websearch_tokens(query) if token.casefold() != "or")
    return " ".join(token for token in terms if not (token.startswith("-") and len(token) > 1))


def relaxed_websearch_query(query: str) -> str:
    """Build one relaxed web-search expression from raw query text.

    Parameters
    ----------
    query : str
        Raw web-search text containing terms, phrases, OR tokens, or exclusions.

    Returns
    -------
    str
        Expression with positive operands ORed and exclusions distributed.

    Notes
    -----
    Quoted phrases remain intact, and PostgreSQL parses the final expression only once.
    """
    terms = tuple(token for token in websearch_tokens(query) if token.casefold() != "or")
    positives = tuple(token for token in terms if not (token.startswith("-") and len(token) > 1))
    exclusions = tuple(token for token in terms if token.startswith("-") and len(token) > 1)
    if not positives:
        return query

    suffix = f" {' '.join(exclusions)}" if exclusions else ""
    return " OR ".join(f"{positive}{suffix}" for positive in positives)


def filter_predicates(
    filters: RetrievalFilters, source: ChunkSource = Chunk
) -> tuple[ColumnElement[bool], ...]:
    """Translate shared exact-match filters to composable SQL predicates.

    Parameters
    ----------
    filters : RetrievalFilters
        Canonical chunk and document restrictions.

    Returns
    -------
    tuple[ColumnElement[bool], ...]
        Predicates combined with AND by the caller.

    Notes
    -----
    Issuer, fiscal-year, and form predicates require a ``Document`` join; Item values
    and ``None`` are alternatives within one filter dimension.
    """
    predicates: list[ColumnElement[bool]] = []
    if filters.doc_ids:
        predicates.append(source.doc_id.in_(filters.doc_ids))
    if filters.languages:
        # The tag is denormalized onto chunks, so a language restriction needs no
        # Document join and stays on the chunk access path every ranker shares.
        predicates.append(source.language.in_(filters.languages))
    if filters.registries:
        predicates.append(
            (Document.registry if source is Chunk else SnapshotChunk.registry).in_(
                filters.registries
            )
        )
    if filters.issuers:
        predicates.append(
            (Document.issuer if source is Chunk else SnapshotChunk.issuer).in_(filters.issuers)
        )
    if filters.fiscal_years:
        predicates.append(
            (Document.fiscal_year if source is Chunk else SnapshotChunk.fiscal_year).in_(
                filters.fiscal_years
            )
        )
    if filters.forms:
        predicates.append(
            (Document.form if source is Chunk else SnapshotChunk.form).in_(filters.forms)
        )
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates: list[ColumnElement[bool]] = []
        if named_items:
            item_predicates.append(source.item.in_(named_items))
        if None in filters.items:
            item_predicates.append(source.item.is_(None))
        predicates.append(or_(*item_predicates))
    if filters.kinds:
        predicates.append(source.kind.in_(filters.kinds))
    if filters.snapshot_id is not None:
        if source is SnapshotChunk:
            predicates.append(SnapshotChunk.snapshot_id == filters.snapshot_id)
        else:
            predicates.append(
                Chunk.id.in_(
                    select(SnapshotChunk.chunk_id).where(
                        SnapshotChunk.snapshot_id == filters.snapshot_id
                    )
                )
            )
    return tuple(predicates)


def needs_document_join(filters: RetrievalFilters, source: ChunkSource = Chunk) -> bool:
    """Return whether active filters require the ``Document`` join.

    Parameters
    ----------
    filters : RetrievalFilters
        Canonical chunk and document restrictions.

    Returns
    -------
    bool
        True when issuer, fiscal-year, or form restrictions are active.
    """
    return source is Chunk and bool(
        filters.registries or filters.issuers or filters.fiscal_years or filters.forms
    )


def apply_filters(
    statement: Select[Any], filters: RetrievalFilters, source: ChunkSource = Chunk
) -> Select[Any]:
    """Apply shared joins and exact-match predicates to a retrieval statement.

    Parameters
    ----------
    statement : Select[Any]
        Chunk-based statement to restrict.
    filters : RetrievalFilters
        Canonical restrictions shared by every retrieval path.

    Returns
    -------
    Select[Any]
        Statement with the required join and predicates.
    """
    if needs_document_join(filters, source):
        statement = statement.join_from(Chunk, Document, Document.doc_id == Chunk.doc_id)
    return statement.where(*filter_predicates(filters, source))


def hit_columns(
    score: ColumnElement[Any], source: ChunkSource = Chunk
) -> tuple[SQLColumnExpression[Any], ...]:
    """Return the shared ``ChunkHit`` projection with score last.

    Parameters
    ----------
    score : ColumnElement[Any]
        Strategy-specific labeled score or distance expression.

    Returns
    -------
    tuple[SQLColumnExpression[Any], ...]
        Columns matching the retrieval hit contract.
    """
    return (
        (Chunk.id if source is Chunk else SnapshotChunk.chunk_id).label("chunk_id"),
        source.doc_id,
        source.item,
        source.kind,
        source.citation,
        source.start_char,
        source.end_char,
        source.source_sha256,
        source.body,
        source.context_header,
        source.index_text,
        score,
    )


def hit_order_by(
    score_ordering: ColumnElement[Any], source: ChunkSource = Chunk
) -> tuple[ColumnElement[Any], ...]:
    """Order by score and stable source identity.

    Parameters
    ----------
    score_ordering : ColumnElement[Any]
        Strategy-specific ascending or descending score expression.

    Returns
    -------
    tuple[ColumnElement[Any], ...]
        Ordering expressions with source-provenance tie-breakers.

    Notes
    -----
    PostgreSQL's ``C`` collation keeps text tie-breakers compatible with Python's
    deterministic ordering.
    """
    return (
        score_ordering,
        source.doc_id.collate(TIE_BREAK_COLLATION).asc(),
        source.source_sha256.collate(TIE_BREAK_COLLATION).asc(),
        source.start_char.asc(),
        source.end_char.asc(),
        (Chunk.id if source is Chunk else SnapshotChunk.chunk_id).asc(),
    )
