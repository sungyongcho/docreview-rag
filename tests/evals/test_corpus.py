"""Corpus preparation shared by the chunking arms of one evaluation run."""

from typing import cast

import pytest

from app.config import Settings
from app.db.models import Base
import app.evals.corpus as corpus
from app.evals.corpus import _temporary_metadata, build_chunking_batch, load_chunking_filings
from app.ingestion.parser import ParsedFiling
from app.retrieval.embeddings import DeterministicEmbeddingProvider


def test_build_chunking_batch_reuses_supplied_filings_without_loading_manifest(monkeypatch):
    """Reuse parsed filings instead of re-reading the manifest."""
    parsed_filings = (cast(ParsedFiling, object()),)
    expected_batch = object()
    calls = []

    def build_from_filings(filings, *, chunker, on_progress):
        """Record the supplied filings and return the sentinel batch."""
        calls.append(filings)
        assert callable(chunker)
        return expected_batch

    monkeypatch.setattr(corpus, "build_seed_batch_from_filings", build_from_filings)
    monkeypatch.setattr(
        corpus,
        "load_manifest",
        lambda _path: pytest.fail("manifest must not be loaded when parsed filings are supplied"),
    )

    result = build_chunking_batch(
        500,
        provider=DeterministicEmbeddingProvider(),
        parsed_filings=parsed_filings,
        selection_id="sec-evaluation",
    )

    assert result is expected_batch
    assert calls == [parsed_filings]


def test_load_chunking_filings_parses_the_manifest_once(monkeypatch, tmp_path):
    """Parse the configured manifest once for the whole run."""
    manifest = tmp_path / "manifest.json"
    entries = (object(), object())
    parsed_filings = (object(), object())
    calls = []

    monkeypatch.setattr(
        corpus,
        "load_manifest",
        lambda path, *, selection_id: (
            entries if path == manifest and selection_id == "sec-evaluation" else None
        ),
    )

    def parse_once(received, *, expected_documents, on_progress):
        """Record one manifest parse and return the prepared filings."""
        calls.append((received, expected_documents))
        return parsed_filings

    monkeypatch.setattr(corpus, "parse_seed_filings", parse_once)
    settings = cast(Settings, type("SettingsStub", (), {"corpus_dir": tmp_path})())

    result = load_chunking_filings(settings=settings, selection_id="sec-evaluation")

    assert result is parsed_filings
    assert calls == [(entries, None)]


def test_the_temporary_schema_keeps_actual_normalized_constraints_and_vector_width():
    """Preserve normalized source relations while isolating experiment dimensions."""
    original_type = Base.metadata.tables["chunk_embeddings"].c.embedding.type
    original_dimensions = original_type.dim
    metadata = _temporary_metadata(12)
    assert set(metadata.tables) == set(Base.metadata.tables)
    for name, table in Base.metadata.tables.items():
        clone = metadata.tables[name]
        assert set(clone.columns.keys()) == set(table.columns.keys())
        assert {constraint.name for constraint in clone.constraints} == {
            constraint.name for constraint in table.constraints
        }
    dimension_check = next(
        constraint
        for constraint in metadata.tables["chunk_embeddings"].constraints
        if constraint.name == "ck_chunk_embeddings_dimensions"
    )
    assert str(dimension_check.sqltext) == "dimensions = 12"
    assert "embedding" not in metadata.tables["chunks"].c
    assert metadata.tables["chunk_embeddings"].c.embedding.type.dim == 12
    assert metadata.tables["snapshot_chunks"].c.embedding.type.dim == 12
    assert Base.metadata.tables["chunk_embeddings"].c.embedding.type is original_type
    assert original_type.dim == original_dimensions


def test_chunking_batch_passes_the_token_target_to_the_chunker(monkeypatch):
    """Keep evaluation chunking on the same token configuration as ingestion."""
    filing = object()
    received = []

    def chunk_filing(source, config):
        """Capture the effective configuration without reading a source file."""
        received.append((source, config.target_tokens))
        return []

    def build_batch(filings, *, chunker, on_progress):
        """Exercise the chunker passed to the ingestion batch builder."""
        for source in filings:
            chunker(source)
        return object()

    monkeypatch.setattr(corpus, "chunk_filing", chunk_filing)
    monkeypatch.setattr(corpus, "build_seed_batch_from_filings", build_batch)
    build_chunking_batch(
        2048,
        provider=DeterministicEmbeddingProvider(),
        parsed_filings=(filing,),
        selection_id="sec-evaluation",
    )
    assert received == [(filing, 2048)]


def test_chunking_respects_the_selected_models_actual_token_limit(monkeypatch):
    """Constrain the requested target using the selected provider's real counter."""

    class SmallModel(DeterministicEmbeddingProvider):
        """Represent a model whose hard window is smaller than the corpus default."""

        @property
        def max_input_tokens(self):
            """Expose the model's small input budget."""
            return 16

        def count_input_tokens(self, text):
            """Expose an independently identifiable model token counter."""
            return len(text.split())

    provider = SmallModel()

    def chunk_filing(filing, config):
        """Inspect the effective model-aware configuration at the chunker boundary."""
        assert config.target_tokens == 16
        assert config.max_tokens == 16
        assert config.token_counter("one two three") == 3
        return []

    def build_batch(filings, *, chunker, on_progress):
        """Exercise the exact chunking callback passed to the seed pipeline."""
        chunker(filings[0])
        return object()

    monkeypatch.setattr(corpus, "chunk_filing", chunk_filing)
    monkeypatch.setattr(corpus, "build_seed_batch_from_filings", build_batch)
    build_chunking_batch(
        2048, provider=provider, selection_id="sec-evaluation", parsed_filings=(object(),)
    )
