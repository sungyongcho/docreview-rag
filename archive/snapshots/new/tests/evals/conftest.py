"""Module-switch fixture for the M3 learner harness."""

import importlib
import os
from types import ModuleType

import pytest

DEFAULT_EVAL_MODULE = "app.evals"


def load_eval_module() -> ModuleType:
    """Load the module selected by ``EVAL_MODULE``."""
    name = os.getenv("EVAL_MODULE", DEFAULT_EVAL_MODULE)
    return importlib.import_module(name)


@pytest.fixture(scope="session")
def E() -> ModuleType:
    """Evaluation module selected by ``EVAL_MODULE``."""
    return load_eval_module()
