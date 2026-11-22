"""Repository-wide pytest command-line options."""

from collections.abc import Generator
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


@pytest.fixture
def no_evidence_holds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report no held report period to a search whose session is a stand-in.

    Retrieval reads the holds of its scope from the database after ranking; a test that
    replaces the ranking functions and passes no real session replaces that read too.
    """

    async def none(session: object, filters: object) -> tuple[()]:
        """Return no hold without touching the stand-in session."""
        del session, filters
        return ()

    monkeypatch.setattr("app.retrieval.search.service.scope_holds", none)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Expose gates for checks that need a live or prepared environment."""
    parser.addoption(
        "--require-live-postgres",
        action="store_true",
        help="Fail instead of skipping when a live PostgreSQL prerequisite is unavailable.",
    )
    parser.addoption(
        "--require-prepared-environment",
        action="store_true",
        help="Fail when a selected prepared_environment test is skipped.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Map the repository option onto the shared live-test policy."""
    if config.getoption("--require-live-postgres"):
        os.environ[EXPECT_LIVE_POSTGRES_ENV] = "1"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Turn a selected prepared check's skip into a release failure."""
    report = yield
    if (
        report.skipped
        and item.config.getoption("--require-prepared-environment")
        and item.get_closest_marker("prepared_environment") is not None
    ):
        reason = report.longrepr[-1] if isinstance(report.longrepr, tuple) else report.longrepr
        report.outcome = "failed"
        report.longrepr = f"Required prepared check {item.nodeid} skipped: {reason}"
    return report
