"""Canonical module selection and deterministic fixtures for the M4 progress harness."""

import importlib
import os
from types import ModuleType

import pytest

DEFAULT_WORKFLOW_MODULE = "app.llm"
DEFAULT_GRAPH_MODULE = "app.workflow"


def load_workflow_module() -> ModuleType:
    """Load the module selected by ``WORKFLOW_MODULE``."""
    name = os.getenv("WORKFLOW_MODULE", DEFAULT_WORKFLOW_MODULE)
    return importlib.import_module(name)


@pytest.fixture(scope="session")
def W() -> ModuleType:
    """LLM foundation module selected by ``WORKFLOW_MODULE``."""
    return load_workflow_module()


@pytest.fixture(scope="session")
def G() -> ModuleType:
    """Workflow graph module selected by ``WORKFLOW_MODULE``."""
    name = os.getenv("WORKFLOW_MODULE", DEFAULT_GRAPH_MODULE)
    return importlib.import_module(name)
