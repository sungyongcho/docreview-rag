"""Repository-wide pytest command-line options."""

import os
from pathlib import Path

import pytest

from tests.live_postgres import EXPECT_LIVE_POSTGRES_ENV


@pytest.fixture(autouse=True)
def _isolated_public_allowance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the shared public allowance ledger inside each test's temporary directory."""
    monkeypatch.setenv(
        "DOCREVIEW_PUBLIC_ALLOWANCE_PATH",
        str(tmp_path / "public-ai-limits.sqlite3"),
    )


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
