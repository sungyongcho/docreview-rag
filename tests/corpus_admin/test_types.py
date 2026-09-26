"""Corpus administrator command validation tests."""

import pytest

from app.corpus_admin.types import AdminCommand


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
