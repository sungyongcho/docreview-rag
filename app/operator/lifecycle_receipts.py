"""Read the existing fresh-start receipt without executing reset or exposing host paths."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scripts.stack.fresh import receipt_path


class LifecycleReceipt(BaseModel):
    """Expose only the recorded outcome needed by the browser notification center."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    command: Literal["start-fresh"]
    updated: float = Field(gt=0)
    status: Literal["running", "succeeded", "failed"]
    completed: tuple[str, ...]
    restarted: bool | None = None
    error: str | None = None


def lifecycle_receipts(root: Path) -> tuple[LifecycleReceipt, ...]:
    """Read a bounded, validated receipt using the command's existing Git-directory path."""
    path = receipt_path(root, "start-fresh")
    if not path.exists():
        return ()
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError("Invalid fresh-start receipt file")
    value = json.loads(path.read_text())
    return (LifecycleReceipt.model_validate(value),)
