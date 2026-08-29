"""SQLAlchemy models for source-cited filing chunks."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
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
        CheckConstraint("start_char >= 0", name="ck_chunks_start_nonnegative"),
        CheckConstraint("end_char > start_char", name="ck_chunks_span_order"),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_chunks_source_sha256_format",
        ),
        Index("ix_chunks_tsv", "content_tsv", postgresql_using="gin"),
    )
