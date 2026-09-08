"""Exact selected-source recording preserves user scope and retry references."""

import asyncio
import json

import pytest

from app.config import Settings
from app.corpus_admin import AdminCommand, OperationOutcome, RuntimeCorpusAdminService
from app.ingestion.manifest import Manifest
from app.ingestion.source_publication import fixed_path, publish_acquired
from app.ingestion.source_selection import acquisition_draft, record_selection, source_inventory
from tests.ingestion.support import (
    acquired_filing,
    filing_document,
    selected_document_ids,
    write_selection_catalog,
)


def test_selection_records_exact_scope_and_keeps_retry_reference(tmp_path):
    """Changing the draft produces independent immutable inputs for jobs and retries."""
    catalog = write_selection_catalog(tmp_path)
    original = (tmp_path / "manifest.json").read_bytes()
    name, identity = record_selection(
        tmp_path,
        ("NVDA", "AMD"),
        (2023, 2024),
        selected_document_ids(tmp_path, ("NVDA", "AMD"), (2023, 2024)),
    )
    selected = Manifest.read(tmp_path / name)
    assert len(selected.selected_sources(identity, tmp_path)) == 4
    next_name, next_id = record_selection(
        tmp_path, ("NVDA",), (2024,), selected_document_ids(tmp_path, ("NVDA",), (2024,))
    )
    assert name != next_name and identity != next_id
    assert len(Manifest.read(tmp_path / next_name).documents) == 1
    assert Manifest.read(tmp_path / name) == selected
    assert (tmp_path / "manifest.json").read_bytes() == original
    assert len(source_inventory(tmp_path)) == len(catalog.documents) == 4
    assert record_selection(
        tmp_path,
        ("AMD", "NVDA"),
        (2024, 2023),
        selected_document_ids(tmp_path, ("AMD", "NVDA"), (2024, 2023)),
    ) == (name, identity)


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
        record_selection(
            tmp_path,
            ("NVDA", "AMD"),
            years,
            tuple(document.document_id for document in catalog.documents),
        )
    assert not list(tmp_path.glob("selected-*.json"))


def test_default_pairs_are_exact_and_independent_of_disk(tmp_path):
    """Only a missing draft uses defaults; persisted pairs are explicit, including empty scope."""
    draft = acquisition_draft(tmp_path)
    expected = {
        ("sec", issuer, year) for issuer in ("NVDA", "AMD") for year in range(2019, 2025)
    } | {("dart", issuer, year) for issuer in ("005930", "000660") for year in range(2022, 2025)}
    assert {(p["registry"], p["issuer"], p["year"]) for p in draft["pairs"]} == expected
    assert len(draft["pairs"]) == 18
    write_selection_catalog(tmp_path)
    assert acquisition_draft(tmp_path) == draft
    path = tmp_path / "acquisition-draft.json"
    pairs = [
        {"registry": "sec", "issuer": issuer, "year": year}
        for issuer in ("NVDA", "AMD")
        for year in (2023, 2024)
    ]
    path.write_text(
        json.dumps({"identifiers": ["NVDA", "AMD"], "years": [2023, 2024], "pairs": pairs})
    )
    sample = acquisition_draft(tmp_path)
    assert sample["pairs"] == pairs and sample["revision"] != draft["revision"]
    path.write_text(json.dumps({"identifiers": [], "years": [], "pairs": []}))
    assert acquisition_draft(tmp_path)["pairs"] == []
    path.write_text(json.dumps({"identifiers": ["NVDA"], "years": [2024]}))
    with pytest.raises(ValueError):
        acquisition_draft(tmp_path)


@pytest.mark.parametrize("duplicate_state", ["valid", "missing", "corrupt"])
def test_equivalent_duplicate_primaries_are_rejected_without_changing_copies(
    tmp_path, duplicate_state
):
    """Current inventory and parsing refuse duplicate registrations even when bytes match."""
    catalog = write_selection_catalog(tmp_path)
    primary = catalog.artifacts[0]
    duplicate = primary.model_copy(
        update={"artifact_id": primary.artifact_id + "-download", "path": "duplicate.html"}
    )
    (tmp_path / duplicate.path).write_bytes(primary.read_bytes(tmp_path))
    catalog.model_copy(update={"artifacts": (*catalog.artifacts, duplicate)}).write(
        tmp_path / "manifest.json"
    )
    if duplicate_state == "missing":
        (tmp_path / duplicate.path).unlink()
    elif duplicate_state == "corrupt":
        (tmp_path / duplicate.path).write_bytes(b"damaged duplicate")
    before = (tmp_path / "manifest.json").read_bytes()
    row = next(row for row in source_inventory(tmp_path) if row.document_id == primary.document_id)
    assert not row.ready and not row.can_redownload
    duplicate_before = (
        (tmp_path / duplicate.path).read_bytes() if (tmp_path / duplicate.path).exists() else None
    )
    with pytest.raises(ValueError, match="Conflicting primary sources"):
        record_selection(
            tmp_path,
            ("NVDA", "AMD"),
            (2023, 2024),
            selected_document_ids(tmp_path, ("NVDA", "AMD"), (2023, 2024)),
        )
    assert (
        (tmp_path / duplicate.path).read_bytes() if (tmp_path / duplicate.path).exists() else None
    ) == duplicate_before
    assert not list(tmp_path.glob("selected-*.json"))
    assert (tmp_path / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("latest_state", ["valid", "missing", "corrupt"])
def test_conflicting_primary_blocks_readiness_and_execution(tmp_path, latest_state):
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
    if latest_state == "missing":
        (tmp_path / duplicate.path).unlink()
    elif latest_state == "corrupt":
        (tmp_path / duplicate.path).write_bytes(b"damaged latest revision")
    blocked = next(
        row for row in source_inventory(tmp_path) if row.document_id == primary.document_id
    )
    assert blocked.on_disk and not blocked.ready and not blocked.can_redownload
    assert "Conflicting primary sources" in blocked.blocker
    with pytest.raises(ValueError, match="Conflicting primary sources"):
        record_selection(
            tmp_path,
            (blocked.issuer,),
            (blocked.fiscal_year,),
            selected_document_ids(tmp_path, (blocked.issuer,), (blocked.fiscal_year,)),
        )
    assert not list(tmp_path.glob("selected-*.json"))


def test_selection_never_scans_other_catalogs(tmp_path):
    """Invalid or overlapping evaluation catalogs do not leak into Build processing."""
    catalog = write_selection_catalog(tmp_path)
    (tmp_path / "evaluation-manifest.json").write_text("invalid unrelated fixture")
    name, _ = record_selection(
        tmp_path, ("NVDA",), (2024,), selected_document_ids(tmp_path, ("NVDA",), (2024,))
    )
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
            AdminCommand(
                "ingest_selected",
                identifiers=("NVDA",),
                years=(2024,),
                document_ids=selected_document_ids(tmp_path, ("NVDA",), (2024,)),
            )
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
    first_name, _ = record_selection(
        tmp_path, ("NVDA",), (2024,), selected_document_ids(tmp_path, ("NVDA",), (2024,))
    )
    documents = tuple(
        document.model_copy(update={"aliases": ("Updated company name",)})
        for document in catalog.documents
    )
    catalog.model_copy(update={"documents": documents}).write(tmp_path / "manifest.json")
    second_name, _ = record_selection(
        tmp_path, ("NVDA",), (2024,), selected_document_ids(tmp_path, ("NVDA",), (2024,))
    )
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
            "path": fixed_path(duplicate.registry, duplicate.filing_id, "primary"),
        }
    )
    (tmp_path / alternate.path).parent.mkdir(parents=True, exist_ok=True)
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
    assert len(rows) == 2 and all(row.ready and not row.can_redownload for row in rows)
    with pytest.raises(ValueError):
        record_selection(tmp_path, (original.issuer,), (original.fiscal_year,), ())
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


@pytest.mark.parametrize("failure", ["missing", "corrupt", "unregistered"])
def test_unavailable_single_identity_can_be_downloaded_again(tmp_path, failure):
    """Only a single filing identity with no verified primary exposes download recovery."""
    catalog = write_selection_catalog(tmp_path)
    artifact = catalog.artifacts[0]
    if failure == "missing":
        (tmp_path / artifact.path).unlink()
    elif failure == "corrupt":
        (tmp_path / artifact.path).write_bytes(b"damaged primary")
    else:
        catalog.model_copy(
            update={"artifacts": tuple(a for a in catalog.artifacts if a != artifact)}
        ).write(tmp_path / "manifest.json")
    row = next(r for r in source_inventory(tmp_path) if r.document_id == artifact.document_id)
    assert row.on_disk is (failure != "missing")
    assert not row.ready and row.can_redownload
    with pytest.raises(ValueError, match="Download it again in Filings"):
        record_selection(
            tmp_path,
            (row.issuer,),
            (row.fiscal_year,),
            selected_document_ids(tmp_path, (row.issuer,), (row.fiscal_year,)),
        )
    assert not list(tmp_path.glob("selected-*.json"))


def test_existing_acquisition_repairs_a_corrupt_source_at_its_stable_path(tmp_path, monkeypatch):
    """Acquisition restores one verified original at the stable path for its exact filing."""
    from unittest.mock import AsyncMock

    from app.ingestion.edgar_api import acquire_edgar

    catalog = write_selection_catalog(tmp_path)
    artifact = catalog.artifacts[0]
    document = next(d for d in catalog.documents if d.document_id == artifact.document_id)
    payload = artifact.read_bytes(tmp_path)
    (tmp_path / artifact.path).write_bytes(b"damaged source")
    monkeypatch.setattr("app.ingestion.edgar_api.discover", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.ingestion.edgar_api.fetch_document", AsyncMock(return_value=payload))
    result = asyncio.run(
        acquire_edgar(
            tmp_path / "manifest.json",
            tickers=(document.issuer,),
            years=(document.fiscal_year,),
            user_agent="DocReview tests tests@example.com",
        )
    )
    assert len(result.fetched) == 1
    row = next(r for r in source_inventory(tmp_path) if r.document_id == document.document_id)
    assert row.on_disk and row.ready and not row.can_redownload and row.blocker is None
    name, selection = record_selection(
        tmp_path,
        (document.issuer,),
        (document.fiscal_year,),
        selected_document_ids(tmp_path, (document.issuer,), (document.fiscal_year,)),
    )
    selected = Manifest.read(tmp_path / name).selected_sources(selection, tmp_path)
    assert len(selected) == 1 and selected[0].read().encode() == payload
    current = [
        a
        for a in Manifest.read(tmp_path / "manifest.json").artifacts
        if a.document_id == document.document_id and a.role == "primary"
    ]
    assert len(current) == 1
    assert current[0].path == f"sec/{document.filing_id}/primary.html"
    assert current[0].sha256 == artifact.sha256


@pytest.fixture
def registered_dart_archive(tmp_path):
    """Publish the actual producer's current ZIP/XML bundle in a disposable catalog."""
    filing = acquired_filing(
        tmp_path,
        document=filing_document(registry="dart"),
        payload=b"<DOCUMENT>synthetic DART input</DOCUMENT>",
    )
    catalog = publish_acquired(
        tmp_path / "manifest.json",
        [filing],
        selection_id="download",
        selected_document_ids=[filing.document.document_id],
    )
    return catalog, next(a for a in catalog.artifacts if a.role == "archive")


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_registered_archive_inventory_cache_and_integrity_gate(
    tmp_path, monkeypatch, registered_dart_archive, damage
):
    """Inventory caches unchanged ZIPs but detects damage and blocks new parse inputs."""
    from app.ingestion.manifest import SourceArtifact

    catalog, archive = registered_dart_archive
    original = SourceArtifact.read_bytes
    reads = []

    def counted(self, root):
        """Observe real integrity checks without replacing source validation."""
        reads.append(self.path)
        return original(self, root)

    monkeypatch.setattr(SourceArtifact, "read_bytes", counted)
    assert source_inventory(tmp_path)[0].ready
    assert len(reads) == 2
    assert source_inventory(tmp_path)[0].ready
    assert len(reads) == 2
    path = tmp_path / archive.path
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"x" * archive.byte_length)
    row = source_inventory(tmp_path)[0]
    assert row.on_disk and not row.ready and row.can_redownload
    assert "Registered DART archive" in row.blocker and archive.path in row.blocker
    assert len(reads) == (2 if damage == "missing" else 3)
    assert not source_inventory(tmp_path)[0].ready
    assert len(reads) == (2 if damage == "missing" else 3)
    document = catalog.documents[0]
    with pytest.raises(ValueError, match="Registered DART archive"):
        record_selection(
            tmp_path, (document.issuer,), (document.fiscal_year,), (document.document_id,)
        )
    assert not list(tmp_path.glob("selected-*.json"))


def test_dart_archive_registration_is_required_before_parsing(tmp_path, registered_dart_archive):
    """A missing ZIP registration is an incomplete bundle, never an XML-only fallback."""
    catalog, archive = registered_dart_archive
    catalog.model_copy(
        update={"artifacts": tuple(a for a in catalog.artifacts if a != archive)}
    ).write(tmp_path / "manifest.json")
    (tmp_path / archive.path).unlink()
    row = source_inventory(tmp_path)[0]
    assert row.on_disk and not row.ready and row.can_redownload
    document = catalog.documents[0]
    primary = next(a for a in catalog.artifacts if a.role == "primary")
    before = primary.read_bytes(tmp_path)
    with pytest.raises(ValueError, match="Registered DART archive"):
        record_selection(
            tmp_path, (document.issuer,), (document.fiscal_year,), (document.document_id,)
        )
    assert primary.read_bytes(tmp_path) == before
    assert not list(tmp_path.glob("selected-*.json"))


def test_old_source_path_is_rejected_without_migration(tmp_path):
    """An old registered path never becomes a current original or an automatic download."""
    catalog = write_selection_catalog(tmp_path)
    primary = catalog.artifacts[0]
    raw = primary.read_bytes(tmp_path)
    old = primary.model_copy(update={"path": "old-original.html"})
    (tmp_path / old.path).write_bytes(raw)
    catalog.model_copy(
        update={"artifacts": tuple(old if a == primary else a for a in catalog.artifacts)}
    ).write(tmp_path / "manifest.json")
    row = next(r for r in source_inventory(tmp_path) if r.document_id == primary.document_id)
    assert not row.ready and not row.can_redownload
    with pytest.raises(ValueError, match="Unsupported current source path"):
        record_selection(tmp_path, (row.issuer,), (row.fiscal_year,), (row.document_id,))
    assert (tmp_path / old.path).read_bytes() == primary.read_bytes(tmp_path) == raw
