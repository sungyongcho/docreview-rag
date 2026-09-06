"""Shared availability policy for optional live PostgreSQL tests."""

import os
from typing import NoReturn

import pytest

EXPECT_LIVE_POSTGRES_ENV = "DOCREVIEW_EXPECT_LIVE_POSTGRES"


def live_postgres_unavailable(detail: str) -> NoReturn:
    """Fail when live PostgreSQL was required, otherwise skip explicitly."""
    if os.getenv(EXPECT_LIVE_POSTGRES_ENV) == "1":
        pytest.fail(f"Expected live PostgreSQL, but it is unavailable: {detail}")
    pytest.skip(f"PostgreSQL is unavailable: {detail}")
