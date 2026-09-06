"""Canonical module fixture for the M2 progress harness."""

import importlib
import os
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy.engine import URL, make_url

from app.config import Settings, get_settings

DEFAULT_RETRIEVAL_MODULE = "app.retrieval"


def load_retrieval_module() -> ModuleType:
    """Load the module selected by ``RETRIEVAL_MODULE``."""
    name = os.getenv("RETRIEVAL_MODULE", DEFAULT_RETRIEVAL_MODULE)
    return importlib.import_module(name)


def make_settings(**overrides: Any) -> Settings:
    """Build ``Settings`` isolated from the developer's ``.env`` file.

    pydantic-settings accepts ``_env_file`` at runtime, but Pylance only sees
    the field-based synthesized signature, so the one suppression lives here.
    """
    return Settings(_env_file=None, **overrides)  # pyright: ignore[reportCallIssue]


@pytest.fixture(scope="session")
def R() -> ModuleType:
    """Retrieval module selected by ``RETRIEVAL_MODULE``."""
    return load_retrieval_module()


@pytest.fixture(scope="session")
def postgres_test_database_url() -> URL:
    """Return the configured local PostgreSQL URL without DNS executor work."""
    url = make_url(get_settings().database_url)
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.skip("PostgreSQL integration tests require a loopback database URL")
    return url.set(host="127.0.0.1")
