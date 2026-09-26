"""Cached manifest scope is valid only while its backing source remains readable."""

import os

import pytest

from app.api.errors import ApiProblemError
from app.ingestion.sources.models import CorpusIdentity, Manifest
from app.query.resolution import ScopeResolver
from app.retrieval.search.profiles import ServerBM25
from tests.ingestion.support import filing_document


@pytest.fixture
def resolver(tmp_path):
    """Resolve the temporary manifest without permitting database access."""

    def no_database():
        """Manifest caching needs no persistence session."""
        raise AssertionError("Reading the manifest must not use a database")

    return ScopeResolver(
        corpus_root=tmp_path,
        session_factory=no_database,
        bm25=ServerBM25(),
        developer=True,
        secret_values=(),
    )


@pytest.mark.parametrize("failure", ["missing", "permission"])
def test_cached_scope_rejects_lost_manifest_and_recovers(tmp_path, resolver, failure):
    """A previously valid cache cannot hide a removed or unreadable manifest."""
    path = tmp_path / "manifest.json"
    manifest = Manifest(
        corpus=CorpusIdentity(corpus_id="test", name="Test"),
        documents=(filing_document(),),
    )
    manifest.write(path)
    first = resolver.manifest_index()
    assert first.match("NVDA revenue")
    mode = path.stat().st_mode
    try:
        if failure == "missing":
            path.unlink()
        else:
            path.chmod(0)
            if os.access(path, os.R_OK):
                pytest.skip("The current user bypasses file permission restrictions")
            with pytest.raises(PermissionError):
                path.read_bytes()
        with pytest.raises(ApiProblemError) as captured:
            resolver.manifest_index()
        assert captured.value.error.code == "query_scope_unavailable"
        assert captured.value.error.cause == (
            "missing_file" if failure == "missing" else "permission"
        )
    finally:
        if path.exists():
            path.chmod(mode)
    manifest.write(path)
    restored = resolver.manifest_index()
    assert restored is not first
    assert restored.match("NVDA revenue") == first.match("NVDA revenue")


def test_atomic_manifest_replacement_invalidates_same_size_and_mtime(tmp_path, resolver):
    """File identity invalidates cached aliases when replacement preserves size and mtime."""
    path = tmp_path / "manifest.json"
    original = Manifest(
        corpus=CorpusIdentity(corpus_id="test", name="Test"),
        documents=(filing_document(aliases=("FIRST",)),),
    )
    original.write(path)
    before = path.stat()
    first = resolver.manifest_index()
    assert first.match("FIRST revenue")

    replacement = tmp_path / "replacement.json"
    original.model_copy(update={"documents": (filing_document(aliases=("OTHER",)),)}).write(
        replacement
    )
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert replacement.stat().st_size == before.st_size
    replacement.replace(path)

    refreshed = resolver.manifest_index()
    assert not refreshed.match("FIRST revenue")
    assert [match.issuer for match in refreshed.match("OTHER revenue")] == ["NVDA"]
