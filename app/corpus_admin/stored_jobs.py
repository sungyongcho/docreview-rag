"""Convert corpus commands and jobs to and from their rows in the shared job ledger.

The ledger keeps each command as JSON so an operator can retry a failed job after a
restart. Restoring a command validates every field strictly: a coerced value would
retry a different command from the one the operator submitted.
"""

from __future__ import annotations

import json

from pydantic import TypeAdapter

from app.corpus_admin.types import AdminCommand
from app.operator.jobs import StoredJob


def command_payload(command: AdminCommand) -> dict[str, object]:
    """Serialize one validated command for persistent retry provenance."""
    payload: dict[str, object] = {
        "identifiers": list(command.identifiers),
        "years": list(command.years),
        "manifest": command.manifest,
        "selection_id": command.selection_id,
        "expected_documents": command.expected_documents,
    }
    if command.document_ids is not None:
        payload["document_ids"] = list(command.document_ids)
    if command.deletion_token is not None:
        payload.update(deletion_token=command.deletion_token, confirm_delete=command.confirm_delete)
    return payload


_COMMAND = TypeAdapter(AdminCommand)


def command_from_stored(job: StoredJob) -> AdminCommand:
    """Validate persisted JSON before restoring command and retry provenance."""
    return _COMMAND.validate_json(json.dumps({**job.request_json, "kind": job.kind}), strict=True)
