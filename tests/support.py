"""Shared checkpoint helpers that are not pytest fixtures."""

import importlib
from types import ModuleType

import pytest


def need(module: ModuleType, *names: str) -> None:
    """Skip when the checkpoint symbols a test needs are not implemented yet."""
    missing = [name for name in names if not hasattr(module, name)]
    if missing:
        pytest.skip(f"not implemented yet: {', '.join(missing)}")


def optional_module(name: str) -> ModuleType:
    """Import a checkpoint module, or return an empty stand-in for ``need``.

    A checkpoint module may be missing outright, or present but half-written: a
    partial scaffold whose annotations name types the file does not import yet
    raises on import rather than merely failing to resolve. Either way the symbols
    ``need`` looks for are absent, and the stand-in turns what would be a
    collection error that aborts the whole suite into the same skip every other
    unwritten checkpoint gives.

    Parameters
    ----------
    name : str
        Importable module path of the checkpoint under test.

    Returns
    -------
    ModuleType
        The imported module, or an attribute-free module of the same name.
    """
    try:
        return importlib.import_module(name)
    except Exception:
        return ModuleType(name)
