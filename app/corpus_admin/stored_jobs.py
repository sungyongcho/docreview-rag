"""Convert corpus commands and jobs to and from their rows in the shared job ledger.

The ledger keeps each command as JSON so an operator can retry a failed job after a
restart. Restoring a command validates every field strictly: a coerced value would
retry a different command from the one the operator submitted.
"""

from __future__ import annotations

from typing import cast

from pydantic import StrictInt, StrictStr, TypeAdapter

from app.corpus_admin.types import AdminCommand, AdminJob, AdminJobKind, AdminJobStatus
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


_JOB_KIND = TypeAdapter(AdminJobKind)
_COMMAND_IDENTIFIERS = TypeAdapter(tuple[StrictStr, ...])
_COMMAND_YEARS = TypeAdapter(tuple[StrictInt, ...])
_COMMAND_TEXT = TypeAdapter(StrictStr | None)
_COMMAND_COUNT = TypeAdapter(StrictInt | None)
_COMMAND_CONFIRM = TypeAdapter(bool | None)


def command_from_stored(job: StoredJob) -> AdminCommand:
    """Validate persisted JSON before restoring command and retry provenance."""
    payload = job.request_json
    return AdminCommand(
        kind=_JOB_KIND.validate_python(job.kind, strict=True),
        identifiers=_COMMAND_IDENTIFIERS.validate_python(payload.get("identifiers", [])),
        years=_COMMAND_YEARS.validate_python(payload.get("years", [])),
        manifest=_COMMAND_TEXT.validate_python(payload.get("manifest")),
        selection_id=_COMMAND_TEXT.validate_python(payload.get("selection_id")),
        expected_documents=_COMMAND_COUNT.validate_python(payload.get("expected_documents")),
        document_ids=_COMMAND_IDENTIFIERS.validate_python(payload["document_ids"])
        if payload.get("document_ids") is not None
        else None,
        deletion_token=_COMMAND_TEXT.validate_python(payload.get("deletion_token")),
        confirm_delete=_COMMAND_CONFIRM.validate_python(payload.get("confirm_delete"), strict=True),
    )


def job_from_stored(job: StoredJob) -> AdminJob:
    """Project a stored job onto the existing corpus job response contract."""
    return AdminJob(
        job_id=job.job_id,
        command=command_from_stored(job),
        status=cast("AdminJobStatus", job.status),
        stage=job.stage,
        current=job.current,
        total=job.total,
        message=job.message,
        detail_current=job.detail_current,
        detail_total=job.detail_total,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_code=job.error_code,
        result_refs=job.result_refs,
    )
