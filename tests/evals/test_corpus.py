"""Corpus preparation shared by the chunking arms of one evaluation run."""

from typing import cast

import pytest

from app.config import Settings
from app.db.models import CONTENT_TSV_SQL, LANGUAGE_FORMAT_CHECK_SQL, LEXICAL_TEXT_CHECK_SQL
from app.evals import corpus
from app.evals.corpus import _TEMPORARY_CORPUS_DDL, build_chunking_batch, load_chunking_filings
from app.ingestion.parser import ParsedFiling


def test_build_chunking_batch_reuses_supplied_filings_without_loading_manifest(monkeypatch):
    """Reuse parsed filings instead of re-reading the manifest."""
    parsed_filings = (cast(ParsedFiling, object()),)
    expected_batch = object()
    calls = []

    def build_from_filings(filings, *, chunker):
        calls.append(filings)
        assert callable(chunker)
        return expected_batch

    monkeypatch.setattr(corpus, "build_seed_batch_from_filings", build_from_filings)
    monkeypatch.setattr(
        corpus,
        "load_manifest",
        lambda _path: pytest.fail("manifest must not be loaded when parsed filings are supplied"),
    )

    result = build_chunking_batch(500, parsed_filings=parsed_filings)

    assert result is expected_batch
    assert calls == [parsed_filings]


def test_load_chunking_filings_parses_the_manifest_once(monkeypatch, tmp_path):
    """Parse the configured manifest once for the whole run."""
    manifest = tmp_path / "manifest.json"
    entries = [{"ticker": "NVDA"}, {"ticker": "AMD"}]
    parsed_filings = (object(), object())
    calls = []

    monkeypatch.setattr(corpus, "load_manifest", lambda path: entries if path == manifest else None)

    def parse_once(received, *, expected_documents):
        calls.append((received, expected_documents))
        return parsed_filings

    monkeypatch.setattr(corpus, "parse_seed_filings", parse_once)
    settings = cast(Settings, type("SettingsStub", (), {"corpus_dir": tmp_path})())

    result = load_chunking_filings(settings=settings)

    assert result is parsed_filings
    assert calls == [(entries, 20)]


def test_the_temporary_schema_keeps_every_populated_corpus_constraint():
    """Reject in the isolated corpus whatever the populated corpus would reject."""
    rendered = "\n".join(
        statement.format(
            dimensions=384,
            content_tsv_sql=CONTENT_TSV_SQL,
            language_format_check_sql=LANGUAGE_FORMAT_CHECK_SQL,
            lexical_text_check_sql=LEXICAL_TEXT_CHECK_SQL,
        )
        for statement in _TEMPORARY_CORPUS_DDL
    )

    for constraint in (
        "ck_documents_parse_status",
        "ck_documents_source_length_positive",
        "ck_documents_source_sha256_format",
        "ck_documents_language_format",
        "uq_doc_ordinal",
        "ck_chunks_ordinal_nonnegative",
        "ck_chunks_kind",
        "ck_chunks_language_format",
        "ck_chunks_lexical_text_language",
        "ck_chunks_start_nonnegative",
        "ck_chunks_span_order",
        "ck_chunks_source_sha256_format",
        "ck_chunk_terms_tf_positive",
        "ck_chunk_lengths_positive",
        "ck_lexeme_stats_df_positive",
        "ck_bm25_corpus_stats_language_format",
    ):
        assert constraint in rendered
    # The temporary chunks table indexes with the exact SQL the live table computes.
    assert CONTENT_TSV_SQL in rendered
    assert LEXICAL_TEXT_CHECK_SQL in rendered
    assert "embedding vector(384)" in rendered
    assert "CREATE INDEX ON chunks (doc_id)" in rendered
