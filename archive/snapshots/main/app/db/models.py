from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (  # DateTime, func 추가
    Computed,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,  # JSONB 추가
    TSVECTOR,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBED_DIM = 384  # st all-MiniLM 차원. fake(256)와 다르니 st 고정


class Base(DeclarativeBase): ...


class Document(Base):
    __tablename__ = "documents"
    doc_id: Mapped[str] = mapped_column(primary_key=True)  # "HR-001"
    title: Mapped[str | None]
    version: Mapped[str | None]
    effective: Mapped[str | None]


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id"), index=True)
    section: Mapped[str]
    heading: Mapped[str]
    content: Mapped[str]
    citation: Mapped[str]
    content_hash: Mapped[str]  # 재시드 중복 방지용
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    content_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', heading || ' ' || content)", persisted=True),
    )
    __table_args__ = (
        UniqueConstraint("doc_id", "section", name="uq_doc_section"),
        Index("ix_chunks_tsv", "content_tsv", postgresql_using="gin"),  # GIN 인덱스
    )


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str]
    status: Mapped[str]
    claim: Mapped[str]
    node_path: Mapped[list] = mapped_column(JSONB, default=list)
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Trace(Base):
    __tablename__ = "traces"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    model_name: Mapped[str]
    prompt_version: Mapped[str]
    latency_ms: Mapped[int]
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    est_cost_usd: Mapped[float] = mapped_column(default=0.0)
    tool_sequence: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
