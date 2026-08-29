"""Canonical graph-module selection for the M4 workflow progress harness."""

import os
from types import ModuleType

import pytest

from tests.support import optional_module

GRAPH_MODULE_ENV = "WORKFLOW_GRAPH_MODULE"
DEFAULT_GRAPH_MODULE = "app.workflow"


@pytest.fixture(scope="session")
def G() -> ModuleType:
    """Workflow graph module selected by ``WORKFLOW_GRAPH_MODULE``.

    Each harness slot owns a distinct variable, so pointing the graph at an
    alternative implementation cannot silently redirect the observability slot to
    the same module and make every test fail on a missing attribute instead.
    """
    return optional_module(os.getenv(GRAPH_MODULE_ENV, DEFAULT_GRAPH_MODULE))
