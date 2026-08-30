"""SQLAlchemy models for filing chunks, evaluation runs, and workflow runs."""

from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, synonym

from app.config import get_settings

DIM = get_settings().embed_dim


class Base(DeclarativeBase):
    """Declarative base for application tables."""


class Document(Base):
    """One immutable filing snapshot and its registry identity."""

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    registry: Mapped[str] = mapped_column(String(16), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    issuer: Mapped[str] = mapped_column(String(32), nullable=False)
    issuer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    form: Mapped[str] = mapped_column(String(32), nullable=False)
    filing_date: Mapped[str] = mapped_column(String(10), nullable=False)
    report_period: Mapped[str] = mapped_column(String(10), nullable=False)
    filing_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    item_index: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    source_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "parse_status IN ('parsed', 'needs_profile_update')",
            name="ck_documents_parse_status",
        ),
        CheckConstraint("source_length > 0", name="ck_documents_source_length_positive"),
        CheckConstraint("language ~ '^[a-z]{2}$'", name="ck_documents_language_format"),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_documents_source_sha256_format",
        ),
    )


class Chunk(Base):
    """A source-cited retrieval unit with separate evidence and context text."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(
        ForeignKey("documents.doc_id", ondelete="CASCADE"), index=True, nullable=False
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    item: Mapped[str | None] = mapped_column(String(8), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    context_header: Mapped[str] = mapped_column(Text, nullable=False)
    index_text: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = synonym("index_text")
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    citation: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(DIM), nullable=True)
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', index_text)", persisted=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("doc_id", "ordinal", name="uq_doc_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_chunks_ordinal_nonnegative"),
        CheckConstraint("kind IN ('text', 'table')", name="ck_chunks_kind"),
        CheckConstraint("language ~ '^[a-z]{2}$'", name="ck_chunks_language_format"),
        CheckConstraint("start_char >= 0", name="ck_chunks_start_nonnegative"),
        CheckConstraint("end_char > start_char", name="ck_chunks_span_order"),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_chunks_source_sha256_format",
        ),
        Index("ix_chunks_tsv", "content_tsv", postgresql_using="gin"),
    )


class ChunkTerm(Base):
    """One lexeme and its frequency inside one chunk."""

    __tablename__ = "chunk_terms"

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    lexeme: Mapped[str] = mapped_column(Text, primary_key=True)
    tf: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (
        CheckConstraint("tf > 0", name="ck_chunk_terms_tf_positive"),
        Index("ix_chunk_terms_lexeme", "lexeme"),
    )


class ChunkLength(Base):
    """Total lexeme occurrences in one chunk."""

    __tablename__ = "chunk_lengths"

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    dl: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (CheckConstraint("dl > 0", name="ck_chunk_lengths_positive"),)


class LexemeStat(Base):
    """Number of chunks containing one lexeme."""

    __tablename__ = "lexeme_stats"

    lexeme: Mapped[str] = mapped_column(Text, primary_key=True)
    df: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (CheckConstraint("df > 0", name="ck_lexeme_stats_df_positive"),)


class BM25CorpusStat(Base):
    """One-row corpus metadata proving that BM25 statistics are current."""

    __tablename__ = "bm25_corpus_stats"

    singleton_id: Mapped[int] = mapped_column(primary_key=True)
    n: Mapped[int] = mapped_column(BigInteger, nullable=False)
    avgdl: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        CheckConstraint("singleton_id = 1", name="ck_bm25_corpus_stats_singleton"),
        CheckConstraint("n > 0", name="ck_bm25_corpus_stats_n_positive"),
        CheckConstraint("avgdl > 0", name="ck_bm25_corpus_stats_avgdl_positive"),
    )


class EvalResult(Base):
    """One persisted evaluation run used as a comparable regression baseline."""

    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    suite: Mapped[str] = mapped_column(String(128), nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    raw_artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("btrim(suite) <> ''", name="ck_eval_results_suite_nonempty"),
        CheckConstraint(
            "jsonb_typeof(config) = 'object'",
            name="ck_eval_results_config_object",
        ),
        CheckConstraint(
            "jsonb_typeof(metrics) = 'object'",
            name="ck_eval_results_metrics_object",
        ),
        CheckConstraint(
            "btrim(raw_artifact_path) <> ''",
            name="ck_eval_results_raw_artifact_path_nonempty",
        ),
        Index("ix_eval_results_suite_created_at", "suite", "created_at"),
    )


class Run(Base):
    """One persisted workflow result, including its structured failure outcome."""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    iterations: Mapped[int] = mapped_column(nullable=False)
    total_requests: Mapped[int] = mapped_column(nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    node_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    report: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'budget_exceeded', 'schema_rejected', 'error')",
            name="ck_runs_status",
        ),
        CheckConstraint("iterations >= 0", name="ck_runs_iterations_nonnegative"),
        CheckConstraint("total_requests >= 0", name="ck_runs_requests_nonnegative"),
        CheckConstraint("total_input_tokens >= 0", name="ck_runs_input_tokens_nonnegative"),
        CheckConstraint("total_output_tokens >= 0", name="ck_runs_output_tokens_nonnegative"),
        CheckConstraint("total_time_seconds >= 0", name="ck_runs_time_nonnegative"),
        CheckConstraint("btrim(system_prompt) <> ''", name="ck_runs_system_prompt_nonempty"),
        CheckConstraint("jsonb_typeof(node_path) = 'array'", name="ck_runs_node_path_array"),
        CheckConstraint(
            "report IS NULL OR jsonb_typeof(report) = 'object'",
            name="ck_runs_report_object",
        ),
        Index("ix_runs_status_created_at", "status", "created_at"),
    )


class Trace(Base):
    """One raw provider step belonging to a persisted workflow run."""

    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[int] = mapped_column(nullable=False)
    node: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    api_url: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    request_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    llm_output: Mapped[str] = mapped_column(Text, nullable=False)
    retries: Mapped[int] = mapped_column(nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("run_id", "step", name="uq_traces_run_step"),
        CheckConstraint("step > 0", name="ck_traces_step_positive"),
        CheckConstraint(
            "node IN ('retrieve', 'grade', 'check', 'report')",
            name="ck_traces_node",
        ),
        CheckConstraint("btrim(model_name) <> ''", name="ck_traces_model_name_nonempty"),
        CheckConstraint("btrim(api_url) <> ''", name="ck_traces_api_url_nonempty"),
        CheckConstraint("input_tokens >= 0", name="ck_traces_input_tokens_nonnegative"),
        CheckConstraint("output_tokens >= 0", name="ck_traces_output_tokens_nonnegative"),
        CheckConstraint("estimated_cost_usd >= 0", name="ck_traces_cost_nonnegative"),
        CheckConstraint("request_time_ms >= 0", name="ck_traces_time_nonnegative"),
        CheckConstraint("retries >= 0", name="ck_traces_retries_nonnegative"),
    )
