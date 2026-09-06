"""Shared test helpers that are not pytest fixtures."""

import importlib
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parent.parent


def need(module: ModuleType, *names: str) -> None:
    """Skip when learner-module symbols are not implemented yet."""
    missing = [n for n in names if not hasattr(module, n)]
    if missing:
        pytest.skip(f"not implemented yet: {', '.join(missing)}")


def optional_module(name: str) -> ModuleType:
    """Import a checkpoint module, or return an empty stand-in for ``need``.

    A checkpoint module may be missing outright, or present but half-written: the
    learner branch ships partial scaffolds whose annotations name types the file
    does not import yet, so importing one raises rather than failing to resolve.
    Either way the symbols ``need`` looks for are absent, and the stand-in turns
    what would be a collection error into the same skip every other checkpoint
    gives before its file exists.
    """
    try:
        return importlib.import_module(name)
    except Exception:
        return ModuleType(name)
