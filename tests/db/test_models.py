"""SQLAlchemy schema contract tests that require no running database."""

from sqlalchemy import CheckConstraint, Computed, DateTime, Table, UniqueConstraint

from app.db.models import Chunk, Document, EvalResult, Run, Trace


def test_document_schema_persists_snapshot_and_filing_metadata():
    """Persist registry-neutral filing identity and source metadata."""
    columns = Document.__table__.columns
    assert set(columns.keys()) == {
        "doc_id",
        "registry",
        "issuer",
        "issuer_id",
        "fiscal_year",
        "form",
        "filing_date",
        "report_period",
        "filing_id",
        "source_url",
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
    document_table = Document.__table__
    assert isinstance(document_table, Table)
    checks = {
        constraint.name
        for constraint in document_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_documents_source_length_positive",
        "ck_documents_source_sha256_format",
        "ck_documents_parse_status",
    } <= checks


def test_chunk_schema_preserves_evidence_context_and_source_coordinates():
    """Persist chunk evidence, retrieval context, and source coordinates."""
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
    """Generate the PostgreSQL search vector from indexed text."""
    computed = Chunk.__table__.columns.content_tsv.computed
    assert isinstance(computed, Computed)
    assert "to_tsvector('english', index_text)" in str(computed.sqltext)
    assert computed.persisted is True


def test_chunk_identity_and_validation_constraints_are_declared():
    """Declare chunk identity, kind, ordinal, span, and digest constraints."""
    chunk_table = Chunk.__table__
    assert isinstance(chunk_table, Table)
    constraints = chunk_table.constraints
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


def test_eval_result_schema_persists_complete_run_provenance():
    """Persist suite, config, metrics, artifact path, and creation time."""
    table = EvalResult.__table__
    assert isinstance(table, Table)
    columns = table.columns

    assert set(columns.keys()) == {
        "id",
        "suite",
        "config",
        "metrics",
        "raw_artifact_path",
        "created_at",
    }
    assert columns.id.primary_key
    assert columns.created_at.server_default is not None
    created_at_type = columns.created_at.type
    assert isinstance(created_at_type, DateTime)
    assert created_at_type.timezone is True
    assert all(not columns[name].nullable for name in columns.keys())
    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_eval_results_suite_nonempty",
        "ck_eval_results_config_object",
        "ck_eval_results_metrics_object",
        "ck_eval_results_raw_artifact_path_nonempty",
    } <= checks
    assert {index.name for index in table.indexes} == {"ix_eval_results_suite_created_at"}


def test_database_models_match_run_and_trace_mapping_contracts():
    """Match the run and trace tables to the mapping the report persists."""
    run_table = Run.__table__
    trace_table = Trace.__table__
    assert isinstance(run_table, Table)
    assert isinstance(trace_table, Table)
    run_columns = run_table.columns
    trace_columns = trace_table.columns

    assert set(run_columns.keys()) == {
        "run_id",
        "status",
        "iterations",
        "total_requests",
        "total_input_tokens",
        "total_output_tokens",
        "total_time_seconds",
        "system_prompt",
        "node_path",
        "report",
        "created_at",
    }
    assert {
        "run_id",
        "step",
        "node",
        "model_name",
        "api_url",
        "input_tokens",
        "output_tokens",
        "estimated_cost_usd",
        "request_time_ms",
        "llm_output",
        "retries",
        "error",
    } <= set(trace_columns.keys())
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in trace_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    checks = {
        constraint.name
        for table in (run_table, trace_table)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert ("run_id", "step") in unique_columns
    assert {
        "ck_runs_status",
        "ck_traces_node",
        "ck_traces_step_positive",
        "ck_traces_cost_nonnegative",
    } <= checks
    # The unique constraint on (run_id, step) already carries a btree index.
    assert {index.name for index in trace_table.indexes} == set()
