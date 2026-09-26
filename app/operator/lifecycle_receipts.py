"""Read the existing fresh-start receipt without executing reset or exposing host paths."""

import json
from pathlib import Path
import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def receipt_path(root: Path, command: str) -> Path:
    """Store receipts outside the deletion set in the current worktree's Git directory.

    The lifecycle commands write here and the operator service reads here, so the path
    rule lives with the reader in ``app`` and the ``scripts`` side imports it.
    """
    output = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--git-path", f"docreview-receipts/{command}.json"],
        text=True,
    )
    path = Path(output.strip())
    return path if path.is_absolute() else root / path


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
