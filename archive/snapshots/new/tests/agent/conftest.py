"""Module switch for the M9 learner harness."""

import importlib
import os
from types import ModuleType

import pytest

DEFAULT_AGENT_MODULE = "app.agent"


def load_agent_module() -> ModuleType:
    """Load the module selected by ``AGENT_MODULE``."""
    name = os.getenv("AGENT_MODULE", DEFAULT_AGENT_MODULE)
    return importlib.import_module(name)


@pytest.fixture(scope="session")
def AG() -> ModuleType:
    """Agent module selected by ``AGENT_MODULE``."""
    return load_agent_module()
