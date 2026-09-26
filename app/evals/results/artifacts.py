"""One stable on-disk JSON encoding shared by every evaluation artifact."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Final

from app.evals.results.identity import EVALUATED_GOLDEN_KEY, evaluated_golden_sha256

JSON_SUFFIX: Final[str] = ".json"


class EvaluationArtifacts:
    """Read stored evaluation evidence within one configured directory."""

    def __init__(self, directory: Path) -> None:
        """Resolve the allowed directory once, before any artifact paths are read."""
        self.directory = directory.resolve()

    def read(
        self, raw: str, *, max_bytes: int | None = None, max_cases: int | None = None
    ) -> dict[str, Any]:
        """Confine reads before filesystem inspection and apply the caller's public limits."""
        path = Path(raw).resolve()
        if path.parent != self.directory:
            raise ValueError("evaluation artifact is outside the configured directory")
        if max_bytes is not None and path.stat().st_size > max_bytes:
            raise ValueError("evaluation artifact exceeds the byte limit")
        payload = read_strict_json(path, error=ValueError)
        if not isinstance(payload, dict):
            raise ValueError("evaluation artifact root must be an object")
        if max_cases is not None:
            cases = payload.get("cases")
            if not isinstance(cases, list) or len(cases) > max_cases:
                raise ValueError("evaluation artifact exceeds the case limit")
        return payload


def cases_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index complete case identities without discarding malformed or duplicate rows."""
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("evaluation artifact cases must be an array")
    indexed = {}
    for item in cases:
        golden = item.get("golden") if isinstance(item, dict) else None
        case_id = golden.get("id") if isinstance(golden, dict) else None
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("evaluation artifact case requires a nonblank string id")
        if case_id in indexed:
            raise ValueError("evaluation artifact contains duplicate case ids")
        indexed[case_id] = item
    return indexed


def recorded_evaluation_cases(
    payload: dict[str, Any], *, suite: str, config: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Verify artifact settings and exact evaluated cases against the stored result."""
    if payload.get("suite") != suite or payload.get("config") != config:
        raise ValueError("evaluation artifact does not match the stored configuration")
    cases = cases_by_id(payload)
    digest = evaluated_golden_sha256([case["golden"] for case in cases.values()])
    if config.get(EVALUATED_GOLDEN_KEY) != digest:
        raise ValueError("evaluation artifact does not match the recorded golden cases")
    return cases


def read_strict_json(path: str | Path, *, error: type[Exception]) -> object:
    """Read one UTF-8 JSON file, rejecting duplicate keys instead of merging them.

    Parameters
    ----------
    path : str | Path
        JSON file to read.
    error : type[Exception]
        Exception class raised by this reader, so each caller reports failures in
        its own domain instead of wrapping a foreign one.

    Returns
    -------
    object
        Parsed JSON value; callers narrow the expected root type themselves.

    Raises
    ------
    error
        If the file cannot be read as UTF-8 JSON or contains a duplicate key.

    Notes
    -----
    Duplicate keys are only visible in the ``object_pairs_hook`` before pairs
    merge into a dictionary; after parsing the loss would be silent. The hook
    records them rather than raising, because an exception raised inside it would
    have to pass back through the ``JSONDecodeError`` handler below.
    """
    json_path = Path(path)
    duplicates: list[str] = []

    def _record_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        """Merge pairs into a dict, noting every repeated key."""
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result

    try:
        payload = json.loads(
            json_path.read_text(encoding="utf-8"),
            object_pairs_hook=_record_duplicate_keys,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise error(f"cannot read valid UTF-8 JSON from {json_path}: {exc}") from exc
    if duplicates:
        raise error(f"duplicate JSON key: {duplicates[0]}")
    return payload


def utc_text(value: datetime) -> str:
    """Format a timezone-aware datetime as a UTC ``Z`` timestamp.

    Every artifact records instants through this function, so equivalent instants
    in different time zones serialize identically.

    Raises
    ------
    ValueError
        If ``value`` is naive or otherwise lacks a UTC offset.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("recorded_at must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def write_json_artifact(path: str | Path, payload: dict[str, object]) -> Path:
    """Write one reviewable UTF-8 JSON artifact.

    Serialization uses sorted keys, two-space indentation, preserved non-ASCII
    text, and exactly one terminal newline, so two runs that measured the same
    evidence produce byte-identical files.

    Parameters
    ----------
    path : str | Path
        Destination whose filename must use the ``.json`` suffix.
    payload : dict[str, object]
        JSON-compatible evidence to serialize.

    Returns
    -------
    Path
        Normalized destination path after a successful write.

    Raises
    ------
    ValueError
        If the destination does not end in ``.json`` or the payload contains a
        non-finite number.
    TypeError
        If the payload contains a value JSON cannot encode.
    OSError
        If the parent directory cannot be created or the artifact cannot be written.
    """
    artifact_path = Path(path)
    if artifact_path.suffix != JSON_SUFFIX:
        raise ValueError("evaluation artifact path must end in .json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
    artifact_path.write_text(text + "\n", encoding="utf-8")
    return artifact_path
