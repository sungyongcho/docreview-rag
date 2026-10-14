"""Source availability, input provenance and ingestion transaction boundaries."""

import asyncio
from dataclasses import asdict, replace
from types import SimpleNamespace

import pytest

from app.api.corpus.routes import _corpus_snapshot
from app.config import Settings
from app.corpus_admin.service import RuntimeCorpusAdminService
from app.ingestion.persistence import persist_seed_batch
from app.ingestion.pipeline import SeedBatch, filing_records
from app.ingestion.sources.deletion import SourceDeletion
from app.ingestion.sources.models import Manifest
from app.ingestion.sources.publication import publish_acquired
from app.ingestion.sources.selection import record_selection
from tests.ingestion.seed.support import sample_chunks, sample_filing
from tests.ingestion.support import acquired_filing
from tests.live_postgres import isolated_session_factory


def _publish(root, payload=b"first raw filing"):
    """Acquire a known synthetic filing through the real publication boundary."""
    document = sample_filing().source.document
    return publish_acquired(
        root / "manifest.json",
        (acquired_filing(root, document=document, payload=payload),),
        selection_id="downloaded",
        selected_document_ids=(document.document_id,),
    )


def _selected_batch(root):
    """Pin the current input, using synthetic parser output with a different text hash."""
    document = sample_filing().source.document
    name, selection_id = record_selection(
        root, (document.issuer,), (document.fiscal_year,), (document.document_id,)
    )
    source = Manifest.read(root / name).selected_sources(selection_id, root)[0]
    filing = replace(sample_filing(), source=source)
    reference, chunks = filing_records(filing, sample_chunks())
    return SeedBatch((reference,), chunks, (filing,), selection_id=selection_id)


@pytest.mark.parametrize("schema", ["empty", "drifted", "unavailable"])
def test_uningested_or_unknown_requires_known_database_state(tmp_path, monkeypatch, schema):
    """A source on disk is not proof of a successful or current database ingestion."""
    _publish(tmp_path)
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))

    async def schema_state():
        """Report schema availability without connecting to an application database."""
        return schema, schema, set()

    monkeypatch.setattr(service._inspector, "schema_state", schema_state)
    snapshot = asyncio.run(service.snapshot())
    assert snapshot.sources[0].ready
    assert snapshot.sources[0].ingestion_status == (
        "not_ingested" if schema == "empty" else "unknown"
    )


@pytest.mark.live_postgres
def test_source_changes_and_failed_reingestion_keep_committed_provenance(tmp_path):
    """Read live DB state through snapshots across publication, rollback and old-input reruns."""

    async def exercise():
        """Use one isolated PostgreSQL schema and never the application's database."""
        async with isolated_session_factory() as factory:
            service = RuntimeCorpusAdminService(
                settings=Settings(corpus_dir=tmp_path),
                session_factory=factory,
                engine=factory.kw["bind"],
            )
            _publish(tmp_path)
            first = _selected_batch(tmp_path)
            assert first.filings[0].source_sha256 != first.filings[0].source.artifact.sha256
            initial = await service.snapshot()
            assert initial.sources[0].ingestion_status == "not_ingested"
            async with factory() as session:
                await persist_seed_batch(session, first)
            current = await service.snapshot()
            assert current.sources[0].ingestion_status == "current"
            assert current.documents[0].ingestion_status == "current"
            assert current.documents[0].chunk_count == 2

            _publish(tmp_path, b"second raw filing")
            second = _selected_batch(tmp_path)
            stale = await service.snapshot()
            assert stale.sources[0].ready
            assert stale.sources[0].ingestion_status == "stale"
            assert stale.documents[0].ingestion_status == "stale"
            filtered = await service.snapshot(issuer="AMD")
            assert not filtered.documents
            assert filtered.sources[0].ingestion_status == "stale"

            def fail_after_parse_write(progress):
                """Abort after provenance updates, proving the transaction rolls them back."""
                if progress.stage == "chunks":
                    raise RuntimeError("simulated ingest failure")

            async with factory() as session:
                with pytest.raises(RuntimeError, match="simulated ingest failure"):
                    await persist_seed_batch(session, second, on_progress=fail_after_parse_write)
            failed = await service.snapshot()
            assert failed.sources[0].ingestion_status == "stale"
            assert failed.documents[0].chunk_count == 2
            async with factory() as session:
                await persist_seed_batch(session, second)
            assert (await service.snapshot()).sources[0].ingestion_status == "current"
            async with factory() as session:
                await persist_seed_batch(session, first)
            assert (await service.snapshot()).sources[0].ingestion_status == "stale"

            # Metadata changes alone require reingestion, even when the bytes match.
            async with factory() as session:
                await persist_seed_batch(session, second)
            manifest = Manifest.read(tmp_path / "manifest.json")
            document = manifest.documents[0]
            changed = document.model_copy(update={"aliases": ("New company alias",)})
            manifest.model_copy(update={"documents": (changed,)}).write(tmp_path / "manifest.json")
            assert (await service.snapshot()).sources[0].ingestion_status == "stale"
            async with factory() as session:
                await persist_seed_batch(session, _selected_batch(tmp_path))
            assert (await service.snapshot()).sources[0].ingestion_status == "current"

            primary = next(a for a in manifest.artifacts if a.role == "primary")
            path = tmp_path / primary.path
            original = path.read_bytes()
            path.write_bytes(b"x" * len(original))
            corrupt = await service.snapshot()
            assert corrupt.sources[0].on_disk and not corrupt.sources[0].ready
            assert corrupt.sources[0].ingestion_status == "unknown"
            assert corrupt.documents[0].ingestion_status == "unknown"
            path.write_bytes(original)
            deletion = SourceDeletion(tmp_path)
            preview = deletion.preview((document.document_id,))
            deletion.reserve(preview["token"])
            deletion.execute(preview["token"])
            deleted = await service.snapshot()
            assert not deleted.sources[0].on_disk
            assert deleted.sources[0].ingestion_status == "unknown"
            assert deleted.documents[0].chunk_count == 2
            assert deleted.documents[0].ingestion_status == "unknown"

            # Verify the actual typed API boundary includes both independent states.
            dependencies = SimpleNamespace(
                corpus=service, runtime=SimpleNamespace(company_names=lambda: {})
            )
            resource = await _corpus_snapshot(dependencies)
            assert resource.sources[0].ingestion_status == "unknown"
            assert resource.documents[0].ingestion_status == "unknown"
            assert asdict(deleted.sources[0])["ready"] is False

    asyncio.run(exercise())


def test_failed_document_read_never_marks_sources_not_ingested(tmp_path, monkeypatch):
    """A successful count probe cannot turn a failed provenance query into an empty DB."""
    _publish(tmp_path)
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))

    async def compatible():
        """Expose the compatible schema before the document query fails."""
        return "compatible", "ok", {"documents", "chunks"}

    async def counts(_tables):
        """Keep the count probe independent from the failing row query."""
        return 1, 2, 0, False

    async def unavailable(_tables):
        """Simulate the database becoming unavailable after the status probe."""
        raise OSError("connection lost")

    monkeypatch.setattr(service._inspector, "schema_state", compatible)
    monkeypatch.setattr(service._inspector, "_counts", counts)
    monkeypatch.setattr(service._inspector, "_documents", unavailable)
    snapshot = asyncio.run(service.snapshot())
    assert snapshot.status.schema_status == "unavailable"
    assert snapshot.sources[0].ready
    assert snapshot.sources[0].ingestion_status == "unknown"
