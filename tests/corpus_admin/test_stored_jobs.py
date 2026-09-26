"""Stored corpus job conversion tests."""

import asyncio

import pytest

from app.corpus_admin.stored_jobs import command_from_stored, command_payload
from app.corpus_admin.types import AdminCommand
from tests.corpus_admin.support import LedgerStore


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
        ("rebuild_bm25", {"identifiers": "NVDA"}),
        ("rebuild_bm25", {"years": ["2024"]}),
        ("rebuild_bm25", {"expected_documents": True}),
        ("rebuild_bm25", {"manifest": []}),
        ("unsupported", {}),
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
