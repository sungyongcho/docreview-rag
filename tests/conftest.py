"""Repository-wide pytest command-line options."""

import os

import pytest

from tests.live_postgres import EXPECT_LIVE_POSTGRES_ENV


def pytest_addoption(parser: pytest.Parser) -> None:
    """Expose an explicit local gate for live PostgreSQL coverage."""
    parser.addoption(
        "--require-live-postgres",
        action="store_true",
        help="Fail instead of skipping when a live PostgreSQL prerequisite is unavailable.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Map the repository option onto the shared live-test policy."""
    if config.getoption("--require-live-postgres"):
        os.environ[EXPECT_LIVE_POSTGRES_ENV] = "1"
