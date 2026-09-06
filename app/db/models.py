"""SQLAlchemy models for filing chunks, evaluation runs, and workflow runs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings

DIM = get_settings().embed_dim

# One authoritative copy of the language-dispatched index SQL. The evaluation
# corpus renders its temporary chunks table from these same strings, so the
# tsvector a measured arm searches is the tsvector the live table computes.
# The config must be a literal inside each branch: a runtime text-to-regconfig
# cast is only stable, and PostgreSQL requires generation expressions to be
# immutable.
CONTENT_TSV_SQL = (
    "CASE WHEN language = 'ko' "
    "THEN to_tsvector('simple', coalesce(lexical_text, index_text)) "
    "ELSE to_tsvector('english', index_text) END"
)
LEXICAL_TEXT_CHECK_SQL = "(language = 'ko') = (lexical_text IS NOT NULL)"
LANGUAGE_FORMAT_CHECK_SQL = "language ~ '^[a-z]{2}$'"


class Base(DeclarativeBase):
    """Declarative base for application tables."""


class Corpus(Base):
    """A named corpus independent of its current storage location."""

    __tablename__ = "corpora"

    corpus_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class SourceArtifact(Base):
    """Exact acquired bytes and their filing, decoding, and acquisition provenance."""

    __tablename__ = "source_artifacts"

    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.corpus_id"), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    encoding: Mapped[str | None] = mapped_column(String(32), nullable=True)
    acquisition: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("corpus_id", "path", name="uq_source_artifacts_corpus_path"),
        UniqueConstraint("corpus_id", "artifact_id", "sha256", name="uq_source_artifacts_identity"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_source_artifacts_digest"),
        CheckConstraint("byte_length > 0", name="ck_source_artifacts_length"),
        CheckConstraint(
            "role IN ('primary', 'archive', 'attachment')", name="ck_source_artifacts_role"
        ),
        CheckConstraint(
            "role <> 'primary' OR encoding IS NOT NULL", name="ck_source_artifacts_text_encoding"
        ),
        CheckConstraint(
            "role <> 'archive' OR encoding IS NULL", name="ck_source_artifacts_binary_encoding"
        ),
    )


class ProcessingSelection(Base):
    """A named set of exact source artifacts chosen for processing."""

    __tablename__ = "processing_selections"

    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.corpus_id"), primary_key=True)
    selection_id: Mapped[str] = mapped_column(String(128), primary_key=True)


class SelectionArtifact(Base):
    """Referentially bind a processing selection to an acquired source artifact."""

    __tablename__ = "selection_artifacts"

    corpus_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    selection_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["corpus_id", "selection_id"],
            ["processing_selections.corpus_id", "processing_selections.selection_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["corpus_id", "artifact_id"],
            ["source_artifacts.corpus_id", "source_artifacts.artifact_id"],
        ),
    )


class ParsedStructure(Base):
    """An immutable source-linked structural parse with an explicit parser identity."""

    __tablename__ = "parsed_structures"

    structure_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    corpus_id: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    item_index: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    structure: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["corpus_id", "artifact_id", "artifact_sha256"],
            [
                "source_artifacts.corpus_id",
                "source_artifacts.artifact_id",
                "source_artifacts.sha256",
            ],
        ),
        CheckConstraint("source_length > 0", name="ck_parsed_structures_source_length"),
        CheckConstraint(
            "parse_status IN ('parsed', 'needs_profile_update')", name="ck_parsed_structures_status"
        ),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_parsed_structures_digest"),
        CheckConstraint("jsonb_typeof(structure) = 'object'", name="ck_parsed_structures_object"),
    )


class ChunkEmbedding(Base):
    """A reusable vector bound to exact indexed input and embedding configuration."""

    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    input_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    dimensions: Mapped[int] = mapped_column(primary_key=True)
    tokenizer: Mapped[str] = mapped_column(String(128), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(DIM), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("input_sha256 ~ '^[0-9a-f]{64}$'", name="ck_chunk_embeddings_digest"),
        CheckConstraint(f"dimensions = {DIM}", name="ck_chunk_embeddings_dimensions"),
        CheckConstraint(
            "btrim(provider) <> '' AND btrim(model) <> '' AND btrim(tokenizer) <> ''",
            name="ck_chunk_embeddings_configuration",
        ),
    )


class Document(Base):
    """One immutable filing snapshot and its registry identity."""

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    registry: Mapped[str] = mapped_column(String(16), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    form: Mapped[str] = mapped_column(Text, nullable=False)
    filing_date: Mapped[str] = mapped_column(String(10), nullable=False)
    report_period: Mapped[str] = mapped_column(String(10), nullable=False)
    filing_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    sec: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    dart: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    current_parse: Mapped[DocumentParse] = relationship(uselist=False, lazy="raise", viewonly=True)

    __table_args__ = (
        UniqueConstraint("registry", "filing_id", name="uq_documents_filing_identity"),
        CheckConstraint("language ~ '^[a-z]{2}$'", name="ck_documents_language_format"),
        CheckConstraint(
            "(registry = 'sec' AND sec IS NOT NULL AND dart IS NULL) OR "
            "(registry = 'dart' AND dart IS NOT NULL AND sec IS NULL)",
            name="ck_documents_registry_metadata",
        ),
    )


class DocumentParse(Base):
    """Select the current parsed structure without merging it into filing identity."""

    __tablename__ = "document_parses"

    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id"), primary_key=True)
    structure_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_structures.structure_id"), nullable=False
    )
    structure: Mapped[ParsedStructure] = relationship(lazy="raise", viewonly=True)


class Chunk(Base):
    """A source-cited retrieval unit with separate evidence and context text."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stable_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    structure_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_structures.structure_id"), nullable=False
    )
    index_text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    table_fragment: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    text_fragment: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
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
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    citation: Mapped[str] = mapped_column(Text, nullable=False)
    # Korean rows store the n-gram tokenization of index_text (app.retrieval.korean);
    # English rows leave it NULL and the tsvector falls through to index_text.
    lexical_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(CONTENT_TSV_SQL, persisted=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("stable_key ~ '^[0-9a-f]{64}$'", name="ck_chunks_stable_key"),
        CheckConstraint("index_text_sha256 ~ '^[0-9a-f]{64}$'", name="ck_chunks_input_digest"),
        CheckConstraint("ordinal >= 0", name="ck_chunks_ordinal_nonnegative"),
        CheckConstraint("kind IN ('text', 'table')", name="ck_chunks_kind"),
        CheckConstraint(LANGUAGE_FORMAT_CHECK_SQL, name="ck_chunks_language_format"),
        CheckConstraint(LEXICAL_TEXT_CHECK_SQL, name="ck_chunks_lexical_text_language"),
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
    """Number of chunks in one corpus language containing one lexeme.

    Document frequency is partitioned by language because the two corpora share
    one chunks table but are tokenized differently; a global count would let the
    English corpus deflate the IDF of lexemes both corpora carry.
    """

    __tablename__ = "lexeme_stats"

    language: Mapped[str] = mapped_column(String(8), primary_key=True)
    lexeme: Mapped[str] = mapped_column(Text, primary_key=True)
    df: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (CheckConstraint("df > 0", name="ck_lexeme_stats_df_positive"),)


class BM25CorpusStat(Base):
    """Per-language corpus metadata proving that BM25 statistics are current.

    One row per corpus language in the chunks table; the invalidation trigger
    deletes every row, so an empty table means the statistics are stale.
    """

    __tablename__ = "bm25_corpus_stats"

    language: Mapped[str] = mapped_column(String(8), primary_key=True)
    n: Mapped[int] = mapped_column(BigInteger, nullable=False)
    avgdl: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        CheckConstraint(LANGUAGE_FORMAT_CHECK_SQL, name="ck_bm25_corpus_stats_language_format"),
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


class GoldenRevision(Base):
    """One immutable or editable revision of a strict golden-suite JSON payload."""

    __tablename__ = "golden_revisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    suite_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("golden_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("suite_id", "version", name="uq_golden_revision_suite_version"),
        CheckConstraint(
            "status IN ('draft', 'validated', 'published')",
            name="ck_golden_revisions_status",
        ),
        CheckConstraint("version > 0", name="ck_golden_revisions_version_positive"),
        CheckConstraint(
            "jsonb_typeof(payload) = 'array'", name="ck_golden_revisions_payload_array"
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_golden_revisions_sha256_format"),
        Index("ix_golden_revisions_suite_created_at", "suite_id", "created_at"),
    )


class EvaluationSnapshot(Base):
    """One immutable published comparison unit over corpus, golden, and eval identity."""

    __tablename__ = "evaluation_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    corpus_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    profile: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    golden_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("golden_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    eval_result_id: Mapped[int] = mapped_column(
        ForeignKey("eval_results.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("status IN ('ready', 'archived')", name="ck_evaluation_snapshots_status"),
        CheckConstraint("btrim(label) <> ''", name="ck_evaluation_snapshots_label_nonempty"),
        CheckConstraint(
            "corpus_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_evaluation_snapshots_corpus_fingerprint",
        ),
        CheckConstraint(
            "jsonb_typeof(profile) = 'object'", name="ck_evaluation_snapshots_profile_object"
        ),
        Index("ix_evaluation_snapshots_public_created_at", "public", "created_at"),
    )


class SnapshotDocument(Base):
    """One exact source document included in an evaluation snapshot."""

    __tablename__ = "snapshot_documents"

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    doc_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_count: Mapped[int] = mapped_column(nullable=False)
    embedding_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint("chunk_count >= 0", name="ck_snapshot_documents_chunk_count"),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_snapshot_documents_source_sha256",
        ),
        CheckConstraint(
            "embedding_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_snapshot_documents_embedding_fingerprint",
        ),
    )


class SnapshotChunk(Base):
    """Exact chunk and embedding identity retained by one immutable snapshot."""

    __tablename__ = "snapshot_chunks"

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stable_key: Mapped[str] = mapped_column(String(64), nullable=False)
    index_text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    table_fragment: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    text_fragment: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    doc_id: Mapped[str] = mapped_column(String(128), nullable=False)
    registry: Mapped[str] = mapped_column(String(16), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    issuer: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    form: Mapped[str] = mapped_column(String(32), nullable=False)
    item: Mapped[str | None] = mapped_column(String(8), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    context_header: Mapped[str] = mapped_column(Text, nullable=False)
    index_text: Mapped[str] = mapped_column(Text, nullable=False)
    lexical_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    citation: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(nullable=True)
    embedding_tokenizer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(DIM), nullable=True)
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(CONTENT_TSV_SQL, persisted=True),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("snapshot_id", "doc_id", "ordinal", name="uq_snapshot_doc_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_snapshot_chunks_ordinal_nonnegative"),
        CheckConstraint("kind IN ('text', 'table')", name="ck_snapshot_chunks_kind"),
        CheckConstraint(LANGUAGE_FORMAT_CHECK_SQL, name="ck_snapshot_chunks_language_format"),
        CheckConstraint(
            LEXICAL_TEXT_CHECK_SQL,
            name="ck_snapshot_chunks_lexical_text_language",
        ),
        CheckConstraint("start_char >= 0", name="ck_snapshot_chunks_start_nonnegative"),
        CheckConstraint("end_char > start_char", name="ck_snapshot_chunks_span_order"),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_snapshot_chunks_source_sha256"
        ),
        CheckConstraint(
            "(embedding IS NULL AND embedding_provider IS NULL AND embedding_model IS NULL "
            "AND embedding_dimensions IS NULL AND embedding_tokenizer IS NULL) OR "
            "(embedding IS NOT NULL AND "
            "btrim(embedding_provider) <> '' AND btrim(embedding_model) <> '' AND "
            "embedding_dimensions > 0 AND btrim(embedding_tokenizer) <> '')",
            name="ck_snapshot_chunks_embedding_identity_complete",
        ),
        Index("ix_snapshot_chunks_chunk_id", "chunk_id"),
        Index("ix_snapshot_chunks_tsv", "content_tsv", postgresql_using="gin"),
    )


class SnapshotChunkTerm(Base):
    """One frozen lexeme frequency for a snapshot chunk."""

    __tablename__ = "snapshot_chunk_terms"

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lexeme: Mapped[str] = mapped_column(Text, primary_key=True)
    tf: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (
        CheckConstraint("tf > 0", name="ck_snapshot_chunk_terms_tf_positive"),
        Index("ix_snapshot_chunk_terms_lexeme", "snapshot_id", "lexeme"),
    )


class SnapshotChunkLength(Base):
    """Frozen total lexeme occurrences for one snapshot chunk."""

    __tablename__ = "snapshot_chunk_lengths"

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dl: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (CheckConstraint("dl > 0", name="ck_snapshot_chunk_lengths_positive"),)


class SnapshotBM25CorpusStat(Base):
    """Per-language corpus size and average length frozen for one snapshot."""

    __tablename__ = "snapshot_bm25_corpus_stats"

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(String(8), primary_key=True)
    n: Mapped[int] = mapped_column(BigInteger, nullable=False)
    avgdl: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        CheckConstraint("n > 0", name="ck_snapshot_bm25_corpus_n_positive"),
        CheckConstraint("avgdl > 0", name="ck_snapshot_bm25_corpus_avgdl_positive"),
    )


class SnapshotLexemeStat(Base):
    """One frozen document-frequency value used by snapshot BM25 scoring."""

    __tablename__ = "snapshot_lexeme_stats"

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(String(8), primary_key=True)
    lexeme: Mapped[str] = mapped_column(Text, primary_key=True)
    df: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (CheckConstraint("df > 0", name="ck_snapshot_lexeme_stats_df_positive"),)


class OperatorJob(Base):
    """One persisted corpus or evaluation job with bounded progress evidence."""

    __tablename__ = "operator_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    current: Mapped[int] = mapped_column(nullable=False, default=0)
    total: Mapped[int | None] = mapped_column(nullable=True)
    detail_current: Mapped[int | None] = mapped_column(nullable=True)
    detail_total: Mapped[int | None] = mapped_column(nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_refs: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("domain IN ('corpus', 'evaluation')", name="ck_operator_jobs_domain"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'interrupted', 'cancelled')",
            name="ck_operator_jobs_status",
        ),
        CheckConstraint("current >= 0", name="ck_operator_jobs_current_nonnegative"),
        CheckConstraint("total IS NULL OR total >= 0", name="ck_operator_jobs_total_nonnegative"),
        CheckConstraint(
            "detail_current IS NULL OR detail_current >= 0",
            name="ck_operator_jobs_detail_current_nonnegative",
        ),
        CheckConstraint(
            "detail_total IS NULL OR detail_total >= 0",
            name="ck_operator_jobs_detail_total_nonnegative",
        ),
        CheckConstraint(
            "jsonb_typeof(request_json) = 'object'", name="ck_operator_jobs_request_object"
        ),
        CheckConstraint(
            "jsonb_typeof(result_refs) = 'object'", name="ck_operator_jobs_results_object"
        ),
        Index("ix_operator_jobs_status_created_at", "status", "created_at"),
        Index("ix_operator_jobs_domain_created_at", "domain", "created_at"),
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
    total_cached_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_cache_write_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_reasoning_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    total_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    node_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    report: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    request_context: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True),
        nullable=True,
    )
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
        CheckConstraint(
            "total_cached_input_tokens >= 0",
            name="ck_runs_cached_input_tokens_nonnegative",
        ),
        CheckConstraint(
            "total_cache_write_input_tokens >= 0",
            name="ck_runs_cache_write_input_tokens_nonnegative",
        ),
        CheckConstraint(
            "total_reasoning_tokens >= 0",
            name="ck_runs_reasoning_tokens_nonnegative",
        ),
        CheckConstraint(
            "total_estimated_cost_usd >= 0",
            name="ck_runs_cost_nonnegative",
        ),
        CheckConstraint("total_time_seconds >= 0", name="ck_runs_time_nonnegative"),
        CheckConstraint("btrim(system_prompt) <> ''", name="ck_runs_system_prompt_nonempty"),
        CheckConstraint("jsonb_typeof(node_path) = 'array'", name="ck_runs_node_path_array"),
        CheckConstraint(
            "report IS NULL OR jsonb_typeof(report) = 'object'",
            name="ck_runs_report_object",
        ),
        CheckConstraint(
            "request_context IS NULL OR jsonb_typeof(request_context) = 'object'",
            name="ck_runs_request_context_object",
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
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_write_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
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
            "node IN ('gate', 'route', 'retrieve', 'chat', 'grade', 'check', 'report')",
            name="ck_traces_node_v2",
        ),
        CheckConstraint("btrim(model_name) <> ''", name="ck_traces_model_name_nonempty"),
        CheckConstraint("btrim(api_url) <> ''", name="ck_traces_api_url_nonempty"),
        CheckConstraint("input_tokens >= 0", name="ck_traces_input_tokens_nonnegative"),
        CheckConstraint("output_tokens >= 0", name="ck_traces_output_tokens_nonnegative"),
        CheckConstraint(
            "cached_input_tokens >= 0",
            name="ck_traces_cached_input_tokens_nonnegative",
        ),
        CheckConstraint(
            "cache_write_input_tokens >= 0",
            name="ck_traces_cache_write_input_tokens_nonnegative",
        ),
        CheckConstraint(
            "reasoning_tokens >= 0",
            name="ck_traces_reasoning_tokens_nonnegative",
        ),
        CheckConstraint("estimated_cost_usd >= 0", name="ck_traces_cost_nonnegative"),
        CheckConstraint("request_time_ms >= 0", name="ck_traces_time_nonnegative"),
        CheckConstraint("retries >= 0", name="ck_traces_retries_nonnegative"),
    )
