"""Explicit read joins for current filing parses."""

from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import contains_eager
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Document, DocumentParse, ParsedStructure


def join_current_parse(
    statement: Select[Any], *, load: bool = False, grouped: bool = False
) -> Select[Any]:
    """Join the selected structural parse, optionally loading its ORM relationships."""
    statement = statement.join(DocumentParse, DocumentParse.doc_id == Document.doc_id).join(
        ParsedStructure, ParsedStructure.structure_id == DocumentParse.structure_id
    )
    if load:
        statement = statement.options(
            contains_eager(Document.current_parse).contains_eager(DocumentParse.structure)
        )
    if grouped:
        statement = statement.group_by(DocumentParse.doc_id, ParsedStructure.structure_id)
    return statement


def current_source_matches(
    digest: ColumnElement[str] | InstrumentedAttribute[str],
) -> ColumnElement[bool]:
    """Correlate a source digest to the filing's explicitly selected current parse."""
    return (
        select(DocumentParse.doc_id)
        .join(ParsedStructure, ParsedStructure.structure_id == DocumentParse.structure_id)
        .where(DocumentParse.doc_id == Document.doc_id, ParsedStructure.source_sha256 == digest)
        .correlate_except(DocumentParse, ParsedStructure)
        .exists()
    )
