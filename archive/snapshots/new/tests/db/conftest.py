"""Module-switch fixtures for the M1.4 learner harness."""

import importlib
import os

import pytest

SEED_MODULE_NAME = os.getenv("SEED_MODULE", "app.ingestion.seed")


@pytest.fixture(scope="session")
def S():
    """Seed module selected by ``SEED_MODULE``."""
    return importlib.import_module(SEED_MODULE_NAME)
