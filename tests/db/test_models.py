"""SQLAlchemy schema contract tests that require no running database."""

from sqlalchemy import CheckConstraint, Computed, DateTime, Table, UniqueConstraint

from app.db.models import (
    CONTENT_TSV_SQL,
    LEXICAL_TEXT_CHECK_SQL,
    BM25CorpusStat,
    Chunk,
    Document,
    EvalResult,
    EvaluationSnapshot,
    GoldenRevision,
    LexemeStat,
    OperatorJob,
    Run,
    SnapshotBM25CorpusStat,
    SnapshotChunk,
    SnapshotChunkLength,
    SnapshotChunkTerm,
    SnapshotDocument,
    SnapshotLexemeStat,
    Trace,
)
from app.retrieval.korean import lexical_plan


def test_document_schema_persists_snapshot_and_filing_metadata():
    """Persist registry-neutral filing identity and source metadata."""
    columns = Document.__table__.columns
    assert set(columns.keys()) == {
        "doc_id",
        "registry",
        "language",
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
    assert not columns.language.nullable
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


def test_search_vector_is_computed_per_corpus_language():
    """Generate the search vector with each corpus language's own configuration."""
    computed = Chunk.__table__.columns.content_tsv.computed
    assert isinstance(computed, Computed)
    expression = str(computed.sqltext)
    assert "to_tsvector('simple', coalesce(lexical_text, index_text))" in expression
    assert "to_tsvector('english', index_text)" in expression
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


def test_experiment_schema_preserves_golden_snapshot_and_document_identity():
    """Persist self-contained chunk, embedding, and lexical snapshot revisions."""
    golden = GoldenRevision.__table__
    snapshot = EvaluationSnapshot.__table__
    membership = SnapshotDocument.__table__

    assert {"suite_id", "version", "status", "payload", "sha256"} <= set(golden.columns.keys())
    assert {
        "label",
        "public",
        "corpus_fingerprint",
        "profile",
        "golden_revision_id",
        "eval_result_id",
    } <= set(snapshot.columns.keys())
    assert set(membership.primary_key.columns.keys()) == {"snapshot_id", "doc_id"}
    assert not membership.columns.doc_id.foreign_keys
    assert membership.columns.source_sha256.nullable is False
    assert set(SnapshotChunk.__table__.primary_key.columns.keys()) == {
        "snapshot_id",
        "chunk_id",
    }
    assert not SnapshotChunk.__table__.columns.chunk_id.foreign_keys
    assert {
        "doc_id",
        "registry",
        "language",
        "issuer",
        "fiscal_year",
        "form",
        "body",
        "context_header",
        "index_text",
        "content_tsv",
        "embedding",
    } <= set(SnapshotChunk.__table__.columns.keys())
    assert set(SnapshotChunkTerm.__table__.primary_key.columns.keys()) == {
        "snapshot_id",
        "chunk_id",
        "lexeme",
    }
    assert set(SnapshotChunkLength.__table__.primary_key.columns.keys()) == {
        "snapshot_id",
        "chunk_id",
    }
    assert set(SnapshotBM25CorpusStat.__table__.primary_key.columns.keys()) == {
        "snapshot_id",
        "language",
    }
    assert set(SnapshotLexemeStat.__table__.primary_key.columns.keys()) == {
        "snapshot_id",
        "language",
        "lexeme",
    }


def test_operator_job_schema_persists_queue_progress_and_result_provenance():
    """Persist corpus and evaluation work across application restarts."""
    table = OperatorJob.__table__
    assert {
        "job_id",
        "domain",
        "kind",
        "request_json",
        "status",
        "stage",
        "current",
        "total",
        "detail_current",
        "detail_total",
        "message",
        "error_code",
        "result_refs",
        "created_at",
        "started_at",
        "finished_at",
        "updated_at",
    } == set(table.columns.keys())
    assert table.columns.job_id.primary_key
    assert {index.name for index in table.indexes} == {
        "ix_operator_jobs_status_created_at",
        "ix_operator_jobs_domain_created_at",
    }


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
        "total_cached_input_tokens",
        "total_cache_write_input_tokens",
        "total_reasoning_tokens",
        "total_estimated_cost_usd",
        "total_time_seconds",
        "system_prompt",
        "node_path",
        "report",
        "request_context",
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
        "cached_input_tokens",
        "cache_write_input_tokens",
        "reasoning_tokens",
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
        "ck_traces_node_v2",
        "ck_traces_step_positive",
        "ck_traces_cost_nonnegative",
    } <= checks
    # The unique constraint on (run_id, step) already carries a btree index.
    assert {index.name for index in trace_table.indexes} == set()


def test_index_sql_constants_agree_with_the_lexical_plans():
    """Pin the shared SQL to the plan table so the two dispatches cannot drift."""
    korean = lexical_plan("ko")
    english = lexical_plan("en")

    assert f"to_tsvector('{korean.text_search_config}'" in CONTENT_TSV_SQL
    assert f"to_tsvector('{english.text_search_config}'" in CONTENT_TSV_SQL
    assert "language = 'ko'" in CONTENT_TSV_SQL
    assert LEXICAL_TEXT_CHECK_SQL == "(language = 'ko') = (lexical_text IS NOT NULL)"


def test_bm25_statistics_are_partitioned_by_corpus_language():
    """Both derived statistic tables key on the chunk's corpus language."""
    lexeme_columns = LexemeStat.__table__.columns
    corpus_columns = BM25CorpusStat.__table__.columns

    assert [column.name for column in lexeme_columns if column.primary_key] == [
        "language",
        "lexeme",
    ]
    assert [column.name for column in corpus_columns if column.primary_key] == ["language"]
