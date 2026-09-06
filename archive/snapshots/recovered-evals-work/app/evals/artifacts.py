"""One stable on-disk JSON encoding shared by every evaluation artifact."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path


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
    if artifact_path.suffix != ".json":
        raise ValueError("evaluation artifact path must end in .json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    artifact_path.write_text(encoded + "\n", encoding="utf-8")
    return artifact_path
