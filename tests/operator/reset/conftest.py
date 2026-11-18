"""Fixtures shared by the reset tests."""

from pathlib import Path

import pytest


@pytest.fixture
def state_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A per-test directory for the reset audit and lock, outside the reset root.

    Every service a test builds shares it, as operator processes share the system
    temporary directory, and nothing reaches that directory itself.
    """
    return tmp_path_factory.mktemp("reset-state")
