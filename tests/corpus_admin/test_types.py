"""Corpus administrator command validation tests."""

import asyncio

import pytest

from app.corpus_admin.types import AdminCommand, command_from_stored, command_payload
from tests.corpus_admin.support import LedgerStore


@pytest.mark.parametrize(
    "build_command,reason",
    [
        pytest.param(
            lambda: AdminCommand("acquire_edgar"),
            "requires identifiers and fiscal years",
            id="acquisition-without-companies-or-years",
        ),
        pytest.param(
            lambda: AdminCommand("acquire_dart", identifiers=("005930",), years=(1800,)),
            "between 1900 and 2100",
            id="acquisition-year-outside-the-supported-range",
        ),
        pytest.param(
            lambda: AdminCommand("ingest_manifest", manifest=""),
            "requires a manifest and selection_id",
            id="ingestion-with-a-blank-manifest",
        ),
        pytest.param(
            lambda: AdminCommand(
                "ingest_manifest",
                manifest="manifest.json",
                selection_id="selected",
                expected_documents=0,
            ),
            "Input should be greater than 0",
            id="ingestion-expecting-zero-documents",
        ),
    ],
)
def test_admin_commands_reject_incomplete_or_unsafe_inputs(build_command, reason) -> None:
    """Reject hidden defaults and invalid counts before an operation is queued."""
    with pytest.raises(ValueError, match=reason):
        build_command()


@pytest.mark.parametrize(
    "document_ids", [None, (), ("filing-a", "filing-a")], ids=["absent", "empty", "duplicated"]
)
def test_selected_command_requires_exact_document_ids(document_ids):
    """Internal commands reject absent or duplicate selected identities before queueing."""
    with pytest.raises(ValueError, match="nonempty unique document_ids"):
        AdminCommand(
            "ingest_selected", identifiers=("NVDA",), years=(2024,), document_ids=document_ids
        )


def test_selection_command_restores_from_stored_job(tmp_path):
    """Restore the identical selection when retrying a persisted operation."""

    async def scenario():
        """Create the ledger row without starting any database work."""
        store = LedgerStore()
        command = AdminCommand("ingest_manifest", manifest="manifest.json", selection_id="selected")
        row = await store.create(
            job_id="selection",
            domain="corpus",
            kind=command.kind,
            request_json=command_payload(command),
        )
        assert command_from_stored(row) == command

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind,payload",
    [
        pytest.param("rebuild_bm25", {"identifiers": "NVDA"}, id="identifiers-as-a-string"),
        pytest.param("rebuild_bm25", {"years": ["2024"]}, id="year-as-a-string"),
        pytest.param("rebuild_bm25", {"expected_documents": True}, id="document-count-as-a-bool"),
        pytest.param("rebuild_bm25", {"manifest": []}, id="manifest-as-a-list"),
        pytest.param("unsupported", {}, id="unknown-job-kind"),
        pytest.param("rebuild_bm25", {"old_argument": True}, id="unknown-command-field"),
    ],
)
def test_stored_command_rejects_invalid_json_types(kind, payload):
    """Reject malformed persisted commands instead of coercing retry inputs."""

    async def scenario():
        """Validate one in-memory ledger row without starting an operation."""
        store = LedgerStore()
        row = await store.create(job_id="invalid", domain="corpus", kind=kind, request_json=payload)
        with pytest.raises(ValueError):
            command_from_stored(row)

    asyncio.run(scenario())
