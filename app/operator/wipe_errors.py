"""The reset refusal error and the diagnosis the operator API returns for any reset failure."""

from __future__ import annotations

from typing import Any


class WipeError(RuntimeError):
    """A reset cannot safely proceed against its declared target."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "reset_precondition_failed",
        details: dict[str, Any] | None = None,
        remediation: list[str] | None = None,
    ) -> None:
        """Attach safe diagnostic evidence while preserving the existing error message."""
        super().__init__(message)
        self.diagnosis = {
            "code": code,
            "details": details or {},
            "remediation": remediation
            or ["Resolve the reported condition, then check reset availability again."],
        }


def diagnose_wipe_error(error: Exception) -> dict[str, Any]:
    """Keep known reset evidence and identify unclassified inspection failures honestly."""
    if isinstance(error, WipeError):
        return error.diagnosis
    return {
        "code": "reset_inspection_failed",
        "details": {"error_type": type(error).__name__},
        "remediation": [
            "The cause is unknown. Review the operator error and local service status, "
            "then check reset availability again."
        ],
    }
