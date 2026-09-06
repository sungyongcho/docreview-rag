"""One stable on-disk JSON encoding shared by every evaluation artifact."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Final

JSON_SUFFIX: Final[str] = ".json"


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


def encode_json_document(payload: object, *, sort_keys: bool = True) -> str:
    """Encode one reviewable JSON document with exactly one terminal newline.

    Parameters
    ----------
    payload : object
        JSON-compatible value to serialize.
    sort_keys : bool
        Sort object keys, which every generated artifact wants and a
        human-authored file whose field order is part of its review does not.

    Returns
    -------
    str
        Two-space indented, non-ASCII-preserving JSON text.

    Raises
    ------
    ValueError
        If the payload contains a non-finite number.
    TypeError
        If the payload contains a value JSON cannot encode.

    Notes
    -----
    Every evaluation file narrows through this encoder, so two runs that recorded
    the same evidence produce byte-identical bytes whatever wrote them.
    """
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=sort_keys,
        )
        + "\n"
    )


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
    artifact_path.write_text(encode_json_document(payload), encoding="utf-8")
    return artifact_path
