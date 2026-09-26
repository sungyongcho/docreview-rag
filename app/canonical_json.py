"""Serialize values to one deterministic JSON text for hashing, comparison and prompts."""

import json


def canonical_json(value: object) -> str:
    """Serialize ``value`` as compact, key-sorted JSON without NaN or infinity.

    The same value always produces the same text, so callers can hash or compare the
    result directly. Keys are sorted at every depth, separators carry no spaces, and
    non-ASCII characters are written as themselves instead of being escaped. NaN and
    infinities are refused because JSON has no portable spelling for them.

    Parameters
    ----------
    value : object
        JSON-compatible value.

    Returns
    -------
    str
        Canonical JSON text.

    Raises
    ------
    ValueError
        If ``value`` contains NaN or an infinity.
    TypeError
        If ``value`` contains an object that JSON cannot represent.
    """
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
