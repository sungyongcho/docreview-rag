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


def test_default_pairs_are_exact_and_independent_of_disk(tmp_path):
    """Ordinary fresh start selects eighteen intended pairs, never a registry cross product."""
    draft = acquisition_draft(tmp_path, ())
    expected = {
        ("sec", issuer, year) for issuer in ("NVDA", "AMD") for year in range(2019, 2025)
    } | {("dart", issuer, year) for issuer in ("005930", "000660") for year in range(2022, 2025)}
    assert {(p["registry"], p["issuer"], p["year"]) for p in draft["pairs"]} == expected
    assert len(draft["pairs"]) == 18
    write_selection_catalog(tmp_path)
    assert acquisition_draft(tmp_path, source_inventory(tmp_path)) == draft
    path = tmp_path / "acquisition-draft.json"
    path.write_text(json.dumps({"identifiers": ["NVDA", "AMD"], "years": [2023, 2024]}))
    sample = acquisition_draft(tmp_path, ())
    assert len(sample["pairs"]) == 4
    assert sample["revision"] != draft["revision"]
    path.write_text(json.dumps({"identifiers": [], "years": []}))
    assert acquisition_draft(tmp_path, ())["pairs"] == draft["pairs"]


def test_equivalent_duplicate_primaries_are_ready_and_recorded_once(tmp_path):
    """The reported legacy/download duplicate with the same exact bytes safely collapses."""
    catalog = write_selection_catalog(tmp_path)
    primary = catalog.artifacts[0]
    duplicate = primary.model_copy(
        update={"artifact_id": primary.artifact_id + "-download", "path": "duplicate.html"}
    )
    (tmp_path / duplicate.path).write_bytes(primary.read_bytes(tmp_path))
    catalog.model_copy(update={"artifacts": (*catalog.artifacts, duplicate)}).write(
        tmp_path / "manifest.json"
    )
    before = (tmp_path / "manifest.json").read_bytes()
    assert all(row.ready for row in source_inventory(tmp_path))
    name, selection = record_selection(tmp_path, ("NVDA", "AMD"), (2023, 2024))
    assert len(Manifest.read(tmp_path / name).selected_sources(selection, tmp_path)) == 4
    assert (tmp_path / "manifest.json").read_bytes() == before


def test_conflicting_primary_blocks_readiness_and_execution(tmp_path):
    """Different valid bytes cannot be chosen by catalog order or queued silently."""
    import hashlib

    catalog = write_selection_catalog(tmp_path)
    primary = catalog.artifacts[0]
    raw = b"different valid primary bytes"
    duplicate = primary.model_copy(
        update={
            "artifact_id": primary.artifact_id + "-conflict",
            "path": "conflict.html",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw),
        }
    )
    (tmp_path / duplicate.path).write_bytes(raw)
    catalog.model_copy(update={"artifacts": (*catalog.artifacts, duplicate)}).write(
        tmp_path / "manifest.json"
    )
    blocked = next(
        row for row in source_inventory(tmp_path) if row.document_id == primary.document_id
    )
    assert blocked.on_disk and not blocked.ready
    assert "Conflicting primary sources" in blocked.blocker
    with pytest.raises(ValueError, match="Conflicting primary sources"):
        record_selection(tmp_path, (blocked.issuer,), (blocked.fiscal_year,))
    assert not list(tmp_path.glob("selected-*.json"))


def test_selection_never_scans_other_catalogs(tmp_path):
    """Invalid or overlapping evaluation catalogs do not leak into Build processing."""
    catalog = write_selection_catalog(tmp_path)
    (tmp_path / "evaluation-manifest.json").write_text("invalid unrelated fixture")
    name, _ = record_selection(tmp_path, ("NVDA",), (2024,))
    assert len(Manifest.read(tmp_path / name).documents) == 1
    assert len(source_inventory(tmp_path)) == len(catalog.documents)


@pytest.mark.parametrize(
    "kind,issuer",
    [("acquire_edgar", "MSFT"), ("acquire_dart", "123456"), ("acquire_edgar", "005930")],
)
def test_unknown_acquisition_company_is_rejected_before_queue(kind, issuer):
    """The administrator endpoint cannot bypass the bounded company picker."""
    with pytest.raises(ValueError, match="supported acquisition catalog"):
        AdminCommand(kind, identifiers=(issuer,), years=(2024,))


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
    assert len(resource.acquisition_draft.pairs) == 18
    assert len(resource.acquisition_companies) == 7


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


def test_distinct_filings_require_explicit_document_ids(tmp_path):
    """Multiple filings for one picker pair require a decision before any job starts."""
    catalog = write_selection_catalog(tmp_path)
    original = catalog.documents[0]
    filing_id = original.filing_id[:-6] + "999999"
    duplicate = original.model_copy(
        update={
            "document_id": original.document_id + "-other",
            "filing_id": filing_id,
            "sec": original.sec.model_copy(update={"accession": filing_id}),
        }
    )
    artifact = next(a for a in catalog.artifacts if a.document_id == original.document_id)
    alternate = artifact.model_copy(
        update={
            "document_id": duplicate.document_id,
            "artifact_id": artifact.artifact_id + "-other",
            "path": "other-filing.html",
        }
    )
    (tmp_path / alternate.path).write_bytes(artifact.read_bytes(tmp_path))
    catalog.model_copy(
        update={
            "documents": (*catalog.documents, duplicate),
            "artifacts": (*catalog.artifacts, alternate),
        }
    ).write(tmp_path / "manifest.json")
    rows = [
        row
        for row in source_inventory(tmp_path)
        if row.issuer == original.issuer and row.fiscal_year == original.fiscal_year
    ]
    assert len(rows) == 2 and all(row.ready for row in rows)
    with pytest.raises(ValueError, match="Ambiguous filing identity"):
        record_selection(tmp_path, (original.issuer,), (original.fiscal_year,))
    assert not list(tmp_path.glob("selected-*.json"))
    name, selection_id = record_selection(
        tmp_path,
        (original.issuer,),
        (original.fiscal_year,),
        (original.document_id, duplicate.document_id),
    )
    assert len(Manifest.read(tmp_path / name).selected_sources(selection_id, tmp_path)) == 2


def test_exact_document_ids_reject_a_stale_selection(tmp_path):
    """A removed ID cannot silently become another filing from the same company/year."""
    write_selection_catalog(tmp_path)
    with pytest.raises(ValueError, match="identities changed"):
        record_selection(tmp_path, ("NVDA",), (2024,), ("removed-id",))
    assert not list(tmp_path.glob("selected-*.json"))
