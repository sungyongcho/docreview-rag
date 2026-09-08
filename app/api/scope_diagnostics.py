"""Preserve actionable manifest failures without disclosing developer detail in production."""

from collections.abc import Iterable
import json
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from app.api.errors import ApiProblemError
from app.observability.persistence import redact_sensitive_text


def manifest_problem(
    error: Exception, root: Path, *, developer: bool, secret_values: Iterable[str] = ()
) -> ApiProblemError:
    """Classify the actual load failure and keep a bounded, sanitized diagnostic in DEV."""
    cause: Literal[
        "missing_file", "invalid_json", "invalid_manifest", "alias_conflict", "permission"
    ]
    if isinstance(error, PermissionError):
        cause = "permission"
    elif isinstance(error, FileNotFoundError):
        cause = "missing_file"
    elif isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)) or (
        isinstance(error, ValidationError)
        and any(item["type"] == "json_invalid" for item in error.errors())
    ):
        cause = "invalid_json"
    elif "alias" in str(error).lower() and any(
        word in str(error).lower() for word in ("duplicate", "conflict", "ambiguous")
    ):
        cause = "alias_conflict"
    else:
        cause = "invalid_manifest"
    repository = Path(__file__).resolve().parents[2]
    try:
        path = (root / "manifest.json").relative_to(repository).as_posix()
    except ValueError:
        path = "manifest.json"
    detail = redact_sensitive_text(str(error), secret_values=secret_values).replace(
        str(root / "manifest.json"), path
    )[:1500]
    return ApiProblemError(
        status_code=503,
        code="query_scope_unavailable",
        message="Query scope metadata is unavailable.",
        cause=cause if developer else None,
        detail=f"{type(error).__name__}: {detail}" if developer else None,
        path=path if developer else None,
        failed_stage="gate",
    )
