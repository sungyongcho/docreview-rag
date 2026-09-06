"""Exact selected-source recording preserves user scope and retry references."""

import asyncio
import json

import pytest

from app.config import Settings
from app.corpus_admin import AdminCommand, OperationOutcome, RuntimeCorpusAdminService
from app.ingestion.manifest import Manifest
from app.ingestion.source_selection import acquisition_draft, record_selection, source_inventory
from tests.ingestion.support import write_selection_catalog


def test_selection_records_exact_scope_and_keeps_retry_reference(tmp_path):
    """Changing the draft produces independent immutable inputs for jobs and retries."""
    catalog = write_selection_catalog(tmp_path)
    original = (tmp_path / "manifest.json").read_bytes()
    name, identity = record_selection(tmp_path, ("NVDA", "AMD"), (2023, 2024))
    selected = Manifest.read(tmp_path / name)
    assert len(selected.selected_sources(identity, tmp_path)) == 4
    next_name, next_id = record_selection(tmp_path, ("NVDA",), (2024,))
    assert name != next_name and identity != next_id
    assert len(Manifest.read(tmp_path / next_name).documents) == 1
    assert Manifest.read(tmp_path / name) == selected
    assert (tmp_path / "manifest.json").read_bytes() == original
    assert len(source_inventory(tmp_path)) == len(catalog.documents) == 4
    assert record_selection(tmp_path, ("AMD", "NVDA"), (2024, 2023)) == (name, identity)


@pytest.mark.parametrize("failure", ["missing_file", "unknown_year", "changed_bytes"])
def test_missing_selected_sources_never_create_partial_selection(tmp_path, failure):
    """A partially available draft fails as a whole before job inputs are recorded."""
    catalog = write_selection_catalog(tmp_path)
    artifact = catalog.artifacts[0]
    years = (2023, 2024)
    if failure == "missing_file":
        (tmp_path / artifact.path).unlink()
    elif failure == "changed_bytes":
        (tmp_path / artifact.path).write_text("changed")
    else:
        years = (2022, 2024)
    with pytest.raises(ValueError):
        record_selection(tmp_path, ("NVDA", "AMD"), years)
    assert not list(tmp_path.glob("selected-*.json"))


def test_draft_uses_disk_then_persisted_sample_without_download(tmp_path):
    """No hidden sample defaults exist; a sample preset alone creates no source files."""
    assert acquisition_draft(tmp_path, ()) == {"identifiers": [], "years": []}
    (tmp_path / "acquisition-draft.json").write_text(
        json.dumps({"identifiers": ["NVDA", "AMD"], "years": [2023, 2024]})
    )
    assert acquisition_draft(tmp_path, ())["identifiers"] == ["NVDA", "AMD"]
    catalog = write_selection_catalog(tmp_path)
    for artifact in catalog.artifacts:
        if artifact.document_id != "NVDA-FY2024":
            (tmp_path / artifact.path).unlink()
    assert acquisition_draft(tmp_path, source_inventory(tmp_path)) == {
        "identifiers": ["NVDA"],
        "years": [2024],
    }


def test_ingest_selected_job_uses_existing_manifest_job_contract(tmp_path):
    """The queue and retry preserve the recorded reference rather than rereading the draft."""
    write_selection_catalog(tmp_path)
    calls = []

    async def scenario():
        """Use an isolated in-memory queue, with no database or actual parsing."""

        async def runner(command, publish):
            """Capture resolved command references and fail once to exercise retry."""
            calls.append(command)
            if len(calls) == 1:
                raise ValueError("fixture parse failure")
            return OperationOutcome(
                "done", manifest=command.manifest, selection_id=command.selection_id
            )

        service = RuntimeCorpusAdminService(
            settings=Settings(corpus_dir=tmp_path), operation_runner=runner
        )
        job = await service.enqueue(
            AdminCommand("ingest_selected", identifiers=("NVDA",), years=(2024,))
        )
        await service._queue.join()
        assert job.command.kind == "ingest_manifest"
        assert job.command.manifest and job.command.selection_id
        await service.retry(job.job_id)
        await service._queue.join()
        assert calls[0] == calls[1]
        assert service._resolve_manifest(job.command.manifest).exists()

    asyncio.run(scenario())


def test_source_snapshot_accepts_the_strict_api_resource(tmp_path):
    """The live snapshot serializes disk identities and server drafts without coercion failures."""
    from dataclasses import asdict
    from unittest.mock import AsyncMock

    from app.api.admin_schemas import CorpusSnapshotResource

    write_selection_catalog(tmp_path)
    service = RuntimeCorpusAdminService(settings=Settings(corpus_dir=tmp_path))
    service._schema_state = AsyncMock(return_value=("empty", "empty", set()))
    snapshot = asyncio.run(service.snapshot())
    resource = CorpusSnapshotResource.model_validate(asdict(snapshot))
    assert len(resource.sources) == 4
    assert resource.acquisition_draft.identifiers == ("AMD", "NVDA")


def test_updated_document_metadata_creates_new_immutable_job_selection(tmp_path):
    """Changed filing metadata does not collide with an earlier retryable source selection."""
    catalog = write_selection_catalog(tmp_path)
    first_name, _ = record_selection(tmp_path, ("NVDA",), (2024,))
    documents = tuple(
        document.model_copy(update={"aliases": ("Updated company name",)})
        for document in catalog.documents
    )
    catalog.model_copy(update={"documents": documents}).write(tmp_path / "manifest.json")
    second_name, _ = record_selection(tmp_path, ("NVDA",), (2024,))
    assert first_name != second_name
    assert Manifest.read(tmp_path / first_name).documents[0].aliases != ("Updated company name",)
