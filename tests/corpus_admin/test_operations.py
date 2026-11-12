"""Corpus operation dispatch, manifest resolution and embedding postcondition tests."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from pydantic import SecretStr
import pytest

from app.config import Settings
import app.corpus_admin.operations as operations
from app.corpus_admin.operations import CorpusOperations
from app.corpus_admin.service import RuntimeCorpusAdminService
from app.corpus_admin.types import AdminCommand
from app.db.session_factory import SessionFactory
from app.retrieval.embedding.provider import DeterministicEmbeddingProvider
from app.retrieval.indexing.embeddings import EmbeddingBackfillResult
from tests.corpus_admin.support import write_manifest


def test_backfill_refuses_false_success_when_committed_count_does_not_change(
    monkeypatch, tmp_path: Path
) -> None:
    """Fail the job when an UPDATE reports rows but the database postcondition disagrees."""

    class FakeSession:
        """Minimal async context used by monkeypatched count and backfill boundaries."""

        async def __aenter__(self):
            """Return the fake session."""
            return self

        async def __aexit__(self, *args):
            """Close without suppressing errors."""
            return False

    states = iter(((0, 3), (0, 3)))

    async def fake_state(session, provider, document_ids):
        """Report no committed change before or after the claimed update."""
        del session, provider, document_ids
        return next(states)

    async def fake_embed(session, provider, *, on_batch, document_ids, on_usage=None):
        """Claim three stored rows without changing persistence."""
        del session, provider, on_batch, document_ids
        return EmbeddingBackfillResult(selected=3, embedded=3, skipped_stale=0, batches=1)

    async def fake_bootstrap(engine):
        """Avoid database setup in the focused postcondition test."""
        del engine

    async def fake_writable(self):
        """Treat the focused fake schema as writable."""
        del self

    monkeypatch.setattr(operations, "_embedding_state", fake_state)
    monkeypatch.setattr(operations, "embed_missing_chunks", fake_embed)
    monkeypatch.setattr(operations, "bootstrap_schema", fake_bootstrap)
    monkeypatch.setattr(CorpusOperations, "_assert_writable_schema", fake_writable)
    service = RuntimeCorpusAdminService(
        settings=Settings(corpus_dir=tmp_path),
        session_factory=cast(SessionFactory, FakeSession),
        embedding_provider=DeterministicEmbeddingProvider(),
    )

    with pytest.raises(RuntimeError, match="reported rows were not committed"):
        asyncio.run(
            service._operations.run(
                AdminCommand("backfill_embeddings"),
                lambda progress: None,
            )
        )


def test_manifest_resolution_is_confined_to_valid_root_entries(tmp_path: Path) -> None:
    """Accept enumerated manifests and reject traversal or arbitrary JSON files."""
    write_manifest(tmp_path)
    (tmp_path / "notes.json").write_text("[]\n", encoding="utf-8")
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))

    assert service._operations._resolve_manifest("manifest.json") == tmp_path / "manifest.json"
    with pytest.raises(ValueError, match="corpus root"):
        service._operations._resolve_manifest("../outside.json")
    with pytest.raises(ValueError, match="selectable"):
        service._operations._resolve_manifest("notes.json")


def test_ingestion_rejects_unknown_selection_before_parsing(tmp_path, monkeypatch):
    """Reject an unlisted selection before invoking any parser or persistence."""
    write_manifest(tmp_path)
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))

    async def writable():
        """Isolate manifest validation from live database readiness."""
        return None

    monkeypatch.setattr(service._operations, "_assert_writable_schema", writable)
    with pytest.raises(ValueError, match="unknown processing selection"):
        asyncio.run(
            service._operations.run(
                AdminCommand("ingest_manifest", manifest="manifest.json", selection_id="missing"),
                lambda progress: None,
            )
        )


@pytest.mark.parametrize("registry", ["sec", "dart"])
def test_acquisition_returns_common_manifest_selection(tmp_path, monkeypatch, registry):
    """Forward adapter provenance without creating a second catalog."""
    from types import SimpleNamespace

    service = RuntimeCorpusAdminService(
        settings=Settings(corpus_dir=tmp_path, dart_api_key=SecretStr("test"))
    )

    async def writable():
        """Isolate acquisition dispatch from database readiness."""
        return None

    async def no_schema():
        """Report a database with no corpus tables, which records no filing versions."""
        return "empty", "No corpus tables exist yet.", set()

    async def acquire(*args, **kwargs):
        """Return the canonical acquisition contract without a network call."""
        return SimpleNamespace(
            fetched=(object(),),
            archived=(object(),),
            manifest="manifest.json",
            selection_id="selected",
        )

    monkeypatch.setattr(service._operations, "_assert_writable_schema", writable)
    monkeypatch.setattr(service._inspector, "schema_state", no_schema)
    monkeypatch.setattr(
        operations, "acquire_edgar" if registry == "sec" else "acquire_dart", acquire
    )
    result = asyncio.run(
        service._operations.run(
            AdminCommand(
                "acquire_edgar" if registry == "sec" else "acquire_dart",
                identifiers=("NVDA" if registry == "sec" else "005930",),
                years=(2024,),
            ),
            lambda progress: None,
        )
    )
    assert result.manifest == "manifest.json"
    assert result.selection_id == "selected"
    assert list(tmp_path.iterdir()) == []


def test_backfill_uses_the_exact_selected_document_ids(tmp_path, monkeypatch):
    """Constrain counting and embedding to the same explicit processing selection."""
    from contextlib import asynccontextmanager

    write_manifest(tmp_path)
    calls = []
    states = iter(((0, 1), (1, 0)))

    @asynccontextmanager
    async def sessions():
        """Isolate operation dispatch from database persistence."""
        yield object()

    async def writable():
        """Bypass schema I/O for the argument-contract test."""
        return None

    async def bootstrap(engine):
        """Keep the schema boundary free of database calls."""
        return None

    async def state(session, provider, document_ids):
        """Record exactly the documents whose readiness is measured."""
        calls.append(document_ids)
        return next(states)

    async def embed(session, provider, *, on_batch, document_ids, on_usage=None):
        """Verify the backfill uses the identical selection."""
        assert document_ids == ("nvda-2024",)
        return EmbeddingBackfillResult(selected=1, embedded=1, skipped_stale=0, batches=1)

    service = RuntimeCorpusAdminService(
        settings=Settings(corpus_dir=tmp_path),
        session_factory=cast(SessionFactory, sessions),
        embedding_provider=DeterministicEmbeddingProvider(),
    )
    monkeypatch.setattr(service._operations, "_assert_writable_schema", writable)
    monkeypatch.setattr(operations, "bootstrap_schema", bootstrap)
    monkeypatch.setattr(operations, "_embedding_state", state)
    monkeypatch.setattr(operations, "embed_missing_chunks", embed)
    result = asyncio.run(
        service._operations.run(
            AdminCommand("backfill_embeddings", manifest="manifest.json", selection_id="selected"),
            lambda progress: None,
        )
    )
    assert "Embedded 1" in result.summary
    assert calls == [("nvda-2024",), ("nvda-2024",)]


def test_acquisition_is_independent_of_corpus_schema_writes(tmp_path, monkeypatch):
    """File acquisition can proceed while incompatible corpus indexing stays blocked."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))
    blocked = AsyncMock(side_effect=RuntimeError("schema blocked"))
    acquire = AsyncMock(
        return_value=SimpleNamespace(
            fetched=("filing",), manifest="manifest.json", selection_id="selected"
        )
    )
    drifted = AsyncMock(return_value=("drifted", "The schema is incomplete.", set()))
    monkeypatch.setattr(service._operations, "_assert_writable_schema", blocked)
    monkeypatch.setattr(service._inspector, "schema_state", drifted)
    monkeypatch.setattr(operations, "acquire_edgar", acquire)
    result = asyncio.run(
        service._operations.run(
            AdminCommand("acquire_edgar", identifiers=("NVDA",), years=(2024,)),
            lambda progress: None,
        )
    )
    assert result.selection_id == "selected"
    blocked.assert_not_awaited()
    drifted.assert_awaited_once()
    with pytest.raises(RuntimeError, match="schema blocked"):
        asyncio.run(service._operations.run(AdminCommand("rebuild_bm25"), lambda progress: None))


@pytest.mark.live_postgres
@pytest.mark.parametrize("download", ["succeeds", "fails"])
def test_acquisition_records_listed_filings_even_when_a_download_fails(
    tmp_path, monkeypatch, download
):
    """An amendment the catalog lists holds its report period whether or not it was fetched."""
    from sqlalchemy import select

    from app.db.models import FilingVersion
    from app.ingestion.persistence import persist_seed_batch
    from app.ingestion.sources.models import CorpusIdentity, Manifest
    from tests.amendments.support import amendment_document, batch, eligible, parsed, sec_document
    from tests.live_postgres import isolated_session_factory

    report, amendment = sec_document(18), amendment_document(21)

    async def acquire(manifest_path, **kwargs):
        """List the amendment in the catalog, then finish or fail like a download would."""
        Manifest(
            corpus=CorpusIdentity(corpus_id="filings", name="Filing corpus"),
            documents=(report, amendment),
        ).write(manifest_path)
        if download == "fails":
            raise RuntimeError("download failed")
        return SimpleNamespace(fetched=(), manifest="manifest.json", selection_id="selected")

    async def exercise() -> None:
        """Index the report, run the acquisition, then read what the database knows."""
        async with isolated_session_factory() as factory:
            async with factory() as session:
                await persist_seed_batch(session, batch(parsed(report, ("1", "7"))))
            service = RuntimeCorpusAdminService(
                settings=Settings(corpus_dir=tmp_path),
                engine=factory.kw["bind"],
                session_factory=factory,
            )
            monkeypatch.setattr(operations, "acquire_edgar", acquire)
            command = AdminCommand("acquire_edgar", identifiers=("AMD",), years=(2025,))
            if download == "fails":
                with pytest.raises(RuntimeError, match="download failed"):
                    await service._operations.run(command, lambda progress: None)
            else:
                await service._operations.run(command, lambda progress: None)
            async with factory() as session:
                kinds = await session.scalars(select(FilingVersion.kind))
                assert sorted(kinds) == ["amendment", "report"]
                assert await eligible(session) == set()

    asyncio.run(exercise())
