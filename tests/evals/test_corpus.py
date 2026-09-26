"""Corpus preparation shared by the chunking arms of one evaluation run."""

from copy import deepcopy
import hashlib

from pgvector.sqlalchemy import Vector
import pytest
from sqlalchemy import Table

from app.config import Settings
from app.db.models import Base
from app.evals.corpus import _temporary_metadata, build_chunking_batch, load_chunking_filings
import app.ingestion.edgar as edgar
from app.ingestion.manifest import Manifest, ProcessingSelection
from app.ingestion.parser import Block, ParsedFiling, Section, normalize
from app.retrieval.embeddings import DeterministicEmbeddingProvider
from tests.ingestion.edgar.support import build_numbered_body
from tests.ingestion.support import filing_document, filing_source
from tests.support import load_settings


def test_load_chunking_filings_reads_only_verified_selected_sources(tmp_path, monkeypatch):
    """Bind parsed evidence to the selected artifact and refuse bytes changed after acquisition."""
    source_path = tmp_path / "filing.html"
    raw = build_numbered_body(gap=2)
    source_path.write_text(raw)
    source = filing_source(source_path)
    unselected_path = tmp_path / "unselected.html"
    unselected_path.write_text(raw)
    unselected = filing_source(
        unselected_path,
        document=filing_document(issuer="AMD", filing_id="0000002488-24-000012"),
    )
    manifest = Manifest(
        corpus=source.corpus,
        documents=(source.document, unselected.document),
        artifacts=(source.artifact, unselected.artifact),
        selections=(
            ProcessingSelection(
                selection_id="selected", artifact_ids=(source.artifact.artifact_id,)
            ),
        ),
    )
    manifest.write(tmp_path / "manifest.json")
    monkeypatch.setattr(edgar, "PROFILES", tmp_path / "profiles")
    settings = load_settings(Settings, env_file=None, corpus_dir=tmp_path)

    filings = load_chunking_filings(settings=settings, selection_id="selected")

    assert len(filings) == 1
    filing = filings[0]
    assert filing.source == source
    assert filing.source_sha256 == hashlib.sha256(raw.encode()).hexdigest()
    assert filing.source_length == len(raw)
    assert {"1", "1A", "7", "8"} <= {section.item for section in filing.sections}
    source_path.write_text(raw.replace("Body text", "Wrong text", 1))
    with pytest.raises(ValueError, match="artifact bytes disagree"):
        load_chunking_filings(settings=settings, selection_id="selected")


def embedding_type(table: Table) -> Vector:
    """Return the pgvector type declared on a table's embedding column."""
    column_type = table.c.embedding.type
    assert isinstance(column_type, Vector)
    return column_type


def test_temporary_vector_widths_do_not_mutate_other_schemas():
    """Keep separate evaluation widths independent from each other and the live schema."""
    live_type = embedding_type(Base.metadata.tables["chunk_embeddings"])
    live_dimensions = live_type.dim

    first = _temporary_metadata(12)
    second = _temporary_metadata(24)

    assert embedding_type(first.tables["chunk_embeddings"]).dim == 12
    assert embedding_type(second.tables["chunk_embeddings"]).dim == 24
    assert embedding_type(Base.metadata.tables["chunk_embeddings"]) is live_type
    assert live_type.dim == live_dimensions


@pytest.fixture
def parsed_filing(tmp_path):
    """Supply a real source snapshot parsed into short, independently located disclosures."""
    paragraphs = [
        "Revenue increased with customer demand.",
        "Product costs decreased during the year.",
        "Cash reserves support planned investments.",
        "Research spending funds future products.",
        "International sales increased this year.",
        "Debt repayments reduced outstanding balances.",
        "Operating margins improved across segments.",
        "Management expects continued market competition.",
    ]
    raw = "\n".join(f"<p>{text}</p>" for text in paragraphs)
    path = tmp_path / "filing.html"
    path.write_text(raw)
    blocks = [
        Block(
            "paragraph",
            text,
            source_pos=raw.index(f"<p>{text}</p>"),
            end_pos=raw.index(f"<p>{text}</p>") + len(f"<p>{text}</p>"),
        )
        for text in paragraphs
    ]
    filing = ParsedFiling(
        source=filing_source(path),
        source_length=len(raw),
        source_sha256=hashlib.sha256(raw.encode()).hexdigest(),
        sections=[Section("II", "7", "Results", "Results", blocks)],
    )
    return raw, filing, paragraphs


def test_chunking_target_changes_packing_without_mutating_source_evidence(parsed_filing):
    """Different targets change chunk boundaries while preserving every source word and identity."""
    raw, filing, paragraphs = parsed_filing
    before = deepcopy(filing)
    batches = [
        build_chunking_batch(
            target,
            provider=DeterministicEmbeddingProvider(),
            parsed_filings=(filing,),
            selection_id="selected",
        )
        for target in (16, 2048)
    ]
    assert len(batches[0].chunks) > len(batches[1].chunks) > 0
    for batch in batches:
        assert (
            " ".join(chunk.body for chunk in batch.chunks).split() == " ".join(paragraphs).split()
        )
        for chunk in batch.chunks:
            assert chunk.doc_id == filing.source.document.document_id
            assert chunk.source_sha256 == hashlib.sha256(raw.encode()).hexdigest()
            evidence = normalize(raw[chunk.start_char : chunk.end_char]).get_text(" ", strip=True)
            assert chunk.body.split() == evidence.split()
    assert filing == before


def test_chunking_respects_the_selected_models_complete_input_limit(parsed_filing):
    """Context and body must fit the selected model despite a larger requested target."""
    _raw, filing, paragraphs = parsed_filing

    class SmallModel(DeterministicEmbeddingProvider):
        """A model with a sixteen-word window over the complete embedding input."""

        @property
        def max_input_tokens(self):
            return 16

        def count_input_tokens(self, text):
            return len(text.split())

    batch = build_chunking_batch(
        2048,
        provider=SmallModel(),
        parsed_filings=(filing,),
        selection_id="selected",
    )
    assert all(len(chunk.index_text.split()) <= 16 for chunk in batch.chunks)
    assert " ".join(chunk.body for chunk in batch.chunks).split() == " ".join(paragraphs).split()
