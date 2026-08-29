"""Shared SQL construction for retrieval strategies."""

from typing import Any

from sqlalchemy import Select, SQLColumnExpression, or_
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Chunk, Document
from app.retrieval.types import RetrievalFilters

TIE_BREAK_COLLATION = "C"


def filter_predicates(filters: RetrievalFilters) -> tuple[ColumnElement[bool], ...]:
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
        predicates.append(Chunk.doc_id.in_(filters.doc_ids))
    if filters.issuers:
        predicates.append(Document.issuer.in_(filters.issuers))
    if filters.fiscal_years:
        predicates.append(Document.fiscal_year.in_(filters.fiscal_years))
    if filters.forms:
        predicates.append(Document.form.in_(filters.forms))
    if filters.items:
        named_items = tuple(item for item in filters.items if item is not None)
        item_predicates: list[ColumnElement[bool]] = []
        if named_items:
            item_predicates.append(Chunk.item.in_(named_items))
        if None in filters.items:
            item_predicates.append(Chunk.item.is_(None))
        predicates.append(or_(*item_predicates))
    if filters.kinds:
        predicates.append(Chunk.kind.in_(filters.kinds))
    return tuple(predicates)


def needs_document_join(filters: RetrievalFilters) -> bool:
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
    return bool(filters.issuers or filters.fiscal_years or filters.forms)


def apply_filters(statement: Select[Any], filters: RetrievalFilters) -> Select[Any]:
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
    if needs_document_join(filters):
        statement = statement.join_from(Chunk, Document, Document.doc_id == Chunk.doc_id)
    return statement.where(*filter_predicates(filters))


def hit_columns(score: ColumnElement[Any]) -> tuple[SQLColumnExpression[Any], ...]:
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
        Chunk.id.label("chunk_id"),
        Chunk.doc_id,
        Chunk.item,
        Chunk.kind,
        Chunk.citation,
        Chunk.start_char,
        Chunk.end_char,
        Chunk.source_sha256,
        Chunk.body,
        Chunk.context_header,
        Chunk.index_text,
        score,
    )


def hit_order_by(score_ordering: ColumnElement[Any]) -> tuple[ColumnElement[Any], ...]:
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
        Chunk.doc_id.collate(TIE_BREAK_COLLATION).asc(),
        Chunk.source_sha256.collate(TIE_BREAK_COLLATION).asc(),
        Chunk.start_char.asc(),
        Chunk.end_char.asc(),
        Chunk.id.asc(),
    )
