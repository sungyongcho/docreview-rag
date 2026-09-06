"""L1 schema contract tests that require no running database."""

from sqlalchemy import CheckConstraint, Computed, UniqueConstraint

from app.db.models import Chunk, Document


def test_document_schema_persists_snapshot_and_filing_metadata():
    columns = Document.__table__.columns
    assert set(columns.keys()) == {
        "doc_id",
        "ticker",
        "cik",
        "fiscal_year",
        "form",
        "filing_date",
        "report_period",
        "accession",
        "url",
        "parse_status",
        "item_index",
        "source_length",
        "source_sha256",
    }
    assert columns.doc_id.primary_key
    assert not columns.source_length.nullable
    assert not columns.source_sha256.nullable
    assert not columns.parse_status.nullable
    assert not columns.item_index.nullable
    checks = {
        constraint.name
        for constraint in Document.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_documents_source_length_positive",
        "ck_documents_source_sha256_format",
        "ck_documents_parse_status",
    } <= checks


def test_chunk_schema_preserves_evidence_context_and_source_coordinates():
    columns = Chunk.__table__.columns
    required = {
        "doc_id",
        "item",
        "kind",
        "ordinal",
        "body",
        "context_header",
        "index_text",
        "start_char",
        "end_char",
        "source_sha256",
        "citation",
        "embedding",
        "content_tsv",
    }
    assert required <= set(columns.keys())
    assert "content" in Chunk.__mapper__.attrs
    assert Chunk.__mapper__.attrs.content.name == "index_text"
    assert columns.embedding.nullable


def test_search_vector_is_computed_from_index_text():
    computed = Chunk.__table__.columns.content_tsv.computed
    assert isinstance(computed, Computed)
    assert "to_tsvector('english', index_text)" in str(computed.sqltext)
    assert computed.persisted is True


def test_chunk_identity_and_validation_constraints_are_declared():
    constraints = Chunk.__table__.constraints
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in constraints
        if isinstance(constraint, UniqueConstraint)
    }
    checks = {
        constraint.name for constraint in constraints if isinstance(constraint, CheckConstraint)
    }
    assert ("doc_id", "ordinal") in unique_columns
    assert {
        "ck_chunks_ordinal_nonnegative",
        "ck_chunks_kind",
        "ck_chunks_start_nonnegative",
        "ck_chunks_span_order",
        "ck_chunks_source_sha256_format",
    } <= checks
