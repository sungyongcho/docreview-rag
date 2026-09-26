"""Corpus administrator command validation tests."""

import pytest

from app.corpus_admin.types import AdminCommand


@pytest.mark.parametrize(
    "command",
    [
        lambda: AdminCommand("acquire_edgar"),
        lambda: AdminCommand("acquire_dart", identifiers=("005930",), years=(1800,)),
        lambda: AdminCommand("ingest_manifest", manifest=""),
        lambda: AdminCommand("ingest_manifest", manifest="manifest.json", expected_documents=0),
    ],
)
def test_admin_commands_reject_incomplete_or_unsafe_inputs(command) -> None:
    """Reject hidden defaults and invalid counts before an operation is queued."""
    with pytest.raises(ValueError):
        command()


@pytest.mark.parametrize("document_ids", [None, (), ("filing-a", "filing-a")])
def test_selected_command_requires_exact_document_ids(document_ids):
    """Internal commands reject absent or duplicate selected identities before queueing."""
    with pytest.raises(ValueError, match="nonempty unique document_ids"):
        AdminCommand(
            "ingest_selected", identifiers=("NVDA",), years=(2024,), document_ids=document_ids
        )
