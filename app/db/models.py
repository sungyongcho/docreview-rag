"""SQLAlchemy models for filing chunks, evaluation runs, and workflow runs."""

from __future__ import annotations

from datetime import date, datetime
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
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import EMBEDDING_DIMENSIONS

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


class FilingFactContext(Base):
    """One context a parse found in its filing: a period, its fiscal year and scope.

    ``dimensions`` are ``axis=member`` pairs; an undimensioned context has none. A
    DART context states only its fiscal year, so its dates are null.
    """

    __tablename__ = "filing_fact_contexts"

    structure_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_structures.structure_id", ondelete="CASCADE"), primary_key=True
    )
    context_id: Mapped[str] = mapped_column(Text, primary_key=True)
    period_start: Mapped[date | None] = mapped_column(nullable=True)
    period_end: Mapped[date | None] = mapped_column(nullable=True)
    instant: Mapped[date | None] = mapped_column(nullable=True)
    fiscal_year: Mapped[int | None] = mapped_column(nullable=True)
    dimensions: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "instant IS NULL OR (period_start IS NULL AND period_end IS NULL)",
            name="ck_filing_fact_contexts_period",
        ),
    )


class FilingFactUnit(Base):
    """One inline XBRL unit a parse found: its measures and a ratio's denominator."""

    __tablename__ = "filing_fact_units"

    structure_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_structures.structure_id", ondelete="CASCADE"), primary_key=True
    )
    unit_id: Mapped[str] = mapped_column(Text, primary_key=True)
    numerator: Mapped[str] = mapped_column(Text, nullable=False)
    denominator: Mapped[str | None] = mapped_column(Text, nullable=True)


class FilingPeriodTerm(Base):
    """One period word a parse found its DART report defining, with its declaration.

    ``term`` is ``당기``, ``전기``, ``전전기`` or ``제N기``; ``start_char``/``end_char``
    locate the declaration it rests on.
    """

    __tablename__ = "filing_period_terms"

    structure_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_structures.structure_id", ondelete="CASCADE"), primary_key=True
    )
    term: Mapped[str] = mapped_column(String(16), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    period_start: Mapped[date] = mapped_column(nullable=False)
    period_end: Mapped[date] = mapped_column(nullable=False)
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        CheckConstraint("period_end > period_start", name="ck_filing_period_terms_period"),
        CheckConstraint(
            "start_char >= 0 AND end_char > start_char", name="ck_filing_period_terms_span"
        ),
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
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("input_sha256 ~ '^[0-9a-f]{64}$'", name="ck_chunk_embeddings_digest"),
        CheckConstraint(
            f"dimensions = {EMBEDDING_DIMENSIONS}", name="ck_chunk_embeddings_dimensions"
        ),
        CheckConstraint(
            "btrim(provider) <> '' AND btrim(model) <> '' AND btrim(tokenizer) <> ''",
            name="ck_chunk_embeddings_configuration",
        ),
    )


class Document(Base):
    """One immutable filing snapshot and its registry identity."""

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    filing_registry: Mapped[str] = mapped_column("registry", String(16), nullable=False)
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


def _in(column: str, values: tuple[str, ...]) -> str:
    """Render a CHECK that keeps one text column inside a closed vocabulary."""
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


FILING_KINDS = ("report", "amendment")
AMENDMENT_ACTIONS = ("replace", "add", "withhold")


class FilingVersion(Base):
    """One filing a registry holds for a report period, whether indexed or only known.

    Filings that share ``registry``, ``issuer_id`` and ``report_period`` are versions of
    one report. A ``report`` is a whole document, so it replaces every earlier version.
    An ``amendment`` carries only some Items: until a review records what each Item does
    (``amendment_effects``), the whole report period is withheld from evidence.

    ``filed_key`` orders versions of one kind: the registry's receipt number, or the
    acceptance time as ``YYYYMMDDHHMMSS``. An amendment always follows its report.
    """

    __tablename__ = "filing_versions"

    filing_registry: Mapped[str] = mapped_column("registry", String(16), primary_key=True)
    filing_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    report_period: Mapped[str] = mapped_column(String(10), nullable=False)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    form: Mapped[str] = mapped_column(Text, nullable=False)
    filing_date: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    filed_key: Mapped[str] = mapped_column(String(14), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The source the reviewer read. A different source returns the amendment to review.
    reviewed_source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        CheckConstraint(_in("kind", FILING_KINDS), name="ck_filing_versions_kind"),
        CheckConstraint("filed_key ~ '^[0-9]{14}$'", name="ck_filing_versions_filed_key"),
        CheckConstraint(
            "(reviewed_at IS NULL AND reviewer IS NULL AND rationale IS NULL "
            "AND reviewed_source_sha256 IS NULL) OR "
            "(kind = 'amendment' AND reviewed_at IS NOT NULL AND btrim(reviewer) <> '' "
            "AND btrim(rationale) <> '' AND reviewed_source_sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_filing_versions_review",
        ),
        Index("ix_filing_versions_family", "registry", "issuer_id", "report_period"),
    )


class AmendmentEffect(Base):
    """What a reviewed amendment does to one Item of its report.

    ``replace`` admits the amendment's Item and retires the same Item of every earlier
    version. ``add`` admits it beside the earlier text. ``withhold`` retires the earlier
    Item without admitting the amendment's, for an Item neither filing states in full.
    """

    __tablename__ = "amendment_effects"

    filing_registry: Mapped[str] = mapped_column("registry", String(16), primary_key=True)
    filing_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    item: Mapped[str] = mapped_column(String(8), primary_key=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["registry", "filing_id"],
            ["filing_versions.registry", "filing_versions.filing_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(_in("action", AMENDMENT_ACTIONS), name="ck_amendment_effects_action"),
        CheckConstraint("btrim(item) <> ''", name="ck_amendment_effects_item"),
    )


class Chunk(Base):
    """A source-cited retrieval unit with separate evidence and context text."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stable_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    structure_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_structures.structure_id"), nullable=False
    )
    index_text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
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


TABLE_UNIT_STATUSES = ("known", "absent", "unknown", "conflicting")
TABLE_CELL_STATUSES = (
    "known",
    "blank",
    "not_numeric",
    "conflicting",
    "not_monetary",
    "scale_unknown",
    "currency_unconfirmed",
    "period_unknown",
    "scope_qualified",
    "scope_unknown",
    "item_unknown",
)
STATEMENT_KINDS = (
    "balance_sheet",
    "income",
    "comprehensive_income",
    "cash_flow",
    "equity",
    "notes",
    "summary",
)
STATEMENT_SCOPES = ("consolidated", "separate", "conflicting")
READING_BASES = ("text", "fact")
READING_MEASURES = ("amount", "per_share", "other")


class ParsedTable(Base):
    """One source table of one parse, stored once with the unit its own notes state."""

    __tablename__ = "parsed_tables"

    table_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(
        ForeignKey("documents.doc_id", ondelete="CASCADE"), index=True, nullable=False
    )
    structure_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_structures.structure_id"), nullable=False
    )
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    header_rows: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    builder_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    resolver_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_status: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_scale: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    unit_percent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unit_per_share_plain: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unit_currency: Mapped[list[str]] = mapped_column(ARRAY(String(8)), nullable=False)
    statement_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    statement_scope: Mapped[str | None] = mapped_column(String(16), nullable=True)
    statement_basis: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("table_id ~ '^[0-9a-f]{64}$'", name="ck_parsed_tables_id"),
        CheckConstraint("start_char >= 0 AND end_char > start_char", name="ck_parsed_tables_span"),
        CheckConstraint(_in("unit_status", TABLE_UNIT_STATUSES), name="ck_parsed_tables_unit"),
        CheckConstraint(
            _in("statement_kind", STATEMENT_KINDS), name="ck_parsed_tables_statement_kind"
        ),
        CheckConstraint(
            _in("statement_scope", STATEMENT_SCOPES), name="ck_parsed_tables_statement_scope"
        ),
        UniqueConstraint("structure_id", "start_char", "end_char", name="uq_parsed_tables_span"),
    )


class TableCaption(Base):
    """One caption linked to a table, in link order, with the cells it was read from.

    ``cells`` keeps the caption's original grid cells as JSON because a caption-only
    table or caption row has its own grid, not the data table's.
    """

    __tablename__ = "table_captions"

    table_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_tables.table_id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    cells: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_table_captions_ordinal"),
        CheckConstraint("jsonb_typeof(cells) = 'array'", name="ck_table_captions_cells"),
    )


class TableSourceCell(Base):
    """One original grid cell of a table and, when it holds figures, how it is read.

    The reading columns are all present or all absent: ``reading_values`` are the
    magnitudes the cell states, the rest the year, scale, item, percentage and currency
    ``check_figures`` reads for them.
    """

    __tablename__ = "table_source_cells"

    table_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_tables.table_id", ondelete="CASCADE"), primary_key=True
    )
    grid_row: Mapped[int] = mapped_column(Integer, primary_key=True)
    grid_column: Mapped[int] = mapped_column(Integer, primary_key=True)
    rowspan: Mapped[int] = mapped_column(Integer, nullable=False)
    colspan: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_char: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    end_char: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reading_values: Mapped[list[Decimal] | None] = mapped_column(ARRAY(Numeric), nullable=True)
    reading_years: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    reading_scale: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    reading_item: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reading_percent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reading_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    reading_marked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reading_row_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    reading_basis: Mapped[str | None] = mapped_column(String(8), nullable=True)
    reading_overrides: Mapped[list[str] | None] = mapped_column(ARRAY(String(16)), nullable=True)
    reading_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    reading_measure: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        CheckConstraint("grid_row >= 0 AND grid_column >= 0", name="ck_table_source_cells_grid"),
        CheckConstraint("rowspan > 0 AND colspan > 0", name="ck_table_source_cells_span"),
        CheckConstraint(
            "(start_char IS NULL) = (end_char IS NULL)", name="ck_table_source_cells_source"
        ),
        CheckConstraint(
            "(reading_values IS NULL) = (reading_years IS NULL) "
            "AND (reading_values IS NULL) = (reading_marked IS NULL) "
            "AND (reading_values IS NULL) = (reading_basis IS NULL) "
            "AND (reading_values IS NULL) = (reading_overrides IS NULL)",
            name="ck_table_source_cells_reading",
        ),
        CheckConstraint(_in("reading_basis", READING_BASES), name="ck_table_source_cells_basis"),
        CheckConstraint(
            _in("reading_measure", READING_MEASURES), name="ck_table_source_cells_measure"
        ),
    )


class TableSourceFact(Base):
    """One tagged number inside an original grid cell, as the filing declares it.

    ``scale`` is the inline XBRL power of ten of the displayed number (null for DART);
    ``decimals`` is the stated precision. ``ordinal`` orders the facts of one cell.
    """

    __tablename__ = "table_source_facts"

    table_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    grid_row: Mapped[int] = mapped_column(Integer, primary_key=True)
    grid_column: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    structure_id: Mapped[str] = mapped_column(String(64), nullable=False)
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    concept: Mapped[str] = mapped_column(Text, nullable=False)
    context_id: Mapped[str] = mapped_column(Text, nullable=False)
    unit_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    scale: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sign: Mapped[str | None] = mapped_column(String(1), nullable=True)
    decimals: Mapped[str | None] = mapped_column(String(8), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_table_source_facts_ordinal"),
        CheckConstraint(
            "start_char >= 0 AND end_char > start_char", name="ck_table_source_facts_span"
        ),
        ForeignKeyConstraint(
            ["table_id", "grid_row", "grid_column"],
            [
                "table_source_cells.table_id",
                "table_source_cells.grid_row",
                "table_source_cells.grid_column",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["structure_id", "context_id"],
            ["filing_fact_contexts.structure_id", "filing_fact_contexts.context_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["structure_id", "unit_id"],
            ["filing_fact_units.structure_id", "filing_fact_units.unit_id"],
            ondelete="CASCADE",
        ),
    )


class TableCell(Base):
    """One normalized body cell: what it shows and whether it is one selectable amount.

    ``source_row`` and ``column_index`` are the coordinates a chunk's fragment names.
    ``value`` keeps the sign and written decimals; ``value_row``/``value_column`` name
    the one source cell whose reading gives its unit, currency, year and item.
    """

    __tablename__ = "table_cells"

    table_id: Mapped[str] = mapped_column(
        ForeignKey("parsed_tables.table_id", ondelete="CASCADE"), primary_key=True
    )
    source_row: Mapped[int] = mapped_column(Integer, primary_key=True)
    column_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    column_header: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    value_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_column: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(_in("status", TABLE_CELL_STATUSES), name="ck_table_cells_status"),
        CheckConstraint(
            "(value_row IS NULL) = (value_column IS NULL)", name="ck_table_cells_value_source"
        ),
        CheckConstraint(
            "status <> 'known' OR (value IS NOT NULL AND value_row IS NOT NULL)",
            name="ck_table_cells_known_value",
        ),
        ForeignKeyConstraint(
            ["table_id", "value_row", "value_column"],
            [
                "table_source_cells.table_id",
                "table_source_cells.grid_row",
                "table_source_cells.grid_column",
            ],
            ondelete="CASCADE",
        ),
    )


class TableCellSource(Base):
    """One original grid cell that contributes to a normalized cell, in source order."""

    __tablename__ = "table_cell_sources"

    table_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_row: Mapped[int] = mapped_column(Integer, primary_key=True)
    column_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    grid_row: Mapped[int] = mapped_column(Integer, nullable=False)
    grid_column: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["table_id", "source_row", "column_index"],
            ["table_cells.table_id", "table_cells.source_row", "table_cells.column_index"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["table_id", "grid_row", "grid_column"],
            [
                "table_source_cells.table_id",
                "table_source_cells.grid_row",
                "table_source_cells.grid_column",
            ],
            ondelete="CASCADE",
        ),
    )


class ChunkTableCell(Base):
    """Which interval of one normalized cell a table chunk carries, in fragment order."""

    __tablename__ = "chunk_table_cells"

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text_start: Mapped[int] = mapped_column(Integer, nullable=False)
    text_end: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_chunk_table_cells_ordinal"),
        CheckConstraint(
            "text_start >= 0 AND text_end >= text_start", name="ck_chunk_table_cells_interval"
        ),
        ForeignKeyConstraint(
            ["table_id", "source_row", "column_index"],
            ["table_cells.table_id", "table_cells.source_row", "table_cells.column_index"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "chunk_id", "source_row", "column_index", name="uq_chunk_table_cells_cell"
        ),
    )


class ChunkTableHeader(Base):
    """One header cell a table chunk renders, in its fragment's header order.

    A wide table split by columns repeats only the headers of each piece's columns, so
    the header cells belong to the chunk.
    """

    __tablename__ = "chunk_table_headers"

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    grid_row: Mapped[int] = mapped_column(Integer, nullable=False)
    grid_column: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_chunk_table_headers_ordinal"),
        ForeignKeyConstraint(
            ["table_id", "grid_row", "grid_column"],
            [
                "table_source_cells.table_id",
                "table_source_cells.grid_row",
                "table_source_cells.grid_column",
            ],
            ondelete="CASCADE",
        ),
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
    text_fragment: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    doc_id: Mapped[str] = mapped_column(String(128), nullable=False)
    filing_registry: Mapped[str] = mapped_column("registry", String(16), nullable=False)
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
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
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


class SnapshotParsedTable(Base):
    """One table frozen by a snapshot, with the unit its notes stated then."""

    __tablename__ = "snapshot_parsed_tables"

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    table_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(128), nullable=False)
    structure_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    header_rows: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    builder_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    resolver_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_status: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_scale: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    unit_percent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unit_per_share_plain: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unit_currency: Mapped[list[str]] = mapped_column(ARRAY(String(8)), nullable=False)
    statement_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    statement_scope: Mapped[str | None] = mapped_column(String(16), nullable=True)
    statement_basis: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            _in("unit_status", TABLE_UNIT_STATUSES), name="ck_snapshot_parsed_tables_unit"
        ),
    )


class SnapshotTableCaption(Base):
    """One caption of a snapshot table, in link order."""

    __tablename__ = "snapshot_table_captions"

    snapshot_id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_char: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    cells: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "table_id"],
            ["snapshot_parsed_tables.snapshot_id", "snapshot_parsed_tables.table_id"],
            ondelete="CASCADE",
        ),
    )


class SnapshotTableSourceCell(Base):
    """One original grid cell of a snapshot table and its reading then."""

    __tablename__ = "snapshot_table_source_cells"

    snapshot_id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    grid_row: Mapped[int] = mapped_column(Integer, primary_key=True)
    grid_column: Mapped[int] = mapped_column(Integer, primary_key=True)
    rowspan: Mapped[int] = mapped_column(Integer, nullable=False)
    colspan: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    start_char: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    end_char: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reading_values: Mapped[list[Decimal] | None] = mapped_column(ARRAY(Numeric), nullable=True)
    reading_years: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    reading_scale: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    reading_item: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reading_percent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reading_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    reading_marked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reading_row_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    reading_basis: Mapped[str | None] = mapped_column(String(8), nullable=True)
    reading_overrides: Mapped[list[str] | None] = mapped_column(ARRAY(String(16)), nullable=True)
    reading_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    reading_measure: Mapped[str | None] = mapped_column(String(16), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "table_id"],
            ["snapshot_parsed_tables.snapshot_id", "snapshot_parsed_tables.table_id"],
            ondelete="CASCADE",
        ),
    )


class SnapshotTableCell(Base):
    """One normalized body cell of a snapshot table and its interpretation then."""

    __tablename__ = "snapshot_table_cells"

    snapshot_id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_row: Mapped[int] = mapped_column(Integer, primary_key=True)
    column_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    column_header: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    value_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_column: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(_in("status", TABLE_CELL_STATUSES), name="ck_snapshot_table_cells_status"),
        ForeignKeyConstraint(
            ["snapshot_id", "table_id"],
            ["snapshot_parsed_tables.snapshot_id", "snapshot_parsed_tables.table_id"],
            ondelete="CASCADE",
        ),
    )


class SnapshotTableCellSource(Base):
    """One grid cell contributing to a snapshot table's normalized cell, in order."""

    __tablename__ = "snapshot_table_cell_sources"

    snapshot_id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_row: Mapped[int] = mapped_column(Integer, primary_key=True)
    column_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    grid_row: Mapped[int] = mapped_column(Integer, nullable=False)
    grid_column: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "table_id", "source_row", "column_index"],
            [
                "snapshot_table_cells.snapshot_id",
                "snapshot_table_cells.table_id",
                "snapshot_table_cells.source_row",
                "snapshot_table_cells.column_index",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "table_id", "grid_row", "grid_column"],
            [
                "snapshot_table_source_cells.snapshot_id",
                "snapshot_table_source_cells.table_id",
                "snapshot_table_source_cells.grid_row",
                "snapshot_table_source_cells.grid_column",
            ],
            ondelete="CASCADE",
        ),
    )


class SnapshotChunkTableCell(Base):
    """Which interval of one normalized cell a snapshot table chunk carried."""

    __tablename__ = "snapshot_chunk_table_cells"

    snapshot_id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text_start: Mapped[int] = mapped_column(Integer, nullable=False)
    text_end: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "chunk_id"],
            ["snapshot_chunks.snapshot_id", "snapshot_chunks.chunk_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "table_id", "source_row", "column_index"],
            [
                "snapshot_table_cells.snapshot_id",
                "snapshot_table_cells.table_id",
                "snapshot_table_cells.source_row",
                "snapshot_table_cells.column_index",
            ],
            ondelete="CASCADE",
        ),
    )


class SnapshotChunkTableHeader(Base):
    """One header cell a snapshot table chunk rendered, in fragment order."""

    __tablename__ = "snapshot_chunk_table_headers"

    snapshot_id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), nullable=False)
    grid_row: Mapped[int] = mapped_column(Integer, nullable=False)
    grid_column: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "chunk_id"],
            ["snapshot_chunks.snapshot_id", "snapshot_chunks.chunk_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["snapshot_id", "table_id", "grid_row", "grid_column"],
            [
                "snapshot_table_source_cells.snapshot_id",
                "snapshot_table_source_cells.table_id",
                "snapshot_table_source_cells.grid_row",
                "snapshot_table_source_cells.grid_column",
            ],
            ondelete="CASCADE",
        ),
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
