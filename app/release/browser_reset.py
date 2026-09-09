"""Expose only the explicit fresh-start marker belonging to this checkout."""

import json
from pathlib import Path
from uuid import UUID

BROWSER_RESET_PATH = Path(__file__).resolve().parents[2] / "data/browser-reset.json"


def browser_reset_id() -> str | None:
    """Read a fresh-start receipt; ordinary application startup never creates one."""
    try:
        raw = json.loads(BROWSER_RESET_PATH.read_text())
    except FileNotFoundError:
        return None
    if (
        not isinstance(raw, dict)
        or set(raw) != {"reset_id"}
        or not isinstance(raw["reset_id"], str)
    ):
        raise ValueError("Invalid DocReview browser reset marker.")
    return str(UUID(raw["reset_id"]))
